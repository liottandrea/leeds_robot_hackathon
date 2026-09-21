"""Talk to an Ohbot robot powered by a local Ollama model.

    python ohbot_chat.py                      # type to chat, with expression
                                               # (defaults to the "joker" persona)
    python ohbot_chat.py --mode beats         # expression changes mid-reply
    python ohbot_chat.py --mode plain         # no expression, just speech
    python ohbot_chat.py --voice              # speak instead of typing
    python ohbot_chat.py --persona pirate     # different personality and voice
    python ohbot_chat.py --camera             # let it see you; type /look for a photo
    python ohbot_chat.py --voice --camera     # both: speak, and still say/send /look
    python ohbot_chat.py --list-devices       # show audio devices, then exit

Settings live in config.yaml, overridden by config.local.yaml (git-ignored,
for machine-specific things like audio devices), overridden by these flags.

Run from the project root so the ohbotData/ calibration folder is shared.
Requires Ollama running locally (`ollama serve`) and the Ohbot plugged in.
--camera additionally needs a local vision model (`ollama pull moondream`),
even when --model points at Bedrock -- the camera never talks to Bedrock.
With --voice, the mic can't type "/look", so a /look line sent on stdin
(e.g. the Streamlit "Take a picture" button) still works from a background
thread; typing it directly at a terminal only works without --voice.
"""

import argparse
import contextlib
import sys
import threading

from ohbot_kit import audio, expression, kids_content, llm, tts, vision
from ohbot_kit import config as config_mod
from ohbot_kit.robot import Ohbot

BANNER = """Ohbot chat -- model: {model}, voice: {engine}, persona: {persona}, mode: {mode}
Audio in: {mic} | out: {out}
Type and press enter. Commands: {commands}
"""

INTRO_PROMPT = "Introduce yourself briefly, in character, to whoever just started this chat."
LOOK_PROMPT = (
    "You just looked at the person you are talking to through your camera and "
    "saw: {description}. React briefly, in character -- make a joke or tease "
    "them about what you saw, don't just describe it back."
)


def parse_args():
    p = argparse.ArgumentParser(description="Chat with an Ohbot robot.")
    # Config-backed options default to None so "not given" is distinguishable
    # from "given the same value as the default".
    p.add_argument("--config", default=config_mod.DEFAULT_PATH, help="path to config.yaml")
    # Funnier than config.yaml's global "friendly" default -- this is the app
    # people run to see the robot be entertaining. --persona still overrides it.
    p.add_argument("--persona", default="joker", help="persona from config.yaml")
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
        "--camera",
        nargs="?",
        type=int,
        const=0,
        default=None,
        metavar="INDEX",
        help="let it see you through webcam INDEX (default 0); type /look for a photo",
    )
    p.add_argument(
        "--vision-model", default=None, help="Ollama model with vision (default moondream)"
    )
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
                bot.gaze(beat.get("gaze_x", 5), beat.get("gaze_y", 5))
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


def look(bot, convo, eye, max_sentences, mode="empathy"):
    """Grab a frame from the camera and let the robot react to what it sees.

    eye.describe() returning None (no frame) or "" (nothing describable, e.g. a
    covered lens), and the camera/model raising, all count as a skipped look --
    spoken as a soft miss rather than a crash.
    """
    bot.set_state("thinking")
    bot.express("curious")
    try:
        description = eye.describe()
    except (vision.CameraError, llm.OllamaError) as e:
        print(f"[camera] {e}", file=sys.stderr)
        description = None

    if not description:
        bot.speak("I could not see anything just then.", emotion="confused")
        bot.set_state("listening")
        return

    print(f"[camera] {description}")
    before = len(convo.messages)
    respond(bot, convo, LOOK_PROMPT.format(description=description), max_sentences, mode)
    # The instruction ("React briefly... make a joke...") only needs to steer
    # *this* reply. Left verbatim in history it reads, to a small model, like a
    # standing directive to keep joking about the photo -- a later "do you like
    # it?" got the same joke replayed instead of an answer. A short, plain
    # stand-in keeps the photo as context without anchoring every reply after
    # it back onto react-and-joke.
    if len(convo.messages) == before + 2:
        convo.messages[before]["content"] = f"[shows you a photo: {description}]"


