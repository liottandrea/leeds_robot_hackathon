"""Talk to an Ohbot robot powered by a local Ollama model.

    python ohbot_chat.py                      # type to chat, with expression
    python ohbot_chat.py --mode beats         # expression changes mid-reply
    python ohbot_chat.py --mode plain         # no expression, just speech
    python ohbot_chat.py --voice              # speak instead of typing
    python ohbot_chat.py --persona pirate     # different personality and voice
    python ohbot_chat.py --list-devices       # show audio devices, then exit

Settings live in config.yaml, overridden by config.local.yaml (git-ignored,
for machine-specific things like audio devices), overridden by these flags.

Run from the project root so the ohbotData/ calibration folder is shared.
Requires Ollama running locally (`ollama serve`) and the Ohbot plugged in.
"""

import argparse
import sys

from ohbot_kit import audio, expression, llm, tts
from ohbot_kit import config as config_mod
from ohbot_kit.robot import Ohbot

BANNER = """Ohbot chat -- model: {model}, voice: {engine}, persona: {persona}, mode: {mode}
Audio in: {mic} | out: {out}
Type and press enter. Commands: /reset (forget context), /quit
"""


def parse_args():
    p = argparse.ArgumentParser(description="Chat with an Ohbot robot.")
    # Config-backed options default to None so "not given" is distinguishable
    # from "given the same value as the default".
    p.add_argument("--config", default=config_mod.DEFAULT_PATH, help="path to config.yaml")
    p.add_argument("--persona", default=None, help="persona from config.yaml")
    p.add_argument("--model", default=None, help="Ollama model name")
    p.add_argument("--voice", action="store_true", help="use the microphone instead of typing")
    p.add_argument("--no-idle", action="store_true", help="disable idle blinking and drift")
    p.add_argument("--tts", choices=("kokoro", "say"), default=None, help="speech engine")
    p.add_argument("--voice-name", default=None, help="Kokoro voice, e.g. af_heart, bf_emma")
    p.add_argument("--speed", type=float, default=None, help="speech speed")
    p.add_argument("--max-sentences", type=int, default=None, help="cap on spoken sentences")
    p.add_argument("--input-device", default=None, help="microphone name substring")
    p.add_argument("--output-device", default=None, help="speaker name substring")
    p.add_argument(
        "--mode",
        choices=("empathy", "beats", "plain"),
        default="empathy",
        help="empathy: face+gesture per reply (default); beats: per sentence; plain: no expression",
    )
    p.add_argument("--list-devices", action="store_true", help="list audio devices and exit")
    return p.parse_args()


def pick(cli_value, cfg, path, fallback):
    """CLI beats config, config beats the code default."""
    if cli_value is not None:
        return cli_value
    return cfg.get(path, fallback)


