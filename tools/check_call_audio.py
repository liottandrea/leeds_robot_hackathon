"""Check the virtual audio cables before you join the call.

    python tools/check_call_audio.py
    python tools/check_call_audio.py --seconds 8     # longer listen

Virtual audio routing fails silently and looks exactly like a broken robot: no
error anywhere, the meeting just goes quiet. This proves each half separately,
so you find out at your desk instead of in front of the call.

What it checks:

  * the devices named in config resolve to real hardware
  * a virtual cable (BlackHole / VB-CABLE) is actually installed
  * the input device's channel count matches what config will read
  * audio genuinely arrives on the input device -- the half that carries the
    call into Ohbot's ears
  * Ohbot's output does NOT loop straight back into its own ears

Exits non-zero if anything critical failed. Setup instructions: docs/TEAMS.md
"""

import argparse
import sys
import time

import _bootstrap  # noqa: F401
import numpy as np
import sounddevice as sd

from ohbot_kit import audio
from ohbot_kit import config as config_mod

CRITICAL = "critical"
WARNING = "warning"

# Same floor voice.py uses for "louder than a quiet room". Copied rather than
# imported, because importing voice loads the whole speech model stack.
FLOOR = 0.004

# Substrings that mean "this is a virtual cable, not real hardware".
VIRTUAL = (
    "blackhole",
    "vb-audio",
    "vb-cable",
    "cable input",
    "cable output",
    "loopback",
    "soundflower",
    "voicemeeter",
)

TONE_HZ = 440.0
TONE_SECONDS = 1.0
TONE_LEVEL = 0.2

results = []


def report(name, ok, detail="", level=CRITICAL):
    if ok:
        mark = "PASS"
    elif level == WARNING:
        mark = "WARN"
    else:
        mark = "FAIL"
    print(f"  [{mark}] {name}")
    if detail:
        for line in str(detail).strip().splitlines():
            print(f"         {line}")
    results.append((name, ok, level))
    return ok


def section(title):
    print(f"\n{title}")


def rms(block):
    return float(np.sqrt(np.mean(np.square(block)))) if len(block) else 0.0


def mono(block):
    return block[:, 0] if block.shape[1] == 1 else block.mean(axis=1)


# -- checks ---------------------------------------------------------------


def resolve_devices(cfg):
    """Turn the configured names into indices. Returns (in_idx, out_idx)."""
    section("Devices")
    found = {}
    for key, kind in (("audio.input_device", audio.INPUT), ("audio.output_device", audio.OUTPUT)):
        name = cfg.get(key)
        try:
            index = audio.resolve(name, kind)
            found[kind] = index
            report(
                "{} = {}".format(key.split(".")[-1], audio.device_name(index)),
                True,
                "" if name else "config says null, so using the system default",
            )
        except audio.DeviceNotFound:
            found[kind] = None
            report(
                "{} = {!r}".format(key.split(".")[-1], name),
                False,
                f"No {kind} device matches that name. Is BlackHole installed, and did "
                "you restart\nafter installing it? Full list: "
                "python -m ohbot_kit.audio",
            )
    return found.get(audio.INPUT), found.get(audio.OUTPUT)


def check_virtual_installed():
    section("Virtual cable")
    names = [d["name"].lower() for d in sd.query_devices()]
    present = sorted(
        {d["name"] for d in sd.query_devices() if any(v in d["name"].lower() for v in VIRTUAL)}
    )
    return report(
        "a virtual audio device exists",
        bool(present),
        "\n".join(present)
        if present
        else f"None found among {len(names)} devices.\n"
        "macOS:   brew install blackhole-2ch blackhole-16ch, then log out and in\n"
        "Windows: install VB-CABLE, then reboot\n"
        "Then build the Multi-Output devices described in docs/TEAMS.md",
    )


def check_input_shape(cfg, in_idx):
    """The two settings that silently drop half the conversation."""
    section("Input format")
    if in_idx is None and cfg.get("audio.input_device"):
        return
    info = sd.query_devices(in_idx if in_idx is not None else sd.default.device[0])
    device_channels = int(info["max_input_channels"])
    device_rate = int(info["default_samplerate"])

    configured = cfg.get("speech_to_text.channels", "all")
    reads_all = configured in (None, "all", "auto")
    effective = device_channels if reads_all else max(1, int(configured))

    report(
        f"channels: device has {device_channels}, will read {effective}",
        effective >= device_channels,
        ""
        if effective >= device_channels
        else f"The device carries {device_channels} channels but only {effective} will be read, so whatever is on\n"
        "the others is dropped without an error. On an Aggregate Device -- "
        '"BlackHole +\nbuilt-in mic", how Ohbot hears the call AND you -- that '
        'loses one of the two.\nFix: set speech_to_text.channels to "all" in '
        "config.local.yaml.",
        level=WARNING,
    )

    rate_setting = cfg.get("speech_to_text.capture_rate", "device")
    follows_device = rate_setting in ("device", "auto")
    report(
        f"sample rate: device runs at {device_rate} Hz",
        follows_device or device_rate == 16000,
        ""
        if follows_device or device_rate == 16000
        else f"Whisper wants 16000 Hz and capture_rate is pinned to {rate_setting!r}. Asking CoreAudio\n"
        "for 16 kHz can renegotiate this device down to 16 kHz, which breaks every\n"
        "Multi-Output or Aggregate Device it belongs to -- their members must agree\n"
        "on a rate. Fix: speech_to_text.capture_rate: device",
        level=WARNING,
    )
    return device_rate


