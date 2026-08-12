# Contributing

Thanks for helping improve the kit. Most contributions here are new expressions,
new examples, or fixes found while running a hackathon — all welcome.

## Setup

```bash
git clone <repo> && cd robot_hackathon
uv venv --python 3.11 && source .venv/bin/activate   # or python -m venv .venv
pip install -r requirements.txt -r requirements-dev.txt
pre-commit install
```

`pre-commit install` is the important line: it runs the same checks CI does, so you
find problems before pushing.

## The checks

```bash
ruff format .        # format
ruff check --fix .   # lint
mypy ohbot_kit       # types
pytest               # tests
```

All four must pass. CI runs them on Ubuntu, macOS and Windows against Python 3.11 and 3.12.

## Tests run without a robot

`tests/conftest.py` fakes `ohbot` and `sounddevice` in `sys.modules`, so the suite needs
no hardware, no audio device and no PortAudio, and finishes in about two seconds.

The fake **records every motor command**, which is how behaviour is asserted:

```python
def test_something(bot, fake_ohbot):
    bot.express("curious")
    assert ex.HEADROLL in fake_ohbot.motors_moved()
    assert fake_ohbot.final_position(ex.HEADNOD) == 5
```

Tests that genuinely need hardware are marked and skipped by default:

```python
@pytest.mark.hardware
def test_real_robot(): ...
```

```bash
pytest -m hardware      # run those, with a robot plugged in
```

## What a good PR looks like

- **One concern per PR.** Formatting churn mixed with a behaviour change is very hard to review.
- **A test for anything that could regress.** Every test in `tests/` maps to a bug that
  actually happened; if you fix something, leave behind the test that would have caught it.
- **Say what you verified.** "Ran `08_empathy_chat.py` on hardware, the head recentres" is
  worth more than "should work". If you couldn't test something, say so — that's useful, not
  embarrassing.
- **Keep the docs true.** `docs/API.md` is the reference participants read; if you add a
  pose or gesture, add it there.

## Adding poses and gestures

The most common change. In `ohbot_kit/expression.py`:

```python
POSES["smug"] = {LIDBLINK: 6, HEADNOD: 6, HEADROLL: 7}
GESTURES["shrug"] = [(HEADROLL, 7, 6, 0.3), (HEADROLL, 3, 6, 0.3), (HEADROLL, 5, 4, 0.2)]
GESTURE_MEANINGS["shrug"] = "indifference, who knows"
```

Two rules the tests enforce, both from real bugs:

1. **End a gesture with `HEADTURN`, `HEADROLL` and `EYETURN` back at 5.** Otherwise the offset
   persists into the next utterance and compounds until the robot faces the wall.
2. **Give every gesture a meaning.** The LLM picks by description; given bare names it chose
   `shake` — which means *no* — for "I finally finished my project!".

Anything you add automatically becomes a choice the LLM can make, because the JSON schema is
built from those tables.

## Before changing anything that looks odd

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first. Three monkeypatches and a
threading rule are load-bearing, and each is there for a measured reason. In particular,
removing the serial write lock, or the mouth guard in `robot._move`, breaks the robot in ways
that are obvious in the room and invisible in the diff.

## Checking the empathy layer still works

Type and lint checks cannot tell you whether the robot still feels alive:

```bash
python tools/check_empathy.py --robot --repeats 3
```

Scores emotion choice against labelled cases, performs them all on hardware, and verifies
gestures overlap speech. **One run is a sample, not a measurement** — the same code has scored
12/12 and 10/12 on consecutive runs. Use `--repeats` before concluding anything.
