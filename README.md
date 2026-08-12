# Ohbot Hackathon Kit

[![CI](https://github.com/liottandrea/robot_hackathon/actions/workflows/ci.yml/badge.svg)](https://github.com/liottandrea/robot_hackathon/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

A desk robot that listens, thinks and reacts — with a face. Everything runs **locally**:
no API keys, no internet, nothing leaves your laptop.

```python
from ohbot_kit import Ohbot, setup

cfg, convo, robot_kwargs = setup()
with Ohbot(**robot_kwargs) as bot:
    bot.speak("I'm sorry to hear that.", emotion="sympathetic", gesture="slow_nod")
```

The robot speaks **and moves at the same time** — the gesture plays underneath the audio,
which is the difference between a robot and a speaker with a face.

## Quickstart

Full instructions, including Windows: **[docs/SETUP.md](docs/SETUP.md)**

```bash
uv venv --python 3.11 && source .venv/bin/activate
uv pip install -r requirements.txt
ollama serve &  &&  ollama pull phi4-mini

python tools/check_setup.py        # downloads models, warms up, checks everything
python examples/01_hello_robot.py  # it should move and talk
```

Run everything **from the repository root**.

## Then try this

```bash
python examples/08_empathy_chat.py
```

Type *"I had a really rough day, my cat died last night."* Watch the face, not the words.

```bash
python examples/08_empathy_chat.py --voice   # talk to it out loud
python examples/11_multi_beat.py             # expression changes mid-reply
python examples/02_expressions.py            # every pose and gesture, demonstrated
```

## Start building

```bash
cp template.py my_project.py
python my_project.py
```

| Where | What |
| --- | --- |
| **[docs/API.md](docs/API.md)** | Every call, pose, gesture and motor. Keep it open. |
| **[docs/CHALLENGES.md](docs/CHALLENGES.md)** | Project ideas, easy → ambitious, if you're still deciding |
| [docs/TEAMS.md](docs/TEAMS.md) | Put the robot in a Teams call: it listens, and speaks when named |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Every failure we hit, and its fix |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it works, and why some odd-looking things are load-bearing |

## Examples

Numbered in the order worth reading them.

| | |
| --- | --- |
| `01_hello_robot.py` | move, speak, look around — **start here** |
| `02_expressions.py` | the full catalogue of poses and gestures |
| `03_speech.py` | 54 voices, speed, and how lip sync works |
| `04_chat_basic.py` | the smallest possible talking robot |
| `05_personas.py` | one robot, different characters |
| `06_voice_chat.py` | talk to it with your voice |
| `07_sensors.py` | react to someone approaching |
| **`08_empathy_chat.py`** | **the flagship** — reacts with face and body, not just words |
| `09_vision.py` | webcam + a vision model: it describes what it sees |
| `11_multi_beat.py` | expression that changes *within* a single reply |
| `10_teams_call.py` | it sits in a Teams call and answers when named — [docs/TEAMS.md](docs/TEAMS.md) |

## What it can do

**Face and body** — 10 emotions, 12 gestures, coordinated looking (eyes lead, head
follows), backchannel nodding while *you* talk. All eight motors, including the head tilt
that isn't in the vendor's docs.

**Voice** — Kokoro-82M, 54 voices, with lip sync. Faster than the macOS built-in voice.

**Ears** — local Whisper. It won't transcribe its own speech.

**Brain** — any Ollama model. The LLM picks the emotion and gesture to go with its words.

Add a pose or gesture to `ohbot_kit/expression.py` and it immediately becomes a choice the
LLM can make — the schema is built from those tables.

## Is it working properly?

```bash
python tools/check_empathy.py --robot
```

Scores emotion choice against 12 labelled cases, performs them all on the robot, and
verifies gestures actually overlap speech. `--repeats 3` shows which cases are unstable
between runs — a single run is a sample, not a measurement.

## Layout

```text
ohbot_kit/     the library          examples/   01-10
tools/         diagnostics          docs/       guides
template.py    copy this to start   ohbot_chat.py  the full chat app
config.yaml    settings + personas
```

Machine-specific settings (audio devices) go in `config.local.yaml`, which is git-ignored.

## Contributing

```bash
pip install -r requirements.txt -r requirements-dev.txt
pre-commit install
pytest                       # ~2s, no robot needed
```

The test suite fakes the hardware, so it runs anywhere. See
[CONTRIBUTING.md](CONTRIBUTING.md), and read
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before changing anything that looks odd —
several strange-looking things are load-bearing.

Licensed under [Apache 2.0](LICENSE). Third-party components are listed in [NOTICE](NOTICE).
