"""Run this before the demo.

Downloads what's missing, warms up every model so the first live response isn't
slow, and checks each thing that has to be true for the demo to work -- so you
find out here rather than in front of an audience.

    python setup_demo.py            # check, download, warm up
    python setup_demo.py --smoke    # also make the robot say one line

Exits non-zero if anything critical failed.
"""

import _bootstrap  # noqa: F401

import argparse
import os
import platform
import sys
import time

CRITICAL = "critical"
WARNING = "warning"

results = []


def report(name, ok, detail="", level=CRITICAL):
    """Record and print one check result."""
    if ok:
        mark, label = "PASS", ""
    elif level == WARNING:
        mark, label = "WARN", ""
    else:
        mark, label = "FAIL", ""
    print("  [{}] {}{}".format(mark, name, label))
    if detail:
        for line in str(detail).strip().splitlines():
            print("         {}".format(line))
    results.append((name, ok, level))
    return ok


def section(title):
    print("\n{}".format(title))


# -- checks ---------------------------------------------------------------


def check_python():
    v = sys.version_info
    ok = (3, 10) <= (v.major, v.minor) < (3, 14)
    in_venv = sys.prefix != sys.base_prefix
    detail = "" if ok else "kokoro-onnx needs >=3.10,<3.14. Recreate: uv venv --python 3.11"
    report("Python {}.{}.{}".format(v.major, v.minor, v.micro), ok, detail)
    report(
        "Running inside the project venv",
        in_venv,
        "" if in_venv else "Run: source .venv/bin/activate",
    )
    return ok


def check_cwd():
    """ohbot resolves ohbotData/ relative to cwd, so this genuinely matters."""
    ok = os.path.exists("config.yaml") and os.path.isdir("ohbot_kit")
    return report(
        "Running from the project root",
        ok,
        "" if ok else "cd into the repo -- ohbotData/ is resolved relative to cwd",
    )


def check_robot():
    try:
        import serial
        import serial.tools.list_ports
    except ImportError as e:
        return report("Ohbot serial port", False, e)

    found = None
    for p in serial.tools.list_ports.comports():
        # Only macOS names its ports with "usb"; Windows uses COM3, so
        # applying this filter everywhere would skip every port and report
        # "no Ohbot" on a perfectly working Windows machine.
        if platform.system() == "Darwin" and "usb" not in p.device:
            continue
        try:
            with serial.Serial(p.device, 19200, timeout=0.5, write_timeout=0.5) as ser:
                ser.flushInput()
                ser.write(("v" + "\n").encode("latin-1"))
                reply = ser.readline()
            if b"v1" in reply or b"v2" in reply:
                found = "{} ({})".format(p.device, reply.decode("latin-1").strip())
                break
        except Exception:
            continue

    return report(
        "Ohbot responding on serial",
        found is not None,
        found or "Not found. Replug the USB-C cable (direct port, not a USB-A adapter).",
    )


def check_ollama(model, host="http://localhost:11434"):
    from ohbot_kit import llm

    try:
        models = llm.list_models(host)
    except llm.OllamaError as e:
        return report("Ollama running", False, e)

    report("Ollama running", True, "{} model(s) installed".format(len(models)))

    try:
        llm.check_model(model, host)
        return report("Chat model '{}' installed".format(model), True)
    except llm.OllamaError as e:
        return report("Chat model '{}' installed".format(model), False, e)


def download(url, dest):
    """Stream a file to dest with a progress line."""
    import requests

    tmp = dest + ".part"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(tmp, "wb") as f:
            for block in r.iter_content(chunk_size=1 << 20):
                f.write(block)
                done += len(block)
                if total:
                    print(
                        "\r         {:.0f}% of {:.0f} MB".format(
                            done * 100 / total, total / 1e6
                        ),
                        end="",
                        flush=True,
                    )
        print()
    os.replace(tmp, dest)  # atomic, so an interrupted download can't look complete


def check_kokoro():
    from ohbot_kit import tts

    for path in (tts.MODEL_FILE, tts.VOICES_FILE):
        if os.path.exists(path):
            continue
        name = os.path.basename(path)
        print("  [....] Downloading {} ...".format(name))
        try:
            download("{}/{}".format(tts.DOWNLOAD_BASE, name), path)
        except Exception as e:
            return report("Kokoro model files", False, e)

    return report(
        "Kokoro model files present",
        tts.available(),
        "\n".join(
            "{}: {:.0f} MB".format(os.path.basename(p), os.path.getsize(p) / 1e6)
            for p in (tts.MODEL_FILE, tts.VOICES_FILE)
            if os.path.exists(p)
        ),
    )


def check_devices(cfg):
    """Resolve configured audio devices and report what they landed on."""
    from ohbot_kit import audio

    resolved = {}
    for key, kind in (("input_device", audio.INPUT), ("output_device", audio.OUTPUT)):
        name = cfg.get("audio.{}".format(key))
        try:
            index = audio.resolve(name, kind)
        except audio.DeviceNotFound as e:
            report("Audio {}".format(kind), False, e)
            resolved[kind] = None
            continue
        resolved[kind] = index
        report(
            "Audio {}".format(kind),
            True,
            "{}{}".format(
                audio.device_name(index),
                "" if name else "  (system default -- set audio.{} to pin it)".format(key),
            ),
        )
    return resolved


