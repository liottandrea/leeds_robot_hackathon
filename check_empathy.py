"""Diagnose whether the empathy layer is actually working.

"Does it feel alive" splits into three questions. Two are measurable and this
script measures them; the third needs your eyes, and is printed as a checklist.

    python check_empathy.py             # emotion accuracy + mechanics, no robot needed
    python check_empathy.py --robot     # also runs the on-hardware mechanics checks

1. SEMANTIC   Does the LLM pick a fitting emotion for the sentiment?
              Scored against a labelled set. This is the one that silently rots
              when you change the model, the persona or the pose vocabulary.
2. MECHANICAL Do gestures actually overlap speech? Does anything write to the
              mouth while lip sync owns it? How long until the robot reacts?
3. PERCEPTUAL Does it look right to a person? Checklist at the end.
"""

import argparse
import sys
import time

import expression
import llm

# Each case lists the emotions a reasonable person would accept. Deliberately
# generous -- we are testing "not wrong", not "matches my favourite".
CASES = [
    ("My cat died last night.",              {"sad", "sympathetic"}),
    ("My grandmother is in hospital.",       {"sad", "sympathetic"}),
    ("I'm really scared about my exam.",     {"sad", "sympathetic", "curious"}),
    ("I lost my job today.",                 {"sad", "sympathetic"}),
    ("I just got promoted!",                 {"happy", "excited"}),
    ("I finally finished my project!",       {"happy", "excited"}),
    ("It's my birthday today!",              {"happy", "excited"}),
    ("There's a huge spider on my shoulder!", {"surprised", "excited"}),
    ("Guess what just happened!",            {"curious", "surprised", "excited"}),
    ("Why is the sky blue?",                 {"thinking", "curious", "neutral", "happy"}),
    ("What is two plus two?",                {"thinking", "neutral", "happy", "curious"}),
    ("I have no idea what you just said.",   {"confused", "curious", "thinking"}),
]

# Gesture tone matters as much as the face, and the first version of this check
# was too lenient: it only flagged bouncy gestures on sad input, so it missed
# `shake` (= "no") being chosen for "I finally finished my project!". Both
# directions are checked now.
BAD_ON_SAD = {"perk_up", "double_take"}       # bouncy under bad news
BAD_ON_GOOD = {"shake", "look_away"}          # reads as "no" / disengagement
SAD_CASES = {c[0] for c in CASES[:4]}
GOOD_CASES = {c[0] for c in CASES[4:7]}


