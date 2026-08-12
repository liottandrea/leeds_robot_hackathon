# Robot Hackathon — Ohbot in Python

Controlling an [Ohbot](https://www.ohbot.co.uk/) robot from Python on macOS.

Verified working against **Ohbrain v2.10.12** (a Raspberry Pi Pico board) over USB-C.

## Setup

The official [Ohbot getting-started guide](https://learn.ohbot.co.uk/ohbotgetstarted.html)
tells you to run `sudo pip3 install ohbot`. **Don't** — see [Why not the official steps?](#why-not-the-official-steps)
below. Use this instead:

```bash
# 1. Install uv if you don't have it: https://docs.astral.sh/uv/
# 2. Create the environment (downloads a managed CPython 3.11)
uv venv --python 3.11
source .venv/bin/activate

# 3. Install dependencies
uv pip install -r requirements.txt
```

Then plug the Ohbot into a **USB-C port directly** — not via a USB-A adapter, which may not
supply enough current to keep the servos running reliably.

## Check it works

```bash
python check_port.py       # is the board answering on serial?
python helloworldohbot.py  # make it speak and move
```

`check_port.py` should report a reply like `SVer:v2.10.12` and print `OHBOT FOUND`.
`helloworldohbot.py` should make the robot say "Hello World" with its lip moving,
fade the eyes, and sweep the head and eyelids.

> Run scripts **from the project root**. The library resolves `ohbotData/` relative to the
> working directory, so running from a subfolder silently creates a second, uncalibrated copy.

## Writing your own

```python
from ohbot import ohbot   # auto-connects on import — plug in BEFORE this line

try:
    ohbot.reset()
    ohbot.move(ohbot.HEADTURN, 8, speed=3)   # motor, position 0-10, speed 0-10
    ohbot.say("Hello")                        # untilDone=False to run on while speaking
    ohbot.setEyeColour(0, 0, 10)              # r, g, b — each 0-10
finally:
    ohbot.close()   # always — detaches motors so they stop drawing current
```

Wrap experiments in `try/finally`. If a script crashes before `close()`, the motors stay
attached, buzzing and drawing current until you replug.

### Motors

| Index | Constant | Moves |
|---|---|---|
| 0 | `HEADNOD` | Head up/down |
| 1 | `HEADTURN` | Head left/right |
| 2 | `EYETURN` | Eyes left/right |
| 3 | `LIDBLINK` | Eyelids |
| 5 | `BOTTOMLIP` | Lower lip |
| 6 | `EYETILT` | Eyes up/down |

Index 4 is unused. Address motors by constant or by number.

### Other API

| Call | Notes |
|---|---|
| `wait(seconds)` | int or float; use between consecutive commands to the same motor |
| `readSensor(pin)` | pin 0–6, returns float 0–10 |
| `playSound(name)` | omit the `.wav`; presets: fanfare, loop, ohbot, smash, spring |
| `getPhrase(set, variable)` | pulls from the speech database CSV |
| `init(portName)` | manual port override if auto-detect fails |
| `reset()` / `close()` | rest position + LEDs off / detach all motors |

## Project layout

| Path | Purpose |
|---|---|
| `check_port.py` | Serial diagnostic — probes ports without importing ohbot |
| `helloworldohbot.py` | Movement + speech demo |
| `requirements.txt` | Pinned dependency set |
| `ohbotData/` | Auto-created on first run; **git-ignored** |

`ohbotData/` holds `MotorDefinitionsv21.omd` (motor min/max/range — tune here if a servo
strains at its range ends), `OhbotSpeech.csv`, and `Sounds/`. Deleting it restores library
defaults on the next run.

## Troubleshooting

**`Ohbot not found` on import.** Run `python check_port.py` first to separate "the robot
isn't talking" from "the library isn't finding it". If the probe succeeds but the import
fails, override the port explicitly:

```python
ohbot.init("/dev/cu.usbmodem2101")
```

**How detection works** — worth knowing, since it's the usual failure point. The library
doesn't match on USB vendor/product ID. It enumerates every serial port, opens each at
19200 baud, writes `v\n`, and accepts the port if the reply contains `v1` or `v2`. On macOS
it only probes ports whose device name contains `usb`.

**Motors move but no speech.** macOS TTS shells out to `say`, writing `ohbotspeech.wav`.
Check `say "test"` works standalone in Terminal and that your output device is unmuted.

**Motors buzzing after a crash.** A script that died before `ohbot.close()` left them
attached. Run `python -c "from ohbot import ohbot; ohbot.close()"` or replug.

## Why not the official steps?

The vendor's macOS instructions predate the current hardware and Python packaging rules:

| Guide says | Reality | Why it breaks |
|---|---|---|
| Install newest Python from python.org | Ohbot is verified for **3.6–3.11** only | Newer interpreters are untested; deps may lack wheels |
| `sudo pip3 install ohbot` | Homebrew Python is PEP 668 externally-managed | pip refuses; `sudo` would pollute system site-packages |
| USB Y-cable + 5V 1A adaptor | Current Ohbrain is USB-C | Obsolete for this hardware; USB-C alone powers it |
| Deps include `playsound`, `pyobjc` | ohbot 4.0.18 uses `playsound3` | Stale dependency list |

Hence the pinned 3.11 venv above.
