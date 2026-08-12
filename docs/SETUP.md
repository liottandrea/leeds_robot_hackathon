# Setup

Target: from `git clone` to a talking robot in about 15 minutes, most of it downloads.

**Do this before the event.** The models are about 3 GB, and conference wifi shared
between ten teams is the most reliable way to lose a morning. If organisers hand out a USB
stick with `models/`, copy that folder into the repository and skip the Kokoro download.

---

## macOS

Verified on macOS 15 (Apple Silicon), Python 3.11.

**1. Python 3.11.** Ohbot is verified for 3.6–3.11 and `kokoro-onnx` requires <3.14, so
don't use the system's newest Python. [uv](https://docs.astral.sh/uv/) fetches the right
one for you:

```bash
brew install uv          # if you don't have it
cd robot_hackathon
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt
```

> The official Ohbot guide says `sudo pip3 install ohbot`. **Don't.** Homebrew Python is
> PEP 668 externally-managed and will refuse, and `sudo` would pollute system packages.

**2. Ollama:**

```bash
brew install ollama
ollama serve &           # leave running
ollama pull phi4-mini    # 2.5 GB
```

**3. Plug the robot in** — USB-C, directly into a port. Not through a USB-A adapter: the
vendor warns those may not supply enough current, and a robot browning out mid-demo looks
exactly like a software bug.

**4. Run the check** — it downloads the remaining models and warms everything up:

```bash
python tools/check_setup.py
```

**5. Grant microphone access** (only needed for voice input): System Settings → Privacy &
Security → Microphone → enable your terminal, then **restart the terminal**.

---

## Windows

The library uses SAPI for its fallback voice; Kokoro, Whisper and Ollama all work.

> **Not yet verified end to end.** Everything is written to be cross-platform and the
> known Windows-specific bug (serial ports are `COM3`, not `/dev/cu.usbmodem…`) is fixed,
> but nobody has run the full kit on Windows. If you're the first, please report back.

**1. Python 3.11** from [python.org](https://www.python.org/downloads/) — tick *Add Python
to PATH*. Then:

```powershell
cd robot_hackathon
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**2. Ollama** from [ollama.com/download](https://ollama.com/download), then:

```powershell
ollama pull phi4-mini
```

**3. Plug the robot in**, then:

```powershell
python tools\check_setup.py
```

If it can't find the robot, `python tools\check_port.py` lists every COM port and shows
what replied.

---

## Check it worked

```bash
python examples/01_hello_robot.py
```

The robot should look around, speak, and move while speaking. Then:

```bash
python examples/08_empathy_chat.py
```

Type *"I had a really rough day"* and watch the face, not just the words.

**Always run from the repository root.** The library resolves `ohbotData/` relative to the
working directory, so running from a subfolder silently creates a second, uncalibrated copy.

---

## Your own machine settings

`config.yaml` is shared and committed. For anything specific to your hardware — audio
devices above all — create `config.local.yaml`, which is git-ignored and overrides it:

```yaml
audio:
  input_device: Plantronics       # substring of the device name
  output_device: MacBook Pro Speakers
```

See the devices with `python ohbot_chat.py --list-devices`.

For a demo, put **output on the laptop speakers** or the audience hears nothing. A headset
is better while developing — and essential in a room with several robots, or yours will
hear the others.

---

## If something's wrong

`python tools/check_setup.py` names the fix for most problems.
[TROUBLESHOOTING.md](TROUBLESHOOTING.md) covers every failure we hit while building this.