def respond(bot, convo, text, max_sentences, mode="empathy"):
    """Reply, in one of three ways.

    plain    -- streamed sentences, no expression. Fastest, and a statue.
    empathy  -- one face and movement for the whole reply (default).
    beats    -- a face and movement per sentence, so it can shift mid-reply.
    """
    bot.set_state("thinking")
    bot.express("thinking")
    said_anything = False

    try:
        if mode == "plain":
            print("Ohbot: ", end="", flush=True)
            for sentence in convo.stream_sentences(text, max_sentences=max_sentences):
                print(sentence, end=" ", flush=True)
                bot.speak(sentence)
                said_anything = True
            print()

        elif mode == "beats":
            for beat in convo.respond_with_beats(text, expression.EMOTIONS, max_sentences):
                print(f"Ohbot [{beat['emotion']}/{beat['gesture']}]: {beat['say']}")
                bot.speak(beat["say"], emotion=beat["emotion"], gesture=beat["gesture"])
                said_anything = True

        else:
            action = convo.respond_with_action(text, expression.EMOTIONS, expression.GESTURE_NAMES)
            print(f"Ohbot [{action['emotion']}/{action['gesture']}]: {action['say']}")
            bot.gaze(action.get("gaze_x", 5), action.get("gaze_y", 5))
            bot.speak(action["say"], emotion=action["emotion"], gesture=action["gesture"])
            said_anything = bool(action["say"])

    except llm.OllamaError as e:
        print(f"\n[llm error] {e}", file=sys.stderr)
        bot.speak("Sorry, my brain is not responding.", emotion="confused")

    if not said_anything:
        bot.speak("Sorry, I did not catch that.", emotion="confused")

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

    if args.list_devices:
        print(audio.describe())
        return 0

    try:
        cfg = config_mod.load(args.config)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1

    # Persona supplies a system prompt and a preferred voice, both of which an
    # explicit flag can still override.
    try:
        persona_name = args.persona or cfg.get("persona")
        persona = cfg.persona(persona_name)
    except KeyError as e:
        # KeyError's str() wraps the message in quotes; args[0] is the plain text.
        print(e.args[0], file=sys.stderr)
        return 1

    model = pick(args.model, cfg, "llm.model", llm.DEFAULT_MODEL)
    host = cfg.get("llm.host", llm.HOST)
    max_sentences = pick(args.max_sentences, cfg, "llm.max_sentences", llm.MAX_SENTENCES)

    # Fail fast with a useful message before touching the robot.
    try:
        llm.check_model(model, host)
    except llm.OllamaError as e:
        print(e, file=sys.stderr)
        return 1

    # -- audio devices
    try:
        mic_device = audio.resolve(
            pick(args.input_device, cfg, "audio.input_device", None), audio.INPUT
        )
        out_device = audio.resolve(
            pick(args.output_device, cfg, "audio.output_device", None), audio.OUTPUT
        )
    except audio.DeviceNotFound as e:
        print(e, file=sys.stderr)
        return 1

    audio.install_output(out_device)

    convo = llm.Conversation(
        model=model,
        system=persona.get("system_prompt", llm.SYSTEM_PROMPT),
        host=host,
        temperature=cfg.get("llm.temperature", 0.7),
        num_predict=cfg.get("llm.num_predict", 80),
    )

    # A demo that sounds worse beats a demo that doesn't run, so a missing or
    # broken Kokoro falls back to the built-in voice rather than exiting.
    engine_name = pick(args.tts, cfg, "tts.engine", "kokoro")

    # Voice precedence: --voice-name > the persona's own voice > tts.voice >
    # built-in default. The persona beats the global setting because choosing a
    # character is a more specific intent than setting a default voice.
    voice_name = args.voice_name or persona.get("voice") or cfg.get("tts.voice", tts.DEFAULT_VOICE)

    engine = "say"
    if engine_name == "kokoro":
        try:
            tts.install(
                tts.KokoroTTS(
                    voice=voice_name,
                    speed=pick(args.speed, cfg, "tts.speed", tts.DEFAULT_SPEED),
                )
            )
            engine = f"kokoro ({voice_name})"
        except Exception as e:
            # Deliberately broad: missing model files, a failed ONNX load and a
            # misplaced espeak-ng data dir all mean the same thing here.
            print(f"[tts] Kokoro unavailable, using macOS say: {e}", file=sys.stderr)

    if args.voice:
        from ohbot_kit import voice  # imported lazily: heavy deps, only needed with --voice

        listener = voice.Listener(
            device=mic_device,
            model_size=cfg.get("speech_to_text.model", voice.MODEL_SIZE),
            silence_seconds=cfg.get("speech_to_text.silence_seconds", voice.SILENCE_SECONDS),
            min_speech_seconds=cfg.get(
                "speech_to_text.min_speech_seconds", voice.MIN_SPEECH_SECONDS
            ),
            noise_multiplier=cfg.get("speech_to_text.noise_multiplier", voice.NOISE_MULTIPLIER),
        )
        source = lambda bot: listener.listen_loop(bot)  # noqa: E731
        # An empty tuple in typed mode, so the handler below is safe either way.
        mic_errors = (voice.MicrophoneBlocked,)
    else:
        source = lambda bot: typed_inputs()  # noqa: E731
        mic_errors = ()

    print(
        BANNER.format(
            model=model,
            engine=engine,
            persona=persona_name or "default",
            mode=args.mode,
            mic=audio.device_name(mic_device),
            out=audio.device_name(out_device),
        )
    )
    if cfg.sources:
        print("config: {}".format(", ".join(cfg.sources)))
    print("Loading model...", flush=True)
    convo.warm_up()

    idle = False if args.no_idle else cfg.get("robot.idle", True)
    with Ohbot(
        idle=idle,
        colours=cfg.get("robot.eye_colours"),
        blink_interval=cfg.get("robot.blink_interval", (2, 6)),
        drift_interval=cfg.get("robot.drift_interval", (4, 9)),
    ) as bot:
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
                    print(f"You: {text}")

                respond(bot, convo, text, max_sentences, args.mode)
        except KeyboardInterrupt:
            print()
        except mic_errors as e:
            print(f"\n[microphone] {e}", file=sys.stderr)
            bot.speak("I cannot hear anything. Check my microphone permission.")

        bot.speak("Goodbye!")

    print("Motors detached. Bye.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
