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

# Used for structured emotion/gesture selection. See respond_with_action.
ACTION_TEMPERATURE = 0.3

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


def list_models(host=HOST):
    """Return the names of locally installed models."""
    try:
        r = requests.get("{}/api/tags".format(host), timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except requests.RequestException as e:
        raise OllamaError(
            "Cannot reach Ollama at {}. Is it running? Try: ollama serve".format(host)
        ) from e


def check_model(model, host=HOST):
    """Raise a helpful error if the model isn't installed."""
    available = list_models(host)
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

    def __init__(
        self,
        model=DEFAULT_MODEL,
        system=SYSTEM_PROMPT,
        host=HOST,
        temperature=0.7,
        num_predict=80,
    ):
        self.model = model
        self.system = system
        self.host = host
        self.temperature = temperature
        self.num_predict = num_predict
        self.messages = []

    def reset(self):
        self.messages = []

    def warm_up(self):
        """Force the model to load now, so the first real reply isn't slow."""
        try:
            requests.post(
                "{}/api/chat".format(self.host),
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
                "{}/api/chat".format(self.host),
                json={
                    "model": self.model,
                    "messages": [{"role": "system", "content": self.system}]
                    + self.messages,
                    "stream": True,
                    "options": {
                        "temperature": self.temperature,
                        "num_predict": self.num_predict,
                    },
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


    # -- structured "act as you speak" mode --------------------------------

    def respond_with_action(self, user_text, emotions, gestures, temperature=None):
        """Get a reply plus the emotion and gesture to perform with it.

        Uses Ollama's `format` JSON-schema mode rather than the tools API.
        phi4-mini advertises a `tools` capability but returned tool_calls: None
        on every attempt and refused outright ("I'm unable to set a real-world
        object's emotional state"). Schema-constrained output parsed 3/3 first
        time, in 0.5-0.7s.

        Returns a dict: {say, emotion, gesture, gaze_x, gaze_y}.
        """
        schema = {
            "type": "object",
            "properties": {
                "say": {"type": "string"},
                "emotion": {"type": "string", "enum": list(emotions)},
                "gesture": {"type": "string", "enum": list(gestures)},
                "gaze_x": {"type": "integer"},
                "gaze_y": {"type": "integer"},
            },
            "required": ["say", "emotion", "gesture"],
        }

        self.messages.append({"role": "user", "content": user_text})
        # Gestures are described, not just named -- see expression.GESTURE_MEANINGS.
        try:
            import expression

            gesture_menu = expression.gesture_menu()
        except Exception:
            gesture_menu = "\n".join("- {}".format(g) for g in gestures)

        system = self.system + ACTION_SUFFIX.format(
            emotions=", ".join(emotions), gestures=gesture_menu
        )

        try:
            r = requests.post(
                "{}/api/chat".format(self.host),
                json={
                    "model": self.model,
                    "messages": [{"role": "system", "content": system}] + self.messages,
                    "stream": False,
                    "format": schema,
                    "options": {
                        # Cooler than plain chat on purpose. Picking the right
                        # emotion is a classification, not a creative act: at
                        # 0.7 the same input scored 12/12 on one run and 10/12
                        # on the next, with "what is two plus two?" drawing
                        # `excited`. Lower temperature stabilises the choice.
                        "temperature": (
                            ACTION_TEMPERATURE if temperature is None else temperature
                        ),
                        "num_predict": self.num_predict,
                    },
                },
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            content = r.json().get("message", {}).get("content", "")
            action = json.loads(content)
        except (requests.RequestException, ValueError) as e:
            self.messages.pop()
            raise OllamaError("Structured request failed: {}".format(e)) from e

        action["say"] = sanitise(action.get("say", ""))
        if action["say"]:
            self.messages.append({"role": "assistant", "content": action["say"]})
        else:
            self.messages.pop()
        return action


# Appended to the persona prompt in action mode. Kept separate so personas
# stay readable and don't each have to repeat the movement instructions.
ACTION_SUFFIX = """

You also control your own face and body. With every reply choose:
- emotion: one of {emotions}
- gaze_x (0 = your right, 5 = ahead, 10 = your left) and gaze_y (0 = down, 10 = up)
- gesture, chosen by MEANING from this list:
{gestures}

Match them to what the person actually said. Bad news gets sympathy and a slow
nod, not cheerfulness. Never shake your head at good news -- that reads as "no".
Prefer subtle choices; constant big gestures look twitchy rather than expressive."""


def chat_once(prompt, model=DEFAULT_MODEL):
    """One-shot helper for testing the LLM path without the robot attached."""
    return " ".join(Conversation(model).stream_sentences(prompt))


if __name__ == "__main__":
    import sys

    check_model(DEFAULT_MODEL)
    print(chat_once(" ".join(sys.argv[1:]) or "Say hello in five words."))
