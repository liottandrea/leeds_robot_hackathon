"""Give the robot eyes: webcam plus a local vision model.

    ollama pull moondream          # ~1.7 GB, small and quick
    pip install opencv-python
    python examples/09_vision.py

    python examples/09_vision.py --model qwen3.6:35b   # smarter, much slower

Grabs one frame from the webcam, asks a vision model what it sees, and the
robot reacts to it out loud.

WHY A SMALL MODEL: the loop only feels alive if it answers in a couple of
seconds. moondream is ~1.7 GB. qwen3.6:35b also has vision but is 23 GB, so
expect long pauses -- fine for a single party trick, poor for interaction.

macOS will ask for camera permission the first time.
"""

import argparse
import base64
import sys
import time

import _bootstrap  # noqa: F401
import requests

from ohbot_kit import Ohbot, expression, llm, setup

p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
p.add_argument("--model", default="moondream", help="an Ollama model with vision")
p.add_argument("--interval", type=float, default=8.0, help="seconds between looks")
p.add_argument("--camera", type=int, default=0)
args = p.parse_args()

try:
    import cv2
except ImportError:
    sys.exit("Needs OpenCV:  pip install opencv-python")

PROMPT = (
    "Describe what you see in one short sentence, as if you were a friendly "
    "robot looking at it. Mention people if there are any."
)

cfg, convo, robot_kwargs = setup()

try:
    llm.check_model(args.model, cfg.get("llm.host", llm.HOST))
except llm.OllamaError as e:
    sys.exit(f"{e}\n\nInstall it with:  ollama pull {args.model}")


def look_and_describe(camera):
    """Grab a frame and ask the vision model about it."""
    ok, frame = camera.read()
    if not ok:
        return None
    # Downscale before encoding: full-resolution frames cost seconds of
    # inference for no gain in what the model notices.
    frame = cv2.resize(frame, (512, 384))
    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        return None

    r = requests.post(
        "{}/api/generate".format(cfg.get("llm.host", llm.HOST)),
        json={
            "model": args.model,
            "prompt": PROMPT,
            "images": [base64.b64encode(buf.tobytes()).decode()],
            "stream": False,
        },
        timeout=180,
    )
    r.raise_for_status()
    return llm.sanitise(r.json().get("response", ""))


camera = cv2.VideoCapture(args.camera)
if not camera.isOpened():
    sys.exit(f"Could not open camera {args.camera}. Check macOS camera permission.")

print(f"Looking every {args.interval:.0f}s. Ctrl-C to stop.\n")

try:
    with Ohbot(**robot_kwargs) as bot:
        bot.speak("Let me have a look around.", emotion="curious", gesture="tilt")
        while True:
            bot.set_state("thinking")
            bot.express("thinking")
            t0 = time.time()
            description = look_and_describe(camera)
            if not description:
                continue
            print(f"[{time.time() - t0:.1f}s] {description}")

            # Let the chat model react in character, with a face and a gesture,
            # rather than the robot flatly reading the caption aloud.
            action = convo.respond_with_action(
                f"You just looked around and saw: {description}. React briefly.",
                expression.EMOTIONS,
                expression.GESTURE_NAMES,
            )
            bot.speak(action["say"], emotion=action["emotion"], gesture=action["gesture"])
            time.sleep(args.interval)
except KeyboardInterrupt:
    print()
finally:
    camera.release()
