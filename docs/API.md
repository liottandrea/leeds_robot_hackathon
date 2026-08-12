# API cheat sheet

Everything you can tell the robot to do. Keep this open while you build.

```python
from ohbot_kit import Ohbot, expression, setup

cfg, convo, robot_kwargs = setup()
with Ohbot(**robot_kwargs) as bot:
    bot.speak("Hello!", emotion="happy", gesture="nod")
```

Always use `with` — it guarantees the motors are detached at the end. A script that
dies before `close()` leaves them attached, drawing current and buzzing audibly until
you replug the robot.

**Run from the repository root.** The ohbot library resolves `ohbotData/` (motor
calibration, speech database, sounds) relative to the working directory, so running
from elsewhere silently creates a second, uncalibrated copy.

## Robot

| Call | Does |
| --- | --- |
| `bot.speak(text, emotion=None, gesture=None, recentre=True)` | Speaks with lip sync. The gesture plays *underneath* the speech. |
| `bot.express("curious")` | Hold a face. See poses below. |
| `bot.gesture("slow_nod", blocking=False)` | Play a movement on its own. |
| `bot.look_at("up_left")` or `bot.look_at(x=8, y=3)` | Eyes lead, head follows partway. |
| `bot.gaze(x, y)` | Eyes only, head still. |
| `bot.listening(True)` | Nod and blink while the *user* talks. |
| `bot.recentre()` | Return head and eyes to face the person. |
| `bot.read_sensor(0)` | Sensor pin 0–6 → float 0–10. Returns 0.0 with no robot. |
| `bot.set_eyes(r, g, b)` | Eye LEDs, each channel 0–10. |
| `bot.set_state("thinking")` | Eye colour by state: listening / thinking / speaking. |

`Ohbot(idle=True, colours=None, blink_interval=(2, 6), drift_interval=(4, 9), has_headroll=True)`

## Emotions

`bot.express(name)`, and the names the LLM can choose from:

`confused` · `curious` · `excited` · `happy` · `neutral` · `sad` · `scared` ·
`surprised` · `sympathetic` · `thinking`

## Gestures

Passed to `bot.speak(gesture=...)` or `bot.gesture(...)`. Choose by meaning:

| Gesture | Means |
| --- | --- |
| `nod` | agreement, understanding, yes |
| `slow_nod` | sympathy, taking something in seriously |
| `shake` | disagreement, no, disbelief at something bad |
| `tilt` | curiosity, mild puzzlement |
| `double_take` | shock at something startling |
| `lean_in` | close interest, wanting to hear more |
| `perk_up` | delight at good news |
| `look_away` | embarrassment, discomfort, thinking to oneself |
| `shiver` | fear, dread, being creeped out |
| `recoil` | alarm or disgust at something unpleasant |
| `blink` / `double_blink` | a small neutral beat / mild confusion |

## Look directions

`user` (= `ahead`) · `left` · `right` · `up` · `down` ·
`up_left` · `up_right` · `down_left` · `down_right`

Or coordinates: `x` is 0 (its right) to 10 (its left), `y` is 0 (down) to 10 (up).

## Motors

All eight are real. The vendor's own docs table omits `TOPLIP` and `HEADROLL`.

| # | Constant | Moves | Notes |
| --- | --- | --- | --- |
| 0 | `HEADNOD` | head up/down | |
| 1 | `HEADTURN` | head left/right | |
| 2 | `EYETURN` | eyes left/right | |
| 3 | `LIDBLINK` | eyelids | **10 = open, 0 = shut.** Rest is 10, not 5 |
| 4 | `TOPLIP` | upper lip | driven by lip sync while speaking |
| 5 | `BOTTOMLIP` | lower lip | driven by lip sync while speaking |
| 6 | `EYETILT` | eyes up/down | |
| 7 | `HEADROLL` | head tilt | not in the vendor docs; may not be fitted on every unit |

Positions are 0–10 and are clamped to each robot's calibrated range from
`ohbotData/MotorDefinitionsv21.omd`, so you cannot drive a servo past its limits.

For anything not wrapped here, the raw library is still available:

```python
from ohbot import ohbot

ohbot.move(ohbot.HEADROLL, 8, 3)  # motor, position 0-10, speed 0-10
```

## LLM

```python
# Plain reply, streamed sentence by sentence so speech starts sooner
for sentence in convo.stream_sentences("tell me a joke"):
    bot.speak(sentence)

# Reply plus a face and a movement
action = convo.respond_with_action(text, expression.EMOTIONS, expression.GESTURE_NAMES)
# -> {"say": ..., "emotion": ..., "gesture": ..., "gaze_x": 5, "gaze_y": 5}
bot.speak(action["say"], emotion=action["emotion"], gesture=action["gesture"])

# Reply broken into beats, each with its own face -- expression changes mid-reply
for beat in convo.respond_with_beats(text, expression.EMOTIONS, max_beats=3):
    bot.speak(beat["say"], emotion=beat["emotion"], gesture=beat["gesture"])

convo.reset()  # forget the conversation
convo.warm_up()  # load the model now, so the first reply isn't slow
```

`respond_with_action` gives one face per reply; `respond_with_beats` gives one per
sentence, so the robot can be concerned while it restates your problem and brighter as it
offers help. Beats cost one `say()` call each, so keep `max_beats` low for live demos.

`respond_with_action` uses Ollama's JSON-schema mode, **not** the tools API — phi4-mini
advertises tool support but never emits tool calls. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Voice input

```python
from ohbot_kit import make_listener

listener = make_listener(cfg)

audio_in = listener.record_utterance(bot)  # pass bot so it ignores the robot's own voice
text = listener.transcribe(audio_in)
```

## Extending it

Add to `ohbot_kit/expression.py`:

```python
POSES["smug"] = {LIDBLINK: 6, HEADNOD: 6, HEADROLL: 7}
GESTURES["shrug"] = [(HEADROLL, 7, 6, 0.3), (HEADROLL, 3, 6, 0.3), (HEADROLL, 5, 4, 0.2)]
GESTURE_MEANINGS["shrug"] = "indifference, who knows"
```

Also add it to `EMOTION_GESTURES`, which lists the gestures that suit each emotion — a
gesture in no shortlist can never be chosen. Offering all twelve at once measurably
under-used them: `double_take` took 35% of picks while four gestures never fired at all,
even on prompts that suited them. Narrowing the choice cut that to 20% and made
incoherent pairings impossible rather than merely discouraged.

Both become choices the LLM can pick immediately — the JSON schema is built from those
tables. **Give every gesture a meaning:** without one the model picks on the name alone,
and we measured it choosing `shake` (which means *no*) for "I finally finished my project!".

Two rules when adding poses:

- End gestures with the orientation axes (`HEADTURN`, `HEADROLL`, `EYETURN`) back at 5,
  or the offset persists into the next utterance.
- Mouth values (`TOPLIP`, `BOTTOMLIP`) are ignored while speaking — lip sync owns the
  mouth then. Set them freely; they apply when the robot is quiet.
