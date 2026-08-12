## What and why

<!-- What changes, and what problem it solves. One or two sentences. -->

## How it was verified

<!-- Be specific and honest. "Ran examples/08_empathy_chat.py on hardware, the head
     recentres after each reply" beats "tested". If something could not be tested,
     say so -- that is useful information, not a failing. -->

- [ ] `ruff format --check . && ruff check . && mypy ohbot_kit && pytest` all pass
- [ ] Tested on a physical robot
- [ ] Added a test for anything that could regress

## Robot behaviour

<!-- Delete if this does not touch expression, gesture, speech or threading. -->

- [ ] Gestures still overlap speech rather than playing before it
- [ ] The head returns to centre after speaking
- [ ] Lip sync is unaffected
- [ ] `python tools/check_empathy.py --robot` still passes

## Docs

- [ ] `docs/API.md` updated if the public API changed
- [ ] New poses/gestures have a `GESTURE_MEANINGS` entry
