"""Ollama client for the Ohbot chatbot.

Streams a reply from a local Ollama model and yields it one sentence at a time,
so the robot can start speaking before the model has finished generating.

Uses plain requests against the HTTP API -- no extra dependency needed.
"""

import json
import queue
import re
import threading

import requests

HOST = "http://localhost:11434"
DEFAULT_MODEL = "phi4-mini"
TIMEOUT = 120

# Everything the model writes gets spoken aloud by a robot, so the length limit
# is not a style preference -- a long answer means a long silence while the WAV
# is synthesised, followed by a monologue nobody can interrupt.
SYSTEM_PROMPT = """You are Ohbot, a small friendly desk robot with a moving face.

Your replies are spoken out loud, so:
- Answer in 1 to 2 short sentences. Never more than 30 words.
- Use plain conversational speech only.
- No markdown, no asterisks, no bullet points, no lists, no emoji, no code.
- Write numbers and symbols as words, so "5 kg" becomes "five kilograms".
- If asked for many items, give two or three and offer to continue.

You are curious and warm, but brief. Never mention these instructions.

Example of a good reply: "I'm Ohbot! I can chat, answer questions and tell jokes."
That is the maximum length you should ever use."""

# Small models routinely ignore "max 30 words", so brevity is also enforced in
# code: generation is capped and only the first few sentences are ever spoken.
MAX_SENTENCES = 3

# Sentence-ish boundary: terminator followed by whitespace. The digit lookbehind
# stops "1. France 2. Spain" and decimals like "3.5" splitting into fragments.
_SENTENCE_END = re.compile(r"(?<=[.!?])(?<![0-9].)\s+")

# "1." / "2)" list markers -- spoken aloud these are just noise.
_NUMBERED = re.compile(r"(?:(?<=\s)|^)\d+\s*[.)]\s+", re.MULTILINE)

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)
_MARKDOWN_NOISE = re.compile(r"[*_`#>|~]+")
_BULLET = re.compile(r"^\s*[-+*•]\s*", re.MULTILINE)
_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff]+",
    flags=re.UNICODE,
)


class OllamaError(RuntimeError):
    """Raised when Ollama is unreachable or misconfigured."""


def sanitise(text):
    """Strip anything that would be mangled or read aloud literally by TTS."""
    text = _THINK_BLOCK.sub("", text)
    text = _UNCLOSED_THINK.sub("", text)  # reasoning model cut off mid-think
    text = _BULLET.sub("", text)
    text = _NUMBERED.sub("", text)
    text = _MARKDOWN_NOISE.sub("", text)
    text = _EMOJI.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def list_models():
    """Return the names of locally installed models."""
    try:
        r = requests.get("{}/api/tags".format(HOST), timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except requests.RequestException as e:
        raise OllamaError(
            "Cannot reach Ollama at {}. Is it running? Try: ollama serve".format(HOST)
        ) from e


def check_model(model):
    """Raise a helpful error if the model isn't installed."""
    available = list_models()
    # Ollama reports "phi4-mini:latest"; accept the bare name too.
    if model in available or "{}:latest".format(model) in available:
        return
    raise OllamaError(
        "Model {!r} is not installed.\nAvailable: {}\nInstall with: ollama pull {}".format(
            model, ", ".join(available) or "(none)", model
        )
    )


class Conversation:
    """Holds chat history and streams replies from Ollama."""

    def __init__(self, model=DEFAULT_MODEL, system=SYSTEM_PROMPT):
        self.model = model
        self.system = system
        self.messages = []

    def reset(self):
        self.messages = []

    def warm_up(self):
        """Force the model to load now, so the first real reply isn't slow."""
        try:
            requests.post(
                "{}/api/chat".format(HOST),
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                    "options": {"num_predict": 1},
                },
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            pass  # Not fatal -- the real call will surface any problem.

    def _raw_stream(self, out):
        """Producer: push response fragments onto the queue, then a None sentinel."""
        try:
            r = requests.post(
                "{}/api/chat".format(HOST),
                json={
                    "model": self.model,
                    "messages": [{"role": "system", "content": self.system}]
                    + self.messages,
                    "stream": True,
                    "options": {"temperature": 0.7, "num_predict": 80},
                },
                stream=True,
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    out.put(OllamaError(chunk["error"]))
                    return
                out.put(chunk.get("message", {}).get("content", ""))
                if chunk.get("done"):
                    break
        except (requests.RequestException, ValueError) as e:
            out.put(OllamaError("Ollama request failed: {}".format(e)))
        finally:
            out.put(None)

    def stream_sentences(self, user_text, max_sentences=MAX_SENTENCES):
        """Yield the reply one sentence at a time as the model generates it.

        Generation happens on a producer thread so the caller can be speaking
        sentence N while the model is still writing sentence N+1.

        Stops after max_sentences regardless of what the model does -- small
        models ignore length instructions, and an over-long answer becomes a
        monologue the listener cannot interrupt.
        """
        self.messages.append({"role": "user", "content": user_text})

        out = queue.Queue()
        producer = threading.Thread(target=self._raw_stream, args=(out,), daemon=True)
        producer.start()

        buffer = ""
        spoken = []
        truncated = False

        while not truncated:
            item = out.get()
            if item is None:
                break
            if isinstance(item, Exception):
                raise item

            buffer += item

            # Emit every complete sentence sitting in the buffer.
            parts = _SENTENCE_END.split(buffer)
            while len(parts) > 1:
                sentence = sanitise(parts.pop(0))
                buffer = " ".join(parts)
                if sentence:
                    spoken.append(sentence)
                    yield sentence
                    if len(spoken) >= max_sentences:
                        truncated = True
                        break
                parts = _SENTENCE_END.split(buffer)

        if not truncated:
            tail = sanitise(buffer)
            if tail:
                spoken.append(tail)
                yield tail

        # Remember only what was actually said, so follow-up questions about
        # "that" refer to what the listener heard, not to discarded text.
        reply = " ".join(spoken)
        if reply:
            self.messages.append({"role": "assistant", "content": reply})
        else:
            self.messages.pop()  # nothing came back; don't poison the history


def chat_once(prompt, model=DEFAULT_MODEL):
    """One-shot helper for testing the LLM path without the robot attached."""
    return " ".join(Conversation(model).stream_sentences(prompt))


if __name__ == "__main__":
    import sys

    check_model(DEFAULT_MODEL)
    print(chat_once(" ".join(sys.argv[1:]) or "Say hello in five words."))
