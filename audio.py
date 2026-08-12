"""Audio device selection for Ohbot.

Two jobs: resolve a device name to a PortAudio index, and route the robot's
speech to a chosen output device.

WHY OUTPUT NEEDS A MONKEYPATCH:

ohbot._playSpeech() calls playsound(speechFile) from playsound3, which always
uses the system default output -- there is no device argument. So choosing an
output device means replacing _playSpeech, the same way tts.py replaces
_generateSpeechFile. This is safe because say() launches it as
threading.Thread(target=_playSpeech, ...), resolving the module global at call
time, so rebinding the attribute takes effect.

Input needs none of this: voice.Listener already passes a device through to
sd.InputStream. It has simply never been set.

WHY MATCHING IS DIRECTION-AWARE:

A headset appears TWICE in the device list under an identical name -- once with
input channels, once with output channels. Matching on name alone picks the
wrong one half the time, so candidates are filtered by direction first.

Names are used rather than indices because indices shift when devices are
plugged or unplugged, leaving a saved index silently pointing at the wrong
hardware.
"""

import wave

import numpy as np
import sounddevice as sd

from ohbot import ohbot

INPUT = "input"
OUTPUT = "output"


class DeviceNotFound(RuntimeError):
    """Raised when a configured device name matches nothing."""


def devices(kind):
    """(index, info) pairs for devices usable in the given direction."""
    key = "max_input_channels" if kind == INPUT else "max_output_channels"
    return [(i, d) for i, d in enumerate(sd.query_devices()) if d[key] > 0]


def describe():
    """Human-readable listing of inputs and outputs, for --list-devices."""
    lines = []
    for kind in (INPUT, OUTPUT):
        lines.append("{}s:".format(kind.capitalize()))
        default = sd.default.device[0 if kind == INPUT else 1]
        for i, d in devices(kind):
            mark = "  <- system default" if i == default else ""
            lines.append("  [{}] {}{}".format(i, d["name"], mark))
    return "\n".join(lines)


def resolve(name, kind):
    """Map a device name substring to an index.

    None or empty means "use the system default", signalled by returning None.
    """
    if not name:
        return None

    candidates = devices(kind)
    needle = str(name).lower()

    for i, d in candidates:
        if needle in d["name"].lower():
            return i

    raise DeviceNotFound(
        "No {} device matching {!r}.\n{}".format(kind, name, describe())
    )


def device_name(index):
    """Name for an index, or 'system default' for None."""
    if index is None:
        return "system default"
    return sd.query_devices(index)["name"]


_ORIGINAL_PLAY = ohbot._playSpeech


def install_output(device):
    """Route ohbot speech playback to a specific output device.

    Passing None restores the default playsound path.
    """
    if device is None:
        ohbot._playSpeech = _ORIGINAL_PLAY
        return

    def _play(addSilence):
        try:
            with wave.open(ohbot.speechAudioFile, "rb") as w:
                rate = w.getframerate()
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
                channels = w.getnchannels()
            if channels > 1:
                pcm = pcm.reshape(-1, channels)

            sd.play(pcm, rate, device=device)
            sd.wait()
        except Exception as e:
            # A USB headset need not support Kokoro's 24 kHz. Losing device
            # routing is much better than losing audio, so fall back.
            print("[audio] playback on device {} failed ({}), "
                  "using system default".format(device, e))
            _ORIGINAL_PLAY(addSilence)

    ohbot._playSpeech = _play


if __name__ == "__main__":
    import sys

    print(describe())
    if len(sys.argv) > 1:
        name = sys.argv[1]
        print()
        for kind in (INPUT, OUTPUT):
            try:
                idx = resolve(name, kind)
                print("{!r} as {}: [{}] {}".format(name, kind, idx, device_name(idx)))
            except DeviceNotFound as e:
                print("{!r} as {}: {}".format(name, kind, e.args[0].splitlines()[0]))
