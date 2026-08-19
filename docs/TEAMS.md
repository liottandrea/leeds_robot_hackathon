# Putting Ohbot on a Teams call

Ohbot sits in a meeting, follows it, and answers when someone says its name.
Works the same on Zoom, Meet and Slack huddles — nothing here is Teams-specific.

```bash
python tools/check_call_audio.py       # prove the cables work
python examples/10_teams_call.py       # join the call
```

Everything still runs locally. Whisper transcribes, Ollama thinks, Kokoro speaks;
no audio and no transcript leaves the machine.

## Status

One routing is confirmed working on real hardware. The rest is written from how
CoreAudio behaves, not from a meeting that ran.

| | |
| --- | --- |
| **Works** — robot as the participant, you on your phone | [below](#a-real-call-with-no-audio-midi-setup-at-all) |
| **WIP** — you and the robot both on the call from one Mac | [below](#being-on-the-call-too-wip) |
| Untested — Multi-Output / Aggregate variants, Windows | marked where they appear |

**Confirmed:** Teams speaker `BlackHole 2ch`, mic `BlackHole 16ch`, noise suppression
off, robot on `--input "BlackHole 2ch" --output "BlackHole 16ch"`, and you joining the
same meeting from a phone. The robot hears the call, and everyone hears its replies.
The wake word gate works. So does `--open-mic`.

**Not working yet:** being on the call from the Mac *at the same time* as the robot.
Details and suspects in that section — don't follow it expecting it to work.

---

## The idea

Teams has no bot you can install for this, and doesn't need one. Teams only cares
which audio **devices** it is pointed at. So Ohbot becomes the microphone, and
Teams' speaker becomes Ohbot's ears. Teams never learns a robot joined the call.

```text
remote participants ──► Teams ──► "Teams Out" (Multi-Output)
                                      ├─► BlackHole 2ch ──► Ohbot's ears
                                      └─► your headphones ──► you

Ohbot's voice ──► "Ohbot Voice" (Multi-Output)
                      ├─► BlackHole 16ch ──► Teams mic ──► the call
                      └─► laptop speakers ──► the room
```

Two cables, because one cable cannot carry both directions. The *Multi-Output*
halves are what stop the robot stealing the audio: without them, routing Teams
into BlackHole means you can no longer hear the call yourself.

---

## macOS setup, about ten minutes

> Untested as a whole. The `BlackHole 2ch` / `BlackHole 16ch` pair underneath it is
> confirmed; the Multi-Output and Aggregate devices wrapped around it are not. If
> you want the shortest confirmed path, skip to
> [a real call with no Audio MIDI Setup](#a-real-call-with-no-audio-midi-setup-at-all).

### 1. Install two cables

```bash
brew install blackhole-2ch blackhole-16ch
```

Log out and back in afterwards, or macOS won't list them. Two *different* variants
rather than one, because a single BlackHole device carries a single signal — put
both directions through it and the robot hears itself in a loop.

> If Teams is installed you already have a device called **Microsoft Teams Audio**
> in the list. It is not the cable you want: Teams installs it for its own
> screen-share audio and controls both ends of it. Ignore it.

### 2. Build two combined devices

Open **Audio MIDI Setup** (`⌘-space`, "Audio MIDI"). Click **+** at the bottom
left and create:

| Name it | Type | Tick these members |
| --- | --- | --- |
| `Teams Out` | Multi-Output Device | BlackHole 2ch, your headphones |
| `Ohbot Voice` | Multi-Output Device | BlackHole 16ch, MacBook Speakers |

Set every BlackHole device to **48000 Hz** while you're here — select it, then
Format. Members of a Multi-Output must agree on a rate, and a mismatch shows up as
crackling or as one member going silent.

> Keep the two Multi-Outputs on **different** physical outputs — headphones for
> the call, laptop speakers for the robot's voice. Two Multi-Outputs sharing one
> physical output fight over it.

### 3. Optional, but worth it: let Ohbot hear you too

Teams does not loop your own microphone back, so via `Teams Out` Ohbot hears
everyone on the call **except you**. To fix that, click **+** once more:

| Name it | Type | Tick these members |
| --- | --- | --- |
| `Ohbot Ears` | Aggregate Device | BlackHole 2ch, your microphone |

That device carries three or four channels — the call on some, you on the others.
`speech_to_text.channels: all` mixes them down; leave it at `1` and everything you
say is dropped without an error.

### 4. Point Teams and Ohbot at them

**Teams → Settings → Devices:**

| Setting | Value |
| --- | --- |
| Speaker | `Teams Out` |
| Microphone | `BlackHole 16ch` |
| Noise suppression | **Off** |

Noise suppression is not optional. Teams classifies synthetic speech arriving on a
virtual device as noise and gates it, so participants hear the robot cutting in and
out. Restart Teams after installing BlackHole, or the devices won't appear.

> **This gives the robot your microphone.** Teams has one mic slot, `BlackHole 16ch`
> now occupies it, and your own voice no longer reaches the call. That is fine when
> the robot is the participant and you are watching. Being on the call yourself as
> well does not work yet — see [Being on the call too](#being-on-the-call-too-wip).

**`config.local.yaml`** (git-ignored; `cp config.local.example.yaml config.local.yaml`):

```yaml
audio:
  input_device: "Ohbot Ears"     # or "BlackHole 2ch" if you skipped step 3
  output_device: "Ohbot Voice"

speech_to_text:
  channels: all                  # mix every channel of the Aggregate Device
  capture_rate: device           # capture at 48 kHz, resample to 16 kHz for Whisper
  silence_seconds: 1.2           # people pause mid-sentence on calls
```

`capture_rate: device` matters more than it looks. Asking CoreAudio for 16 kHz can
renegotiate BlackHole *down* to 16 kHz, which then breaks every Multi-Output and
Aggregate Device it belongs to.

### 5. Check it

```bash
python tools/check_call_audio.py
```

It resolves the device names, checks they are cables rather than your headset,
compares the channel count against your config, listens for real audio arriving,
and confirms the robot's voice doesn't come back into its own ears. Run it with
the call already open and someone talking.

---

## Test it without Teams first

Worth doing before any of the above. This proves the whole chain — cable, 48 kHz
resampling, Whisper, the LLM, the robot's voice — with no meeting and no Audio
MIDI Setup, so when something breaks later you know it isn't this part.

1. Set the macOS **system output** to `BlackHole 2ch` (Sound settings, or
   option-click the volume icon). You will stop hearing your machine — expected,
   everything is going down the cable now.
2. Play anything with speech in it: a YouTube video, a podcast.
3. Both commands take device overrides, so nothing in your config needs touching:

```bash
python tools/check_call_audio.py --input "BlackHole 2ch" --output "MacBook Pro Speakers"
python examples/10_teams_call.py --input "BlackHole 2ch" --output "MacBook Pro Speakers" --open-mic
```

The diagnostic should report `[PASS] audio arrives`, and the example should print
transcripts of the video as it plays. `--open-mic` because a video won't say
"Ohbot" for you. It answers out of the laptop speakers, not the cable, so you can
hear it.

Then put the system output back, and go build the real routing.

### Testing the real thing on your own

You need a second participant to talk. Start a **Meet now** meeting on the laptop
and join it again from your phone — the phone is a real remote participant, so
audio from it travels the actual path Teams will use on a real call.

---

## A real call with no Audio MIDI Setup at all

The two Multi-Output devices above exist for one reason: so **you, in the room**,
can hear the call and the robot. The call itself does not need them. Skip them
entirely and use your phone as both your ears and your mouth:

| Where | Setting |
| --- | --- |
| Teams → Devices | Speaker = `BlackHole 2ch`, Mic = `BlackHole 16ch`, noise suppression **Off** |
| Your phone | joined to the same meeting — you talk into it, you hear Ohbot out of it |

```bash
python examples/10_teams_call.py --input "BlackHole 2ch" --output "BlackHole 16ch"
```

That is the complete loop: the call arrives on `BlackHole 2ch`, the robot answers
into `BlackHole 16ch`, and Teams sends that to everyone. The laptop itself goes
silent, which is the trade — you hear the meeting through the phone instead.

Get this working first. Then, if you want the room to hear it too, build the
Multi-Output devices and swap the two names for `Teams Out` and `Ohbot Voice`.
Nothing else changes.

---

## Being on the call too (WIP)

> **This does not work yet.** Both approaches below were tried and neither got a
> person and the robot onto the same call from one Mac. They are recorded so the
> next attempt starts from the dead ends rather than rediscovering them. If you
> need this working today, use your phone as your own endpoint — that route is
> confirmed.

Everything above puts the **robot** on the call. You are a spectator, in both
directions at once, and each has its own cause:

- **You can't speak.** Teams has one microphone slot and `BlackHole 16ch` is in it,
  carrying the robot's voice. Nothing you say reaches the meeting.
- **You can't hear.** Teams' speaker is `BlackHole 2ch`, which goes to the robot.

The second half is the easy one and probably does work: a Multi-Output Device
(`BlackHole 2ch` + your headphones) as Teams' speaker feeds both of you. Untested,
but nothing about it is unusual. The microphone half is the hard one.

### Attempt 1: let the robot talk out loud — did not work

The idea: put the robot's voice in the room and let your own microphone carry it to
the call, as if a robot were sitting on your desk.

| Where | Setting |
| --- | --- |
| Teams → Speaker | `Teams Out` (Multi-Output: BlackHole 2ch + headphones) |
| Teams → Mic | `MacBook Pro Microphone` |
| Noise suppression | Off |

```bash
python examples/10_teams_call.py --input "BlackHole 2ch" --output "MacBook Pro Speakers"
```

Reported not working. Suspects, roughly in order:

1. **Teams gating the robot anyway.** Noise suppression off is not the only filter —
   Teams also applies echo cancellation, and audio from your speakers arriving at
   your mic is precisely what that is built to remove. It cannot tell the robot's
   voice from the meeting's own echo.
2. **Level.** Laptop speakers at conversational volume, a metre from a mic tuned for
   a voice at 30 cm, and Teams' automatic gain riding on top.
3. **The robot hearing itself and re-triggering.** Handled while it speaks, but not
   in the gap immediately after.

Worth trying next: a separate USB mic pointed at the robot rather than the built-in
one, and checking Teams' own mic level meter while the robot talks — if the meter
doesn't move, the problem is (1) or (2) and not the kit.

### Attempt 2: mix two sources into one virtual mic — not completed

Fully digital and the right answer in principle. BlackHole is a cable, not a mixer,
so it needs a mixer — **LadioCast** (free, Mac App Store) or **Loopback** (Rogue
Amoeba, paid) — plus a third cable for the result:

```bash
brew install blackhole-64ch     # the mixed "microphone" bus
```

In LadioCast: Input 1 = your microphone, Input 2 = `BlackHole 16ch` (the robot),
Main output = `BlackHole 64ch`. Teams' microphone = `BlackHole 64ch`.

Not verified — nobody has run it here. It is the most likely of the two to work,
since it never leaves the digital domain and so gives echo cancellation nothing to
grab onto.

**A dead end worth naming:** an Aggregate Device will not do this job, however much
it looks like it should. Aggregating your mic with `BlackHole 16ch` hands Teams an
18-channel device, and Teams reads the first channel or two — BlackHole's. Your
voice sits on channels 17–18 and is never read. Aggregate devices place channels
side by side; mixing them down is a thing only a mixer does.

---

> Don't reverse those two. `BlackHole 16ch` is fine for the robot's **voice**, but
> makes a poor pair of **ears**: Teams writes to two of its sixteen channels and
> `channels: all` averages across all of them, so the call arrives eight times
> quieter and lands under the threshold. The robot then reports audio arriving but
> too quiet — accurate, but avoidable. Listen on `BlackHole 2ch`, where both
> channels carry.

---

## Windows (untested)

Nobody has run this on Windows. Written from the shape of the macOS setup, so treat
it as a starting point rather than instructions.

Same idea, different parts: install [VB-CABLE](https://vb-audio.com/Cable/) twice
(CABLE A and CABLE B), and use **VoiceMeeter** for the Multi-Output halves, since
Windows has no built-in equivalent. Teams' mic becomes `CABLE-A Input`, Ohbot's
`output_device` becomes `CABLE-A Output`.

The kit's own side needs nothing Windows-specific — `CallListener` reads channel
counts and sample rates off whatever device it is given.

---

## Using it

It stays quiet until addressed. Say its name first:

```text
"So I think we should ship on Friday."      → nods along, says nothing
"Ohbot, what did we decide about Friday?"   → answers out loud into the call
```

```bash
python examples/10_teams_call.py --wake computer   # different wake word
python examples/10_teams_call.py --open-mic        # reply to everything
```

Run `--open-mic` once. It replies to every utterance, a second late, over the top
of whoever is still speaking — which is the clearest possible argument for the
wake word.

It also doesn't greet the call. Speaking unprompted into a live meeting is rude,
and a greeting always lands just as someone else starts talking.

---

## Tell people it's there

The robot's voice is audible to everyone on the call, and it is transcribing what
it hears. The transcription is local — Whisper and Ollama both run on your laptop,
and nothing is uploaded or stored — but plenty of organisations treat any
transcription as recording, so say it's there before you join.

---

## When it goes wrong

**Participants hear nothing.** Teams noise suppression is on, or Teams' mic isn't
`BlackHole 16ch`. Check in a call: Teams' own mic level meter should move when the
robot talks.

**Ohbot hears nothing.** Teams' speaker isn't the Multi-Output containing
BlackHole. `python tools/check_call_audio.py` will say so.

**Ohbot hears the call but never you.** Expected, and not solved — you are not in
the call's audio, since Teams doesn't loop your own microphone back. The Aggregate
Device is meant to fix it (with `channels: all`), but that whole direction is
[WIP](#being-on-the-call-too-wip). Talk to it from your phone in the meantime.

**It hears you but says nothing.** It was not addressed. Say "Ohbot, ..." or pass
`--open-mic`. It prints a hint saying so for the first couple of unaddressed
utterances; either way, plain `call: ...` lines mean it is hearing you perfectly.

**Crackling, or one output silent.** Rate mismatch inside a Multi-Output. Set every
member to 48000 Hz in Audio MIDI Setup.

**It answers itself.** The two cables are crossed — Ohbot's output is feeding its
own input. The self-hearing check catches this. Note that hearing itself
*acoustically* through the built-in mic is fine and already handled: audio is
discarded while the robot speaks.

**It replies to the wrong things.** Whisper writes the name as "oh bot" or "odd
bot" often enough that both are normalised; anything else, use `--wake` with a word
it hears reliably.

**Replies land too late to be useful.** Roughly 2–5 s from end-of-speech to first
word, mostly Whisper and Ollama. `speech_to_text.model: tiny.en` takes a good chunk
off, at some cost in accuracy.

---

## The other route, and why not

A genuine Teams participant bot — one that appears in the roster — means Graph
cloud communications or Azure Communication Services call automation: an Azure
tenant, an app registration, **tenant admin consent**, and a real-time media stack.
The admin consent alone will not clear inside a hackathon. This gets you the same
demo today.
