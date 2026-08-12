"""Robot wrapper: speech, expression, gesture and gaze.

    with Ohbot() as bot:
        bot.express("sympathetic")      # hold a face
        bot.gesture("slow_nod")         # movement that plays under speech
        bot.speak("I'm sorry to hear that.")

TWO RULES THIS FILE ENFORCES

1. Serial writes are locked. ohbot._serwrite has no concurrency guard on macOS,
   and say() drives the lip motor from its own thread. serial_safe wraps it in
   a lock so gestures can run WHILE speaking without corrupting commands.
   That simultaneity is the whole point -- a robot that freezes while talking
   reads as a speaker with a face, not a presence.

2. The mouth belongs to lip sync while speaking. POSES may set TOPLIP and
   BOTTOMLIP, but those values are dropped whenever speech is in progress,
   because the lip-sync thread is already driving them.

Without a robot plugged in, everything here is a safe no-op: the library guards
its writes on `connected`, and say() still plays audio. So you can develop the
whole conversation loop with no hardware.
"""

import random
import threading
import time

import expression as ex
import serial_safe
from expression import GESTURES, MOUTH, POSES, REST
from ohbot import ohbot

# Eye colours as (r, g, b), each 0-10.
COLOURS = {
    "listening": (0, 0, 10),   # blue
    "thinking": (10, 5, 0),    # amber
    "speaking": (0, 10, 3),    # green
    "off": (0, 0, 0),
}