def watch_stdin_for_look(bot, convo, eye, max_sentences, mode, lock):
    """Let "Take a picture" work over stdin even while --voice owns the mic.

    Only started when --voice and --camera are both on: typed mode already
    reads stdin directly in the main loop, so a second reader there would
    steal its lines, and without --camera there is nothing for a stray line
    to trigger. `lock` is the same one the main loop holds during a turn, so
    a photo request waits its turn rather than talking over an in-progress
    reply.
    """
    for line in sys.stdin:
        if line.strip() in ("/look", "/photo"):
            with lock:
                look(bot, convo, eye, max_sentences, mode)


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

    provider = "ollama"
    if model == llm.BEDROCK_MODEL_ALIAS:
        provider = "bedrock"
        model = cfg.get("kids_content.model", kids_content.DEFAULT_MODEL)
    else:
        # Fail fast with a useful message before touching the robot.
        try:
            llm.check_model(model, host)
        except llm.OllamaError as e:
            print(e, file=sys.stderr)
            return 1

    # The camera always talks to a local Ollama vision model, even when the
    # chat model itself is Bedrock -- so fail fast here too, before the robot.
    eye = None
    vision_model = None
    if args.camera is not None:
        vision_model = args.vision_model or vision.DEFAULT_MODEL
        try:
            llm.check_model(vision_model, host)
            eye = vision.Camera(args.camera, vision_model, host).open()
        except (llm.OllamaError, vision.CameraError) as e:
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
        provider=provider,
        aws_profile=cfg.get("kids_content.aws_profile", "genai-agent-user"),
        aws_region=cfg.get("kids_content.aws_region"),
    )

    # A demo that sounds worse beats a demo that doesn't run, so a missing or
    # broken Kokoro falls back to the built-in voice rather than exiting.
    engine_name = pick(args.tts, cfg, "tts.engine", "kokoro")

    # Voice precedence: --voice-name > the persona's own voice > tts.voice >
    # built-in default. The persona beats the global setting because choosing a
    # character is a more specific intent than setting a default voice.
    voice_name = args.voice_name or persona.get("voice") or cfg.get("tts.voice", tts.DEFAULT_VOICE)
    # Same precedence as voice: a persona like chipmunk or bear needs its own
    # speed to sound right, not just a different voice.
    speed = args.speed
    if speed is None:
        speed = persona.get("speed")
    if speed is None:
        speed = cfg.get("tts.speed", tts.DEFAULT_SPEED)

    engine = "say"
    if engine_name == "kokoro":
        try:
            tts.install(
                tts.KokoroTTS(
                    voice=voice_name,
                    speed=speed,
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

    commands = "/reset (forget context), /quit"
    if eye is not None:
        commands = "/reset (forget context), /look (take a photo), /quit"

    print(
        BANNER.format(
            model=model,
            engine=engine,
            persona=persona_name or "default",
            mode=args.mode,
            mic=audio.device_name(mic_device),
            out=audio.device_name(out_device),
            commands=commands,
        )
    )
    if cfg.sources:
        print("config: {}".format(", ".join(cfg.sources)))
    print("Loading model...", flush=True)
    convo.warm_up()
    if eye is not None:
        # The first look costs ~10s while Ollama loads the vision model --
        # pay that now, under "Loading model...", not during the first /look.
        with contextlib.suppress(Exception):
            eye.describe()

    idle = False if args.no_idle else cfg.get("robot.idle", True)
    with Ohbot(
        idle=idle,
        colours=cfg.get("robot.eye_colours"),
        blink_interval=cfg.get("robot.blink_interval", (2, 6)),
        drift_interval=cfg.get("robot.drift_interval", (4, 9)),
    ) as bot:
        respond(bot, convo, INTRO_PROMPT, max_sentences, args.mode)

        # Guards every turn (typed/spoken reply or /look) so a photo request
        # arriving on stdin mid-reply waits its turn instead of talking over it.
        turn_lock = threading.Lock()
        if args.voice and eye is not None:
            threading.Thread(
                target=watch_stdin_for_look,
                args=(bot, convo, eye, max_sentences, args.mode, turn_lock),
                daemon=True,
            ).start()

        try:
            for text in source(bot):
                if not text:
                    continue
                if text in ("/quit", "/exit"):
                    break
                with turn_lock:
                    if text == "/reset":
                        convo.reset()
                        print("[context cleared]")
                        continue
                    if text in ("/look", "/photo"):
                        if eye is None:
                            print(
                                "[camera] not enabled. Restart with: python ohbot_chat.py --camera"
                            )
                            continue
                        look(bot, convo, eye, max_sentences, args.mode)
                        continue
                    if args.voice:
                        print(f"You: {text}")

                    respond(bot, convo, text, max_sentences, args.mode)
        except KeyboardInterrupt:
            print()
        except mic_errors as e:
            print(f"\n[microphone] {e}", file=sys.stderr)
            bot.speak("I cannot hear anything. Check my microphone permission.")
        finally:
            if eye is not None:
                eye.close()

        bot.speak("Goodbye!")

    print("Motors detached. Bye.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
