"""Talk to an Ohbot robot powered by a local Ollama model.

    python ohbot_chat.py                     # type to chat
    python ohbot_chat.py --model qwen3.6:35b # pick a different model
    python ohbot_chat.py --voice             # speak instead of typing
    python ohbot_chat.py --no-idle           # disable blinking / head drift

Run from the project root so the ohbotData/ calibration folder is shared.
Requires Ollama running locally (`ollama serve`) and the Ohbot plugged in.
"""

import argparse
import sys

import llm
from robot import Ohbot

BANNER = """Ohbot chat -- model: {model}
Type and press enter. Commands: /reset (forget context), /quit
"""


def parse_args():
    p = argparse.ArgumentParser(description="Chat with an Ohbot robot.")
    p.add_argument("--model", default=llm.DEFAULT_MODEL, help="Ollama model name")
    p.add_argument("--voice", action="store_true", help="use the microphone instead of typing")
    p.add_argument("--no-idle", action="store_true", help="disable idle blinking and drift")
    p.add_argument(
        "--max-sentences",
        type=int,
        default=llm.MAX_SENTENCES,
        help="hard cap on spoken sentences per reply",
    )
    return p.parse_args()


def respond(bot, convo, text, max_sentences):
    """Stream a reply and speak it sentence by sentence."""
    bot.set_state("thinking")
    print("Ohbot: ", end="", flush=True)

    said_anything = False
    try:
        for sentence in convo.stream_sentences(text, max_sentences=max_sentences):
            print(sentence, end=" ", flush=True)
            bot.speak(sentence)
            said_anything = True
    except llm.OllamaError as e:
        print("\n[llm error] {}".format(e), file=sys.stderr)
        bot.speak("Sorry, my brain is not responding.")
    finally:
        print()

    if not said_anything:
        bot.speak("Sorry, I did not catch that.")

    bot.set_state("listening")


def typed_inputs():
    """Yield lines typed at the prompt until EOF."""
    while True:
        try:
            yield input("You: ").strip()
        except EOFError:
            return


def main():
    args = parse_args()

    # Fail fast with a useful message before touching the robot.
    try:
        llm.check_model(args.model)
    except llm.OllamaError as e:
        print(e, file=sys.stderr)
        return 1

    convo = llm.Conversation(model=args.model)

    if args.voice:
        import voice  # imported lazily: heavy deps, only needed with --voice

        listener = voice.Listener()
        source = lambda bot: listener.listen_loop(bot)  # noqa: E731
        # An empty tuple in typed mode, so the handler below is safe either way.
        mic_errors = (voice.MicrophoneBlocked,)
    else:
        source = lambda bot: typed_inputs()  # noqa: E731
        mic_errors = ()

    print(BANNER.format(model=args.model))
    print("Loading model...", flush=True)
    convo.warm_up()

    with Ohbot(idle=not args.no_idle) as bot:
        bot.speak("Hello! I am ready to chat.")

        try:
            for text in source(bot):
                if not text:
                    continue
                if text in ("/quit", "/exit"):
                    break
                if text == "/reset":
                    convo.reset()
                    print("[context cleared]")
                    continue
                if args.voice:
                    print("You: {}".format(text))

                respond(bot, convo, text, args.max_sentences)
        except KeyboardInterrupt:
            print()
        except mic_errors as e:
            print("\n[microphone] {}".format(e), file=sys.stderr)
            bot.speak("I cannot hear anything. Check my microphone permission.")

        bot.speak("Goodbye!")

    print("Motors detached. Bye.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
