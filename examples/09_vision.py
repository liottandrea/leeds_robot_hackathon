"""Give the robot eyes: webcam plus a local vision model.

    ollama pull moondream          # ~1.7 GB, small and quick
    python examples/09_vision.py

    python examples/09_vision.py --model qwen3.6:35b   # smarter, much slower

OpenCV is already in requirements.txt; this is the only example that uses it.

Grabs one frame from the webcam, asks a vision model what it sees, and the
robot reacts to it out loud.

WHY A SMALL MODEL: the loop only feels alive if it answers in a couple of
seconds. Measured on the same frame, moondream took 1.1-1.2s and qwen3.6:35b
took 21s. qwen sees more detail, but 21s of a motionless robot reads as a
crash -- fine for a single party trick, poor for interaction.

The very first look is slower (~10s) while Ollama loads the vision model;
check_setup.py warms the chat model but not this one. Every look after that is
the figure above.

CAMERA PERMISSION: macOS may deny this silently rather than asking. If OpenCV
says "not authorized to capture video", grant camera access to the app you run
Python from -- VS Code, if that is where your terminal lives, not Terminal.app.
`python tools/check_setup.py` reports the camera and the vision model.

Before you rewrite PROMPT below, read the comment above it. Asking a 1.7 GB
model to act in character instead of describe makes it emit "!!!!!!".
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

# Keep this a plain captioning instruction. moondream is a 1.7 GB model and it
# collapses if you ask it to act: measured at temperature 0, 3/3 identical runs
# each time -- "as if you were a friendly robot looking at it" returned a string
# of "!!!!!!", "Mention people if there are any." returned an empty string, and
# any "in one short sentence" phrasing lost the first token of the reply
# ("urns of blue..."). Plain description returns a clean, accurate caption.
#
# The personality belongs to the chat model further down, which turns this
# caption into an in-character reaction. Asking the vision model to be a
# character as well is both redundant and what broke it.
PROMPT = "Describe this image, including any people in it."

# macOS hands back a few unexposed (black) frames right after the device opens.
WARMUP_FRAMES = 5

# Messages of history to keep -- two exchanges. See the trim in the loop below.
HISTORY = 4

cfg, convo, robot_kwargs = setup()

try:
    llm.check_model(args.model, cfg.get("llm.host", llm.HOST))
except llm.OllamaError as e:
    sys.exit(f"{e}\n\nInstall it with:  ollama pull {args.model}")


def look_and_describe(camera):
    """Grab a frame and ask the vision model about it.

    Returns None if the camera gave us nothing; raises llm.OllamaError if the
    model could not be reached, so the caller can treat both as a skipped turn.
    """
    ok, frame = camera.read()
    if not ok:
        return None
    # Downscale before encoding: full-resolution frames cost seconds of
    # inference for no gain in what the model notices.
    frame = cv2.resize(frame, (512, 384))
    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        return None

    try:
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
    except (requests.RequestException, ValueError) as e:
        raise llm.OllamaError(f"Vision request failed: {e}") from e


camera = cv2.VideoCapture(args.camera)
if not camera.isOpened():
    sys.exit(f"Could not open camera {args.camera}. Check macOS camera permission.")

# Let the sensor settle before the first look, or the robot opens by describing
# a black rectangle with total confidence.
for _ in range(WARMUP_FRAMES):
    camera.read()

print(f"Looking every {args.interval:.0f}s. Ctrl-C to stop.\n")

try:
    with Ohbot(**robot_kwargs) as bot:
        bot.speak("Let me have a look around.", emotion="curious", gesture="tilt")
        while True:
            bot.set_state("thinking")
            bot.express("thinking")
            t0 = time.time()

            # Every skipped turn still waits out the interval. A bare `continue`
            # here would spin at full speed against a camera or a model that has
            # stopped answering, which is exactly when you least want that.
            try:
                description = look_and_describe(camera)
            except llm.OllamaError as e:
                print(f"[vision] {e}", file=sys.stderr)
                time.sleep(args.interval)
                continue
            if description is None:
                print("[vision] no frame from the camera", file=sys.stderr)
                time.sleep(args.interval)
                continue
            if not description:
                # Distinct from the above on purpose: a small vision model does
                # sometimes answer with punctuation or emoji that sanitise()
                # strips to nothing. That is the model, not the camera.
                print("[vision] nothing describable in that frame", file=sys.stderr)
                time.sleep(args.interval)
                continue
            print(f"[{time.time() - t0:.1f}s] {description}")

            # Let the chat model react in character, with a face and a gesture,
            # rather than the robot flatly reading the caption aloud.
            try:
                action = convo.respond_with_action(
                    f"You just looked around and saw: {description}. React briefly.",
                    expression.EMOTIONS,
                    expression.GESTURE_NAMES,
                )
            except llm.OllamaError as e:
                print(f"[llm] {e}", file=sys.stderr)
                time.sleep(args.interval)
                continue

            # Unlike the chat examples this loop is unattended, and every reply
            # appends two messages to the history. Left alone it grows until
            # latency climbs and the context overflows. Two exchanges is enough
            # to stop the robot repeating itself at an unchanged scene.
            del convo.messages[:-HISTORY]

            bot.speak(action["say"], emotion=action["emotion"], gesture=action["gesture"])
            time.sleep(args.interval)
except KeyboardInterrupt:
    print()
finally:
    camera.release()
