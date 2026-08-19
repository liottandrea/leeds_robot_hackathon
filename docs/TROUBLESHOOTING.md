# Troubleshooting

Every failure below actually happened while building this kit. Start with:

```bash
python tools/check_setup.py
```

It checks the robot, Ollama, the models, the audio devices, the microphone and the camera,
and names the fix for whatever is broken.

---

## "Ohbot not found" — but it's plugged in

**Usually another program is holding the serial port.** Only one process can own it.
A chat session left running in another terminal will make every other script report
no robot.

```bash
lsof /dev/cu.usbmodem*        # macOS: shows which PID has it
```

Quit that process and try again. Otherwise:

- Replug the USB-C cable, into a **direct port** — the vendor warns USB-A adapters may
  not supply enough current, and a browning-out robot looks exactly like a software bug.
- `python tools/check_port.py` probes every port and prints what replied. A working
  robot answers with something like `SVer:v2.10.12`.

**On Windows**, ports are named `COM3`, not `/dev/cu.usbmodem…`. Both diagnostics handle
this; if you write your own port code, don't filter on the name containing "usb" — that
filter only applies on macOS.

## The robot doesn't hear me

**First check you passed `--voice`.** Without it the program is in typed mode, sitting at
the `You:` prompt waiting for the keyboard. It isn't ignoring you — it never opened the
microphone. This is the single most common cause.

**Then check macOS granted microphone access:** System Settings → Privacy & Security →
Microphone → enable your terminal app, then **restart the terminal**. If the mic returns
digital silence the program says so and exits rather than waiting forever.

Test the microphone on its own:

```bash
python -c "from ohbot_kit import voice; l=voice.Listener(); l.calibrate(); print(l.transcribe(l.record_utterance()))"
```

**Levels too quiet?** If speech barely crosses the threshold, raise the input volume in
System Settings → Sound → Input, or lower `speech_to_text.noise_multiplier` in
`config.yaml`.

## It hears itself and replies to itself

Happens when output goes to laptop speakers. Listening is suspended while the robot
speaks, so its *own* voice is handled — but in a room with several robots, yours will
hear the others. **Use a headset.** That is the only real fix in a shared room.

## No sound at all

- Check which device audio is going to: `python ohbot_chat.py --list-devices`.
- A headset appears **twice** under one name — once as an input, once as an output.
  That's expected; matching is direction-aware.
- If output is set to your headset, the audience hears nothing. For a demo set
  `output_device` to the laptop speakers in `config.local.yaml`.

## The camera won't open (`09_vision.py`)

```text
OpenCV: not authorized to capture video (status 0), requesting...
OpenCV: camera failed to properly initialize!
Could not open camera 0. Check macOS camera permission.
```

**This is a permission, not the camera.** Grant it in System Settings → Privacy &
Security → **Camera**, then restart the app. `python tools/check_setup.py` distinguishes
this from a missing vision model.

**Grant it to the app that hosts your terminal**, which is not always Terminal.app. Run
Python from VS Code's integrated terminal and the permission belongs to **VS Code** —
macOS attributes it to the parent application. This cost us real time: the permission
looked granted because Terminal.app had it, while the process asking was VS Code.

Also worth checking: nothing else is holding the camera. Zoom, Teams and Photo Booth keep
it open in the background, and only one process gets it.

## The robot describes nothing, or reacts to `!!!`

**Almost always the vision prompt, not the model.** `moondream` is 1.7 GB and it collapses
if you ask it to act rather than describe. Measured at temperature 0, three identical runs
each:

| prompt | what moondream returned |
| --- | --- |
| `Describe this image, including any people in it.` | a clean, accurate caption |
| …`as if you were a friendly robot looking at it.` | `!!!!!!!!!!!!!!` |
| …`Mention people if there are any.` | empty string |
| anything `in one short sentence` | first token missing — `urns of blue…` |

So `09_vision.py` asks the vision model **only to describe**, and lets the chat model add
the personality afterwards. If you add character back into `PROMPT`, expect this. Keep the
captioning instruction plain and put your persona in `config.yaml` instead.

