# Project ideas

Don't spend the first two hours deciding what to build. Pick one of these, or use it as a
starting point and take it somewhere better.

The robot's real advantage over a chatbot on a screen is that it has a **face, a body and
presence in a room**. The strongest projects use that. A chatbot that happens to have a
head is the most common way to waste this hardware.

Start from `template.py`.

---

## Warm-up (under an hour)

**Mood ring** — the robot reads a sentence you type and just *reacts*: face, gesture and a
single word. No conversation. Good for getting comfortable with the expression vocabulary.

**Emotion charades** — the robot performs an emotion, you guess it, it tells you if you're
right. Uses `expression.POSES` and a scorekeeper.

**Greeter** — the distance sensor notices someone approaching and the robot greets them,
then says goodbye when they leave. See `examples/07_sensors.py`. Surprisingly effective as
a demo because nobody has to touch anything.

**New personas** — add characters to `config.yaml`: a grumpy robot, a sports commentator,
a robot that only speaks in questions. Nearly free, and instantly distinctive.

---

## Medium (a few hours)

**Active listener** — a robot that mostly listens. It nods, tilts, says "mm-hm" and asks
one good follow-up question. Deliberately says very little. Leans entirely on
`bot.listening()` and backchannel behaviour, which is where the illusion of presence
actually comes from.

**Storyteller with expression** — it tells a story and changes face and voice for each
beat. Extend `respond_with_action` to return a *list* of `{say, emotion, gesture}` beats
rather than one, so expression changes mid-story. (A documented stretch of the schema —
see ARCHITECTURE.md.)

**Interview coach** — asks you practice questions, listens to your spoken answer, and
gives feedback with appropriate sympathy or encouragement. Voice in, voice out.

**The robot that reacts to your desk** — `examples/09_vision.py` plus a reason to look.
It comments when something changes, notices when you leave, greets you when you return.

**Language tutor** — speaks a phrase in another language, listens to you repeat it, and
reacts to how close you got. Kokoro has multilingual voices.

**Emotional mirror** — it detects the *user's* emotion from what they say and mirrors it
back, or deliberately counterbalances it (calm when you're stressed). Compare which feels
better — an interesting thing to demo.

**Two-robot conversation** — if another team lends you a robot, have two hold a
conversation with each other, each with a different persona. Use headsets or they will
hear each other and loop.

---

## Ambitious (a full day or more)

**A robot with a memory** — it remembers you between sessions. Store facts to a file,
load them at startup, and have it bring one up unprompted: "How did your exam go?" The
single biggest jump in feeling like a relationship rather than a demo.

**Sentiment-aware assistant** — it notices *how* you're saying something, not just what,
and adjusts. Whisper gives you the text; timing and volume are available from the audio
buffer in `voice.py`.

**Robot theatre** — a scripted performance with timed gestures, eye colour, music via
`ohbot.playSound()`, and multiple characters through voice switching.

**Attention-following robot** — a webcam plus face detection so its eyes and head follow
whoever is speaking. `bot.look_at(x, y)` takes coordinates, so you can map a face position
straight onto gaze.

**Wellbeing check-in** — a daily conversation that asks how you are, listens properly, and
tracks answers over time. Handle this thoughtfully: it's the idea most likely to have
someone tell the robot something genuinely personal.

**Teach it a new skill live** — the user says "when I say X, do Y", and the robot writes a
new entry into `POSES`/`GESTURES` at runtime. Self-modifying, and demos beautifully.

---

## What impresses

Having watched this thing come together:

- **Movement during speech** reads as alive; posing then speaking reads as a machine.
  That's already handled — don't accidentally undo it by blocking on gestures.
- **Restraint beats constant motion.** A robot that gestures on every sentence looks
  twitchy. Stillness makes the movements that do happen mean something.
- **Backchannel while listening** does more work than anything on the robot's own turn.
- **Short replies.** Every extra sentence is dead air with a moving mouth.
- **Eye contact matters.** If the head drifts off-axis it stops feeling addressed to you.

## Things that sound good but disappoint

- **Long monologues.** You cannot interrupt the robot; a 30-second answer is 30 seconds of
  the audience waiting.
- **Big vocabulary, no meaning.** Twenty gestures the LLM picks at random look worse than
  five it picks well. Give every gesture a description.
- **Cloud APIs.** Everything here runs locally, so it works with no internet and no keys.
  Conference wifi has ruined more demos than bad code.
- **Complex vision loops.** A 23 GB vision model takes long enough per frame that the
  robot appears frozen. Use a small one.
