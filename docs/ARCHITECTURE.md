# How it works

Read this before "fixing" anything that looks odd. Three of the strangest-looking
decisions in this codebase are load-bearing, and each was arrived at by measurement.

## Layout

```
ohbot_kit/       the library
  robot.py         speech, expression, gesture, gaze, idle motion
  expression.py    POSES, GESTURES, look directions -- the vocabulary
  llm.py           Ollama client, sentence streaming, structured actions
  tts.py           Kokoro speech
  voice.py         microphone + local Whisper
  audio.py         device selection and output routing
  serial_safe.py   the write lock
  config.py        config.yaml + config.local.yaml merge
examples/        01-09, numbered in the order to read them
tools/           check_setup, check_port, check_empathy
docs/            you are here
ohbot_chat.py    the full chat app
template.py      copy this to start your project
```

Nothing needs installing: `examples/_bootstrap.py` puts the repository root on
`sys.path`. One line beats `pip install -e .` when twenty people are setting up at once.

## Three monkeypatches, and why

The `ohbot` library does some things we need to change. Rather than fork it, we rebind
three of its functions at runtime.

### 1. `_generateSpeechFile` → Kokoro (`tts.py`)

Swapping the voice looks like it should cost lip sync, because `say()` does synthesis and
lip movement together. It doesn't — **on macOS the lip is driven by loudness, not
phonemes**. `say()` opens the generated WAV, sums the sample bytes in chunks of
`framerate / 10`, normalises to 0–10, and feeds that envelope to the lip motor. Real
phoneme data is used only on Raspberry Pi, where `synthesizer == "festival"`.

So anything that writes a valid WAV gets lip sync free. Two constraints follow from that
same envelope code:

- It indexes `buffer[i] + buffer[i+1]*256`, so the WAV **must be 16-bit PCM**. Kokoro
  emits float32, so `tts.py` converts.
- It loops `range(0, length - chunk, chunk)`. Audio under ~0.2 s leaves an empty list and
  `say()` then raises `IndexError` on `times[-1]`. Every clip gets 0.3 s of trailing
  silence — that's why a one-word reply doesn't crash.

Kokoro is also *faster* than macOS `say`: 0.62 s to generate 4.5 s of audio, versus 1.25 s.

### 2. `_playSpeech` → device routing (`audio.py`)

`_playSpeech` calls `playsound()`, which always uses the system default output — there is
no device argument. To send audio to a chosen headset or speaker we replace it with one
that reads the WAV and plays it through `sounddevice`. If the device rejects the stream
(a USB headset need not support Kokoro's 24 kHz) it falls back to the default with a
warning: losing routing beats losing audio.

Device matching is **direction-aware** because a headset appears twice in the device list
under an identical name, once with input channels and once with output. Names are used
rather than indices because indices shift when devices are plugged and unplugged.

### 3. `_serwrite` → a lock (`serial_safe.py`)

This is the one that makes the empathy layer possible.

`_serwrite` guards concurrent writes with a `writing` boolean on Windows and Linux — but
**on macOS there is no guard at all**, while `say()` drives the lip motor from its own
thread. So a gesture running during speech could interleave with the lip-sync stream and
corrupt motor commands. That is why idle motion used to freeze during speech.

Freezing is the wrong trade for an expressive robot. All 21 of the library's serial writes
funnel through `_serwrite`, and a standard `move()` emits exactly one newline-terminated
message per call:

```
m0<motor>,<position>,<speed>\n
```

So a lock there gives **message-level atomicity**. Threads may still interleave whole
commands — fine, the firmware parses line by line — but a command can no longer be cut in
half. Measured: during one 5.16 s utterance, 72 lip-sync moves and 8 gesture moves
interleaved with no errors.

The lock is **reentrant** because `read_sensor` holds it across a whole write-then-read
transaction, and the inner `_serwrite` would deadlock on a plain `Lock`.

## The mouth ownership rule

While speaking, the lip-sync thread owns `TOPLIP` and `BOTTOMLIP`. Poses may set them, but
`robot._move()` drops those values while `speaking` is set — otherwise a smile fights the
lip sync and produces mush. Set mouth values freely in a pose; they apply when quiet.

## Recentring

Poses tilt the head for character (`curious` rolls to 8). Nothing put it back, so the
offset persisted into the next utterance and compounded until the robot addressed the wall.
`speak()` now recentres afterwards, waiting for the gesture thread to finish so it doesn't
fight a keyframe mid-flight. The return is slow on purpose: snapping to centre reads as a
twitch, settling reads as relaxing.

## Structured output, not tool-calling

`respond_with_action` passes a JSON schema in Ollama's `format` field. It does *not* use
the tools API, because phi4-mini advertises a `tools` capability but returned
`tool_calls: None` on 3/3 attempts and actively refused ("I'm unable to set a real-world
object's emotional state"). Schema-constrained JSON parsed first time in 0.5–0.7 s.

It also runs at a **lower temperature** (0.3) than plain chat (0.7). Picking an emotion is
a classification, not a creative act; at 0.7 the same 12 cases scored 12/12 on one run and
10/12 on the next.

Gestures are presented to the model **with their meanings**, not just names. Given bare
names it chose `shake` — which means *no* — for "I finally finished my project!".

## Brevity is enforced in code

`llm.MAX_SENTENCES` caps spoken sentences regardless of what the model does. Small models
ignore "never more than 30 words", and because `say()` renders the whole string to a WAV
before the lip moves, a long reply is a long freeze followed by a monologue the listener
cannot interrupt.

## Running without a robot

The library guards its writes on `connected`, so `move()` and friends are silent no-ops
and `say()` still plays audio — the whole conversation loop works with no hardware. The one
exception is `readSensor()`, which calls `ser.flushInput()` unguarded and raises
`AttributeError` on `None`; use `bot.read_sensor()`, which returns 0.0 instead.