def check_audio_arrives(in_idx, seconds):
    """Is the call actually reaching Ohbot's ears?"""
    section("Audio arriving on the input device")
    info = sd.query_devices(in_idx if in_idx is not None else sd.default.device[0])
    channels = max(1, int(info["max_input_channels"]))
    rate = int(info["default_samplerate"])

    print("         Make noise on that device now -- have someone on the call talk,")
    print("         or play a video with Teams' speaker set to the Multi-Output.")
    if sys.stdin.isatty():
        try:
            input("         Press Enter when ready (Ctrl-C to skip)... ")
        except (KeyboardInterrupt, EOFError):
            print()
            return report("audio arrives", False, "skipped", level=WARNING)

    peak = 0.0
    per_channel = np.zeros(channels)
    try:
        with sd.InputStream(
            samplerate=rate, channels=channels, blocksize=1024, device=in_idx
        ) as stream:
            deadline = time.time() + seconds
            while time.time() < deadline:
                block, _ = stream.read(1024)
                peak = max(peak, rms(mono(block)))
                for c in range(channels):
                    per_channel[c] = max(per_channel[c], rms(block[:, c]))
    except sd.PortAudioError as e:
        return report("audio arrives", False, f"Could not open the device: {e}")

    detail = f"peak level {peak:.5f}"
    if channels > 1:
        detail += "\nper channel: " + ", ".join(f"ch{i} {v:.5f}" for i, v in enumerate(per_channel))
        quiet = [i for i, v in enumerate(per_channel) if v <= FLOOR]
        if quiet and peak > FLOOR:
            detail += (
                f"\nSilent channels: {quiet}. That is expected if they are the other "
                "half of\nan Aggregate Device -- the mic while only the call "
                "is talking."
            )

    return report(
        "audio arrives",
        peak > FLOOR,
        detail
        if peak > FLOOR
        else detail + "\nNothing but digital silence. The cable is not carrying the call.\n"
        "Check Teams > Settings > Devices: Speaker must be the Multi-Output that\n"
        "contains BlackHole, and this input must be that same BlackHole.",
    )


def check_no_self_hearing(in_idx, out_idx):
    """Ohbot's voice must not come back into Ohbot's ears down a cable."""
    section("Self-hearing")
    out_info = sd.query_devices(out_idx if out_idx is not None else sd.default.device[1])
    in_info = sd.query_devices(in_idx if in_idx is not None else sd.default.device[0])
    rate = int(out_info["default_samplerate"])
    channels = max(1, int(in_info["max_input_channels"]))

    print("         Playing a short beep on {}...".format(out_info["name"]))
    tone = (
        TONE_LEVEL * np.sin(2 * np.pi * TONE_HZ * np.arange(int(rate * TONE_SECONDS)) / rate)
    ).astype(np.float32)

    peak = 0.0
    try:
        with sd.InputStream(
            samplerate=int(in_info["default_samplerate"]),
            channels=channels,
            blocksize=1024,
            device=in_idx,
        ) as stream:
            sd.play(tone, rate, device=out_idx)
            deadline = time.time() + TONE_SECONDS + 0.5
            while time.time() < deadline:
                block, _ = stream.read(1024)
                peak = max(peak, rms(mono(block)))
            sd.stop()
    except sd.PortAudioError as e:
        return report(
            "output does not loop into input",
            False,
            f"Could not run the test: {e}",
            level=WARNING,
        )

    return report(
        "output does not loop into input",
        peak <= FLOOR * 2,
        ""
        if peak <= FLOOR * 2
        else f"The beep came back at {peak:.5f}. Two possibilities:\n"
        "  * The robot's output feeds its own input down a virtual cable -- the two\n"
        "    cables are crossed. Fix the routing, or it will answer itself on the call.\n"
        "  * Its ears include the built-in mic and it heard the laptop speakers. That\n"
        "    is fine: audio is discarded while the robot speaks.",
        level=WARNING,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--seconds", type=float, default=6.0, help="how long to listen for incoming audio"
    )
    p.add_argument("--config", default="config.yaml")
    args = p.parse_args()

    cfg = config_mod.load(args.config, warn=False)
    print("Checking call audio. Config: {}".format(", ".join(cfg.sources) or "defaults"))

    in_idx, out_idx = resolve_devices(cfg)
    check_virtual_installed()
    check_input_shape(cfg, in_idx)
    check_audio_arrives(in_idx, args.seconds)
    check_no_self_hearing(in_idx, out_idx)

    failed = [n for n, ok, level in results if not ok and level == CRITICAL]
    warned = [n for n, ok, level in results if not ok and level == WARNING]

    print("\n{}".format("-" * 60))
    if failed:
        print("{} critical problem(s): {}".format(len(failed), ", ".join(failed)))
        print("Setup instructions: docs/TEAMS.md")
        return 1
    if warned:
        print("Usable, with {} warning(s): {}".format(len(warned), ", ".join(warned)))
    else:
        print("Cables look right. Join the call, then:")
    print("    python examples/10_teams_call.py")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