An empty caption is reported as `nothing describable in that frame`, which is deliberately
worded differently from `no frame from the camera` — one is the model, the other is the
hardware, and they need different fixes.

## `Class AVFFrameReceiver is implemented in both …` on startup

A long `objc[…]` warning about duplicate classes ending "may cause spurious casting
failures and mysterious crashes". **Harmless, and not caused by your code.**
`opencv-python` and `av` (a Whisper dependency) each bundle their own copy of ffmpeg, and
macOS notices when both load into one process. You only see it in scripts that use the
camera *and* the microphone — `tools/check_setup.py`, or your own project combining
`06_voice_chat.py` with `09_vision.py`. Both libraries work regardless; we have not seen
it cause an actual failure. Ignore it.

## Motors buzzing after a crash

A script that died before `close()` left them attached and drawing current.

```bash
python -c "from ohbot import ohbot; ohbot.close()"
```

Prevent it by always using `with Ohbot(...) as bot:` rather than calling methods directly.

## The head drifts off to one side

It should recentre itself after each utterance. If you added a pose or gesture, make sure
it returns `HEADTURN`, `HEADROLL` and `EYETURN` to 5, or call `bot.recentre()`. Poses may
tilt the head for character, but the tilt has to be undone or it compounds until the robot
is addressing the wall.

## "Kokoro unavailable, using macOS say"

The model files are missing. `python tools/check_setup.py` downloads them (~336 MB) into
`models/`. The demo still runs on the built-in voice meanwhile — deliberately, since a
worse-sounding demo beats no demo.

## `PermissionError: [Errno 1] Operation not permitted` loading the speech model

A long traceback ending in `ssl.create_default_context(cafile=os.environ["SSL_CERT_FILE"])`.
Nothing to do with the robot, and nothing to do with the model being missing.

Whisper checks HuggingFace for a newer copy **even when the model is already cached**, and
building the HTTPS client reads the certificate bundle in `$SSL_CERT_FILE`. On a
corporate-proxy setup (Zscaler and friends) that bundle usually lives under `~/Documents`,
which macOS protects — so your terminal is denied and the read fails with `EPERM`
(`Operation not permitted`) rather than a normal permission error.

The fix is to stop it reaching out at all, which is what this kit wants anyway:

```bash
export HF_HUB_OFFLINE=1          # add it to ~/.zshrc
```

The model then loads straight from `~/.cache/huggingface/hub`. Confirm you have it:

```bash
ls ~/.cache/huggingface/hub | grep faster-whisper
```

If it isn't cached yet, run `python tools/check_setup.py` **with `HF_HUB_OFFLINE` unset** once
to download it. The two other fixes, if you'd rather keep it online: grant your terminal Full
Disk Access in System Settings → Privacy & Security, or move the cert somewhere outside
`~/Documents` and update `SSL_CERT_FILE`.

## Ollama errors

- `Cannot reach Ollama` → start it: `ollama serve`
- `Model 'x' is not installed` → `ollama pull x`. The error lists what you do have.
- Slow first reply → the model is loading. `convo.warm_up()` at startup avoids it, and
  `tools/check_setup.py` warms everything up before the demo.

## Replies are too long

The robot monologues because `say()` renders the whole string to a WAV before the lip
moves. Lower `llm.max_sentences` in `config.yaml` (default 3, try 2). Small models ignore
"be brief" instructions, which is why the cap is enforced in code rather than the prompt.

## The emotion is wrong sometimes

Expected — it's a small model and the choice is stochastic. Measure rather than guess:

```bash
python tools/check_empathy.py --repeats 3
```

It scores 12 labelled cases and reports which are *unstable across runs*, which is what
misbehaves in front of an audience. A single run is a sample, not a measurement — we
saw the same code score 12/12 and then 10/12.

## Examples fail with "No module named ohbot_kit"

Run them from the repository root:

```bash
cd robot_hackathon
python examples/01_hello_robot.py     # not: cd examples && python 01_...
```

The examples check for this and tell you, because running elsewhere would also create a
second, uncalibrated `ohbotData/`.