def check_microphone(device=None):
    """A warning, not a failure -- typed mode is a perfectly good demo.

    Checks the *configured* device, not the system default: otherwise this can
    pass while the demo fails on a different mic.
    """
    try:
        from ohbot_kit import voice
    except ImportError as e:
        return report("Microphone", False, e, level=WARNING)

    try:
        listener = voice.Listener.__new__(voice.Listener)  # skip the model load
        listener.device = device
        listener.noise_multiplier = voice.NOISE_MULTIPLIER
        listener.threshold = voice.FLOOR
        listener.calibrate()
        return report("Microphone delivering audio", True, level=WARNING)
    except voice.MicrophoneBlocked as e:
        return report("Microphone delivering audio", False, e, level=WARNING)
    except Exception as e:
        return report("Microphone delivering audio", False, e, level=WARNING)


# -- warmups --------------------------------------------------------------


def warm_ollama(model):
    from ohbot_kit import llm

    t0 = time.time()
    llm.Conversation(model=model).warm_up()
    report("Ollama model loaded", True, "{:.1f}s".format(time.time() - t0))


def warm_kokoro(voice_name):
    from ohbot_kit import tts

    try:
        t0 = time.time()
        engine = tts.KokoroTTS(voice=voice_name)
        engine.synth("Warming up.")
        return report(
            "Kokoro loaded (voice: {})".format(voice_name),
            True,
            "{:.1f}s, {} voices available".format(time.time() - t0, len(engine.voices())),
        )
    except Exception as e:
        return report("Kokoro loaded", False, e)


def warm_whisper():
    try:
        import numpy as np
        from ohbot_kit import voice

        t0 = time.time()
        listener = voice.Listener()
        # Transcribe a second of silence purely to force the model to load.
        listener.transcribe(np.zeros(16000, dtype=np.float32))
        return report(
            "Whisper loaded ({})".format(voice.MODEL_SIZE),
            True,
            "{:.1f}s".format(time.time() - t0),
        )
    except Exception as e:
        return report("Whisper loaded", False, e, level=WARNING)


def smoke_test(voice_name, output_device=None):
    """Opt-in: prove the whole chain by making the robot actually speak."""
    from ohbot_kit import audio
    from ohbot_kit import tts
    from ohbot_kit.robot import Ohbot

    try:
        audio.install_output(output_device)
        tts.install(tts.KokoroTTS(voice=voice_name))
    except Exception as e:
        return report("Smoke test", False, e)

    try:
        with Ohbot(idle=False) as bot:
            bot.speak("Setup complete. I am ready for the demo.")
        return report("Smoke test: robot spoke and moved", True)
    except Exception as e:
        return report("Smoke test", False, e)


# -- main -----------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(description="Pre-demo setup and checks.")
    p.add_argument("--config", default="config.yaml", help="path to config.yaml")
    p.add_argument("--model", default=None, help="Ollama chat model")
    p.add_argument("--voice-name", default=None, help="Kokoro voice")
    p.add_argument("--smoke", action="store_true", help="also make the robot speak")
    p.add_argument("--skip-mic", action="store_true", help="skip the microphone check")
    args = p.parse_args()

    print("Ohbot demo setup\n" + "=" * 40)

    from ohbot_kit import config as config_mod

    cfg = config_mod.load(args.config)
    model = args.model or cfg.get("llm.model", "phi4-mini")
    voice_name = args.voice_name or cfg.get("tts.voice", "af_heart")

    section("Environment")
    check_python()
    check_cwd()
    report(
        "Config loaded",
        True,
        ", ".join(cfg.sources) if cfg.sources else "none found -- using code defaults",
    )

    section("Hardware and services")
    check_robot()
    check_ollama(model, cfg.get("llm.host", "http://localhost:11434"))

    section("Audio devices")
    resolved = check_devices(cfg)

    section("Models")
    check_kokoro()

    section("Warming up (so the first live response isn't slow)")
    warm_ollama(model)
    warm_kokoro(voice_name)
    warm_whisper()

    if not args.skip_mic:
        section("Microphone (only needed for --voice)")
        check_microphone(resolved.get("input"))

    if args.smoke:
        section("Smoke test")
        smoke_test(voice_name, resolved.get("output"))

    # -- summary
    failed = [n for n, ok, lvl in results if not ok and lvl == CRITICAL]
    warned = [n for n, ok, lvl in results if not ok and lvl == WARNING]

    print("\n" + "=" * 40)
    if failed:
        print("NOT READY -- {} critical problem(s):".format(len(failed)))
        for n in failed:
            print("  - {}".format(n))
        return 1

    if warned:
        print("READY (with {} warning(s)):".format(len(warned)))
        for n in warned:
            print("  - {}".format(n))
        print("\nTyped mode will work. Voice mode (--voice) will not.")
    else:
        print("READY. Everything checks out.")

    print("\nNext:  python examples/01_hello_robot.py"
          "     then  python examples/08_empathy_chat.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
