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

## Chatbot

Hold a spoken conversation with the robot, powered by a local
[Ollama](https://ollama.com/) model with [Kokoro-82M](https://github.com/thewh1teagle/kokoro-onnx)
for the voice. Nothing leaves the machine.

### Before the demo

```bash
ollama serve                 # in another terminal, if not already running
ollama pull phi4-mini        # 2.5 GB

python setup_demo.py         # downloads models, warms everything up, checks hardware
```

Run this once before you present. It fetches the Kokoro (~336 MB) and Whisper (~150 MB) models,
warms up all three models so the first live answer isn't slow, and tells you plainly if the robot,
Ollama or the microphone isn't ready. `--smoke` also makes the robot speak, as a full end-to-end
check. It exits non-zero if anything critical is wrong.

### Running it

```bash
python ohbot_chat.py                      # type, robot speaks back
python ohbot_chat.py --voice              # speak, robot speaks back
python ohbot_chat.py --model qwen3.6:35b  # use a different LLM
python ohbot_chat.py --voice-name bf_emma # different Kokoro voice (54 available)
python ohbot_chat.py --tts say            # fall back to the macOS voice
python ohbot_chat.py --no-idle            # stop the blinking and drift
```

Commands at the prompt: `/reset` forgets the conversation, `/quit` exits.

### Configuration

Settings live in `config.yaml` — model, voice, speech timings, eye colours, idle behaviour and
personality presets. Precedence, lowest to highest:

```text
code defaults  <  config.yaml  <  config.local.yaml  <  command-line flags
```

`config.yaml` is committed and works on any machine (audio devices default to the system's).
`config.local.yaml` is **git-ignored** and holds whatever is specific to your hardware:

```yaml
audio:
  input_device: Plantronics     # case-insensitive substring of the device name
  output_device: Plantronics
```

`python ohbot_chat.py --list-devices` shows what's available. A name that matches nothing gives an
error listing the real devices, rather than silently using the wrong one.

Matching is **direction-aware**, which matters: a headset appears *twice* under one name, once with
input channels and once with output channels. One name covers both ends correctly.

#### Personas

`config.yaml` defines `friendly`, `pirate` and `teacher`, each pairing a system prompt with a voice:

```bash
python ohbot_chat.py --persona pirate
```

Voice precedence is `--voice-name` > the persona's voice > `tts.voice` > built-in default — choosing
a character is treated as more specific than setting a global default voice.

#### Headset vs speakers

Ohbot's own playback always uses the system default output, so `audio.py` replaces
`ohbot._playSpeech` to route audio to a chosen device (falling back to the default, with a warning,
if the device rejects the stream).

Which you want depends on the situation:

| Setup | Effect |
| --- | --- |
| Both ends on the headset | You hear Ohbot in the earpiece and speak into the boom mic. It cannot hear itself. Ideal for testing — but **the audience hears nothing**. |
| Output on MacBook Speakers | The room hears Ohbot. It will also hear itself, which is handled — listening is suspended while it speaks. **Use this for a live demo.** |

Eye colour tells you what it's doing: **blue** listening, **amber** thinking
(pulsing), **green** speaking.

| Module | Role |
| --- | --- |
| `setup_demo.py` | Pre-demo downloads, warmups and readiness checks |
| `config.py` / `config.yaml` | Settings, personas, and the local-override merge |
| `audio.py` | Device resolution and output routing |
| `llm.py` | Ollama streaming client, sentence splitter, TTS sanitiser |
| `tts.py` | Kokoro speech, swapped in behind `ohbot.say()` |
| `robot.py` | Speech, idle motion, eye-colour state, guaranteed `close()` |
| `voice.py` | Mic capture + local Whisper transcription (only with `--voice`) |
| `ohbot_chat.py` | The chat loop |

### The voice

Kokoro-82M replaces the macOS `say` voice and is **also faster**: 0.62 s to generate a 4.5 s
utterance versus 1.25 s for `say` (7.2× realtime on Apple Silicon). Model files live in `models/`
and are git-ignored.

Swapping the engine looks like it should break lip sync, since `ohbot.say()` does synthesis and
lip movement together. It doesn't — **on macOS the lip is driven by loudness, not phonemes.**
`say()` opens the generated WAV, sums sample bytes in chunks of `framerate/10`, normalises to 0–10
and feeds that envelope to the lip motor. Actual phoneme data is used only on Raspberry Pi, where
`synthesizer == "festival"`.

So `tts.py` only has to replace one function, `_generateSpeechFile(text)`, and write a WAV where
ohbot expects one. Viseme calculation, threading and playback are untouched. Two constraints come
from that same envelope code, and both are handled:

- It indexes `buffer[i] + buffer[i+1]*256`, so the WAV **must be 16-bit PCM** — Kokoro emits float32.
- It loops `range(0, length - chunk, chunk)`, so audio under ~0.2 s yields an empty list and
  `say()` then raises `IndexError` on `times[-1]`. Every clip gets 0.3 s of trailing silence, which
  is why a one-word reply doesn't crash.

If Kokoro fails for any reason, the chat falls back to `say` with a warning rather than exiting.

### Why it's built this way

Three things about the hardware drive the design, and are worth knowing before you change it:

**Replies are capped at 3 sentences, in code.** `ohbot.say()` synthesizes the *whole* string to a
WAV before any lip movement starts, so latency scales with length. A long reply means a long
freeze, then a monologue you can't interrupt. The system prompt asks for brevity, but small models
ignore it — so `llm.MAX_SENTENCES` enforces it regardless. Raise it with `--max-sentences` if you
want longer answers.

**Replies are streamed sentence by sentence.** A producer thread reads from Ollama while the main
thread speaks, so the robot starts talking after sentence one rather than after the whole response.

**Idle motion stops during speech — this is not optional.** The library's `_serwrite()` guards
concurrent writes only on Windows and Linux; on macOS there is *no* guard. `say()` meanwhile spawns
its own threads to drive the lip motor. Idle motion running during speech would interleave bytes on
an unguarded serial port and corrupt motor commands. `robot.py` gates every idle write behind an
event that `speak()` clears.

### Voice mode

Uses `faster-whisper` (`base.en`, ~150 MB, downloaded on first run) with silence-triggered capture.
Listening is suspended while the robot talks, so it doesn't transcribe its own voice.

macOS will need microphone permission: **System Settings → Privacy & Security → Microphone**, enable
your terminal app, then restart it. If the mic returns silence, the program says so and exits
instead of hanging. Test the mic alone with `python voice.py`.

A headset is worth using for demos — it stops the robot hearing itself even without the gating.

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
| --- | --- | --- |
| 0 | `HEADNOD` | Head up/down |
| 1 | `HEADTURN` | Head left/right |
| 2 | `EYETURN` | Eyes left/right |
| 3 | `LIDBLINK` | Eyelids |
| 5 | `BOTTOMLIP` | Lower lip |
| 6 | `EYETILT` | Eyes up/down |

Index 4 is unused. Address motors by constant or by number.

### Other API

| Call | Notes |
| --- | --- |
| `wait(seconds)` | int or float; use between consecutive commands to the same motor |
| `readSensor(pin)` | pin 0–6, returns float 0–10 |
| `playSound(name)` | omit the `.wav`; presets: fanfare, loop, ohbot, smash, spring |
| `getPhrase(set, variable)` | pulls from the speech database CSV |
| `init(portName)` | manual port override if auto-detect fails |
| `reset()` / `close()` | rest position + LEDs off / detach all motors |

## Project layout

| Path | Purpose |
| --- | --- |
| `check_port.py` | Serial diagnostic — probes ports without importing ohbot |
| `helloworldohbot.py` | Movement + speech demo |
| `requirements.txt` | Pinned dependency set |
| `ohbotData/` | Auto-created on first run; **git-ignored** |
| `models/` | Kokoro model files, fetched by `setup_demo.py`; **git-ignored** |

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
| --- | --- | --- |
| Install newest Python from python.org | Ohbot is verified for **3.6–3.11** only | Newer interpreters are untested; deps may lack wheels |
| `sudo pip3 install ohbot` | Homebrew Python is PEP 668 externally-managed | pip refuses; `sudo` would pollute system site-packages |
| USB Y-cable + 5V 1A adaptor | Current Ohbrain is USB-C | Obsolete for this hardware; USB-C alone powers it |
| Deps include `playsound`, `pyobjc` | ohbot 4.0.18 uses `playsound3` | Stale dependency list |

Hence the pinned 3.11 venv above.