def semantic_check(model, host, verbose=True):
    convo_system = llm.SYSTEM_PROMPT
    hits, tone_misses, invalid, times = 0, [], [], []

    print("\n1. SEMANTIC -- does the emotion fit the sentiment?\n")
    for prompt, acceptable in CASES:
        # Fresh conversation each time: we're testing the mapping, not memory.
        convo = llm.Conversation(model=model, system=convo_system, host=host)
        t0 = time.time()
        try:
            action = convo.respond_with_action(
                prompt, expression.EMOTIONS, expression.GESTURE_NAMES
            )
        except llm.OllamaError as e:
            print("  ERROR {}".format(e))
            return None
        elapsed = time.time() - t0
        times.append(elapsed)

        emotion = action.get("emotion", "")
        gesture = action.get("gesture", "")

        # A value outside the schema enum means the schema isn't binding.
        if emotion not in expression.EMOTIONS or gesture not in expression.GESTURE_NAMES:
            invalid.append((prompt, emotion, gesture))

        ok = emotion in acceptable
        hits += ok
        if prompt in SAD_CASES and gesture in BAD_ON_SAD:
            tone_misses.append((prompt, gesture, "bouncy gesture on bad news"))
        elif prompt in GOOD_CASES and gesture in BAD_ON_GOOD:
            tone_misses.append((prompt, gesture, "negative gesture on good news"))

        if verbose:
            print("  {} {:5.2f}s  {:<40} -> {:<12} {}".format(
                "PASS" if ok else "MISS", elapsed, prompt[:38], emotion, gesture))

    n = len(CASES)
    print("\n  emotion accuracy : {}/{}  ({:.0f}%)".format(hits, n, 100 * hits / n))
    print("  median latency   : {:.2f}s".format(sorted(times)[n // 2]))
    print("  schema violations: {}".format(len(invalid)))
    print("  gesture tone misses: {}".format(len(tone_misses)))
    if tone_misses:
        for prompt, g, why in tone_misses:
            print("      {!r} -> {}  ({})".format(prompt[:38], g, why))
    return {"accuracy": hits / n, "invalid": invalid, "tone_misses": tone_misses}


def mechanical_check():
    """On-hardware checks: concurrency, mouth ownership, and reaction latency."""
    import audio
    import config as config_mod
    import tts
    from ohbot import ohbot
    from robot import Ohbot

    print("\n2. MECHANICAL -- on the robot\n")
    cfg = config_mod.load(warn=False)
    try:
        audio.install_output(audio.resolve(cfg.get("audio.output_device"), audio.OUTPUT))
        tts.install(tts.KokoroTTS(voice=cfg.get("tts.voice", "af_heart")))
    except Exception as e:
        print("  (tts setup: {})".format(e))

    events = []
    original_move = ohbot.move

    def logged(m, pos, spd=5, eye=0):
        events.append((time.time(), m))
        return original_move(m, pos, spd, eye)

    ohbot.move = logged
    try:
        with Ohbot(idle=True) as bot:
            time.sleep(0.4)
            events.clear()
            t0 = time.time()
            bot.speak(
                "I am really sorry to hear that, it sounds like a very hard day.",
                emotion="sympathetic",
                gesture="slow_nod",
            )
            t1 = time.time()
    finally:
        ohbot.move = original_move

    mouth = {expression.TOPLIP, expression.BOTTOMLIP}
    during = [(t, m) for t, m in events if t0 < t < t1]
    lip = [e for e in during if e[1] in mouth]
    gest = [e for e in during if e[1] not in mouth]

    print("  speech window            : {:.2f}s".format(t1 - t0))
    print("  lip-sync moves during    : {}".format(len(lip)))
    print("  gesture moves during     : {}".format(len(gest)))
    if gest:
        print("  gesture spanned          : +{:.2f}s to +{:.2f}s".format(
            gest[0][0] - t0, gest[-1][0] - t0))

    concurrent = bool(lip and gest)
    print("\n  {} gesture and lip sync overlapped".format(
        "PASS --" if concurrent else "FAIL -- no overlap:"))
    if not concurrent:
        print("        the robot is posing before speaking, not moving while it speaks.")
    return {"concurrent": concurrent, "lip": len(lip), "gesture": len(gest)}


CHECKLIST = """
3. PERCEPTUAL -- only you can judge these. Watch it handle "my cat died":

  [ ] The face changes BEFORE the sentence finishes, not after.
  [ ] The head moves while it talks -- it is not a statue with a moving mouth.
  [ ] Lip movement still tracks the audio (the gesture hasn't disturbed it).
  [ ] Eyes are open at rest, not half-lidded.
  [ ] It blinks occasionally, and nods while YOU are talking.
  [ ] Sad input does not produce a bouncy movement.
  [ ] Motion looks deliberate, not twitchy. If it jitters, lengthen the `hold`
      values in expression.GESTURES rather than lowering the speeds.
  [ ] Nothing buzzes after the program exits (motors detached cleanly).

If any mechanical check fails, fix that first -- perceptual problems usually
follow from a mechanical one rather than from the pose design.
"""


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--robot", action="store_true", help="also run on-hardware checks")
    p.add_argument("--model", default=None)
    args = p.parse_args()

    import config as config_mod

    cfg = config_mod.load(warn=False)
    model = args.model or cfg.get("llm.model", llm.DEFAULT_MODEL)
    host = cfg.get("llm.host", llm.HOST)

    print("Empathy layer check -- model: {}".format(model))
    print("  {} emotions, {} gestures".format(
        len(expression.EMOTIONS), len(expression.GESTURE_NAMES)))

    try:
        llm.check_model(model, host)
    except llm.OllamaError as e:
        print(e, file=sys.stderr)
        return 1

    sem = semantic_check(model, host)
    mech = mechanical_check() if args.robot else None

    print(CHECKLIST)

    print("=" * 60)
    failed = []
    if sem is None or sem["accuracy"] < 0.75:
        failed.append("emotion accuracy below 75%")
    if sem and sem["invalid"]:
        failed.append("schema not binding -- values outside the enum")
    if mech and not mech["concurrent"]:
        failed.append("gestures not overlapping speech")
    if sem and sem["tone_misses"]:
        failed.append("{} gesture(s) with the wrong tone".format(len(sem["tone_misses"])))

    if failed:
        print("PROBLEMS:")
        for f in failed:
            print("  - {}".format(f))
        return 1
    print("Measurable checks pass. Now do the perceptual checklist above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