class Ohbot:
    """Context manager wrapping the robot for expressive conversation."""

    def __init__(
        self,
        idle=True,
        colours=None,
        blink_interval=(2, 6),
        drift_interval=(4, 9),
        has_headroll=True,
    ):
        self.colours = dict(COLOURS)
        if colours:
            # YAML gives lists; the ohbot calls want positional r, g, b.
            self.colours.update({k: tuple(v) for k, v in colours.items()})
        self.blink_interval = tuple(blink_interval)
        self.drift_interval = tuple(drift_interval)
        # Not every Ohbot has the head-roll servo fitted. When absent, those
        # keyframes are skipped rather than the gesture failing.
        self.has_headroll = has_headroll

        self.state = "listening"
        self.emotion = "neutral"
        # Set while talking. voice.py reads this so the mic ignores our own
        # speech; the mouth rule below reads it too.
        self.speaking = threading.Event()
        self._listening = threading.Event()
        self._stop = threading.Event()
        self._idle_thread = None
        self._gesture_thread = None
        self._want_idle = idle

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self):
        # Must happen before any thread touches a motor.
        serial_safe.install_write_lock()

        ohbot.reset()
        self.express("neutral")
        self.set_state("listening")

        if self._want_idle:
            self._idle_thread = threading.Thread(target=self._idle_loop, daemon=True)
            self._idle_thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        for t in (self._idle_thread, self._gesture_thread):
            if t is not None:
                t.join(timeout=2)
        try:
            ohbot.setEyeColour(*self.colours["off"])
            ohbot.reset()
        finally:
            ohbot.close()  # detach motors so they stop drawing current
        return False

    # -- speech ------------------------------------------------------------

    def speak(self, text, emotion=None, gesture=None, recentre=True):
        """Say text aloud, optionally with a face and a movement under it.

        The gesture is launched first and plays *during* the speech.

        recentre returns the head and eyes to face the person afterwards.
        Without it, poses that tilt the head for character (`curious` rolls to
        8) leave that tilt in place, and it compounds utterance after utterance
        until the robot is addressing the wall instead of you.
        """
        if not text or not text.strip():
            return

        if emotion:
            self.express(emotion)

        self.speaking.set()
        try:
            self.set_state("speaking")
            if gesture:
                self.gesture(gesture)  # non-blocking: runs beneath the audio
            ohbot.say(text)  # blocks until the audio has finished
        finally:
            self.speaking.clear()
            if recentre:
                # Let the gesture finish first, or we fight it mid-keyframe.
                if self._gesture_thread is not None:
                    self._gesture_thread.join(timeout=2)
                self.recentre()

    def recentre(self, speed=2):
        """Return head and eyes to centre so the robot faces the person again.

        Deliberately slow: a snap back to centre reads as a twitch, while an
        unhurried settle reads as relaxing. The emotional face (lids, pitch)
        is left alone -- only the aiming axes are reset.
        """
        for motor in ex.ORIENTATION:
            self._move(motor, 5, speed)

    # -- expression --------------------------------------------------------

    def express(self, emotion):
        """Hold a facial expression from expression.POSES."""
        pose = POSES.get(emotion)
        if pose is None:
            raise KeyError(
                "Unknown emotion {!r}. Available: {}".format(
                    emotion, ", ".join(sorted(POSES))
                )
            )
        self.emotion = emotion
        for motor, pos in pose.items():
            self._move(motor, pos, 4)

    def gaze(self, x=5, y=5, speed=6):
        """Aim the eyes only. x: 0 right .. 10 left. y: 0 down .. 10 up."""
        for motor, pos in ex.gaze_positions(x, y).items():
            self._move(motor, pos, speed)

    def look_at(self, direction=None, x=5, y=5, with_head=True, blocking=False):
        """Look somewhere with eyes, head turn, head pitch and a little roll.

            bot.look_at("up_left")      # a named direction
            bot.look_at(x=8, y=3)       # or coordinates
            bot.look_at("user")         # back to facing the person

        The eyes move first and the head follows a moment later, covering only
        part of the distance. That lag is what makes it read as a glance; moving
        both together at the same distance looks like a security camera.
        """
        if direction is not None:
            if direction not in ex.LOOK_DIRECTIONS:
                raise KeyError(
                    "Unknown direction {!r}. Available: {}".format(
                        direction, ", ".join(sorted(ex.LOOK_DIRECTIONS))
                    )
                )
            x, y = ex.LOOK_DIRECTIONS[direction]

        eyes, head = ex.look_targets(x, y, with_head=with_head)

        def run():
            for motor, pos in eyes.items():
                self._move(motor, pos, 8)      # eyes snap
            time.sleep(0.12)                   # the lag that sells it
            for motor, pos in head.items():
                self._move(motor, pos, 3)      # head follows, slower

        if blocking:
            run()
        else:
            threading.Thread(target=run, daemon=True).start()

    def gesture(self, name, blocking=False):
        """Play a keyframe sequence from expression.GESTURES.

        Non-blocking by default so it runs underneath speech. Only one gesture
        plays at a time; starting another lets the first finish first.
        """
        frames = GESTURES.get(name)
        if frames is None:
            raise KeyError(
                "Unknown gesture {!r}. Available: {}".format(
                    name, ", ".join(sorted(GESTURES))
                )
            )

        if blocking:
            self._play(frames)
            return

        if self._gesture_thread is not None and self._gesture_thread.is_alive():
            self._gesture_thread.join(timeout=3)
        self._gesture_thread = threading.Thread(
            target=self._play, args=(frames,), daemon=True
        )
        self._gesture_thread.start()

    def _play(self, frames):
        for motor, pos, speed, hold in frames:
            if self._stop.is_set():
                return
            self._move(motor, pos, speed)
            time.sleep(hold)

    def set_state(self, state):
        """Signal listening / thinking / speaking via eye colour."""
        self.state = state
        ohbot.setEyeColour(*self.colours.get(state, self.colours["off"]))

    # -- listening ---------------------------------------------------------

    def listening(self, on=True):
        """Backchannel mode: nod and blink while the USER is talking.

        Looking attentive while being spoken to does more for the illusion of
        presence than anything the robot does on its own turn.
        """
        self.set_state("listening")
        if on:
            self.express("neutral")
            self._listening.set()
        else:
            self._listening.clear()

    # -- sensors -----------------------------------------------------------

    def read_sensor(self, index):
        """Read a sensor, safely.

        The library's readSensor() calls ser.flushInput() with no guard, so it
        raises AttributeError on None when no robot is attached. It also does
        write-then-read, which another thread's write could land in the middle
        of -- so the whole transaction holds the serial lock.
        """
        if not ohbot.connected:
            return 0.0
        # The lock is reentrant, so readSensor's own _serwrite won't deadlock.
        with serial_safe.lock:
            try:
                return ohbot.readSensor(index)
            except Exception:
                return 0.0

    # -- internals ---------------------------------------------------------

    def _move(self, motor, pos, speed=5):
        """Move one motor, honouring the mouth and head-roll rules."""
        if self._stop.is_set():
            return
        # Lip sync owns the mouth while speaking.
        if motor in MOUTH and self.speaking.is_set():
            return
        if motor == ex.HEADROLL and not self.has_headroll:
            return
        ohbot.move(motor, pos, speed)

    def _idle_loop(self):
        """Blink, drift, and backchannel-nod so the robot never looks frozen.

        Unlike the earlier version, this keeps running during speech -- the
        write lock makes that safe.
        """
        next_blink = time.time() + random.uniform(*self.blink_interval)
        next_drift = time.time() + random.uniform(*self.drift_interval)
        next_backchannel = time.time() + random.uniform(2.5, 5.0)

        while not self._stop.is_set():
            time.sleep(0.15)
            now = time.time()

            if now >= next_blink:
                self._play(GESTURES["blink"])
                next_blink = now + random.uniform(*self.blink_interval)

            elif self._listening.is_set() and now >= next_backchannel:
                # A small nod while being spoken to reads as "I'm following".
                self._play(GESTURES["slow_nod"][:2])
                next_backchannel = now + random.uniform(3.0, 6.0)

            elif now >= next_drift and not self.speaking.is_set():
                motor = random.choice([ex.HEADTURN, ex.HEADNOD])
                self._move(motor, random.randint(4, 6), 2)
                next_drift = now + random.uniform(*self.drift_interval)
