"""Robot wrapper for the Ohbot chatbot.

Owns idle motion and eye-colour state signalling so the chat loop stays readable,
and guarantees close() runs so the motors never sit attached and buzzing.

THREAD SAFETY -- the reason this wrapper exists:

The ohbot library's _serwrite() serialises concurrent writes with a `writing`
flag only on Windows and Linux; on macOS there is no guard at all. Meanwhile
say() spawns its own threads to drive the lip motor while audio plays. So any
idle motion running during speech would interleave raw bytes with the lip-sync
stream on an unguarded serial port and corrupt motor commands.

Hence the rule enforced here: the idle thread writes only while `_idle_allowed`
is set, and speak() clears it for the whole duration of say().
"""

import random
import threading
import time

from ohbot import ohbot

# Eye colours as (r, g, b), each 0-10.
COLOURS = {
    "listening": (0, 0, 10),   # blue
    "thinking": (10, 5, 0),    # amber
    "speaking": (0, 10, 3),    # green
    "off": (0, 0, 0),
}

REST = {"headnod": 5, "headturn": 5, "lidblink": 5}


class Ohbot:
    """Context manager wrapping the robot for conversational use."""

    def __init__(self, idle=True, colours=None, blink_interval=(2, 6), drift_interval=(4, 9)):
        self.colours = dict(COLOURS)
        if colours:
            # YAML gives lists; the ohbot calls want positional r, g, b.
            self.colours.update({k: tuple(v) for k, v in colours.items()})
        self.blink_interval = tuple(blink_interval)
        self.drift_interval = tuple(drift_interval)
        self.state = "listening"
        # Set while the robot is talking. voice.py reads this to avoid
        # transcribing the robot's own speech.
        self.speaking = threading.Event()
        self._idle_allowed = threading.Event()
        self._stop = threading.Event()
        self._idle_thread = None
        self._want_idle = idle

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self):
        ohbot.reset()
        for motor, pos in (
            (ohbot.HEADNOD, REST["headnod"]),
            (ohbot.HEADTURN, REST["headturn"]),
            (ohbot.LIDBLINK, REST["lidblink"]),
        ):
            ohbot.move(motor, pos, 3)
        self.set_state("listening")

        if self._want_idle:
            self._idle_allowed.set()
            self._idle_thread = threading.Thread(target=self._idle_loop, daemon=True)
            self._idle_thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        self._idle_allowed.clear()
        if self._idle_thread is not None:
            self._idle_thread.join(timeout=2)
        try:
            ohbot.setEyeColour(*self.colours["off"])
            ohbot.reset()
        finally:
            ohbot.close()  # detach motors so they stop drawing current
        return False

    # -- speech ------------------------------------------------------------

    def speak(self, text):
        """Say text aloud with lip sync, with idle motion suspended throughout."""
        if not text or not text.strip():
            return

        self._idle_allowed.clear()
        self.speaking.set()
        try:
            self.set_state("speaking")
            ohbot.say(text)  # blocks until the audio has finished playing
        finally:
            self.speaking.clear()
            if self._want_idle and not self._stop.is_set():
                self._idle_allowed.set()

    # -- expression --------------------------------------------------------

    def set_state(self, state):
        """Signal listening / thinking / speaking via eye colour."""
        self.state = state
        if self._safe_to_write():
            ohbot.setEyeColour(*self.colours.get(state, self.colours["off"]))

    def _safe_to_write(self):
        """True when no speech is in progress, so serial writes won't interleave."""
        return not self.speaking.is_set()

    # -- idle motion -------------------------------------------------------

    def _idle_loop(self):
        """Blink and drift so the robot looks alive while the LLM is generating.

        Every write is preceded by an _idle_allowed check, because speak() can
        clear it at any moment.
        """
        next_blink = time.time() + random.uniform(*self.blink_interval)
        next_drift = time.time() + random.uniform(*self.drift_interval)
        pulse_up = True

        while not self._stop.is_set():
            time.sleep(0.2)
            if not self._idle_allowed.is_set():
                continue

            now = time.time()

            if now >= next_blink:
                self._blink()
                next_blink = now + random.uniform(*self.blink_interval)

            elif now >= next_drift:
                self._drift()
                next_drift = now + random.uniform(*self.drift_interval)

            elif self.state == "thinking":
                # Gentle brightness pulse so waiting reads as "working".
                r, g, b = self.colours["thinking"]
                scale = 1.0 if pulse_up else 0.4
                self._write(
                    ohbot.setEyeColour,
                    int(r * scale),
                    int(g * scale),
                    int(b * scale),
                )
                pulse_up = not pulse_up

    def _blink(self):
        self._write(ohbot.move, ohbot.LIDBLINK, 0, 10)
        time.sleep(0.12)
        self._write(ohbot.move, ohbot.LIDBLINK, REST["lidblink"], 10)

    def _drift(self):
        motor = random.choice([ohbot.HEADTURN, ohbot.HEADNOD])
        target = random.randint(4, 6)  # small movement around centre
        self._write(ohbot.move, motor, target, 2)

    def _write(self, fn, *args):
        """Perform a robot write only if idle motion is still permitted.

        Re-checking here closes the window between the loop's check and the
        actual write, during which speak() may have started.
        """
        if self._idle_allowed.is_set() and not self._stop.is_set():
            fn(*args)
