"""Microphone input for the Ohbot chatbot, transcribed locally with Whisper.

Records from the default input device, detects the end of an utterance by
silence, and transcribes with faster-whisper. Nothing leaves the machine.

Only imported when --voice is passed, since the model and its dependencies are
heavy compared with the typed path.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from typing import Any

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000
BLOCK = 1024  # ~64 ms per block
SILENCE_SECONDS = 1.0  # end the utterance after this much quiet
MIN_SPEECH_SECONDS = 0.3  # ignore coughs and door slams
MAX_UTTERANCE_SECONDS = 20  # hard stop so a noisy room can't record forever
CALIBRATION_SECONDS = 1.0
NOISE_MULTIPLIER = 3.0  # speech must be this much louder than the room
FLOOR = 0.004  # absolute minimum, for very quiet rooms

# base.en is ~150 MB and plenty for short spoken commands. Larger models add
# seconds of latency per utterance, which matters more here than word accuracy.
MODEL_SIZE = "base.en"

# Biases the decoder toward the robot's name, which it otherwise mishears.
NAME_HINT = "This is a conversation with Ohbot, a small desk robot."

# Whisper reliably hallucinates these when fed near-silence.
HALLUCINATIONS = {
    "you",
    "thank you.",
    "thanks for watching!",
    "bye.",
    ".",
    "",
    "thank you for watching!",
    "you're welcome.",
}


class MicrophoneBlocked(RuntimeError):
    """Raised when the OS hands us silence instead of microphone audio."""


def _rms(block: Any) -> float:
    return float(np.sqrt(np.mean(np.square(block))))


class Listener:
    """Captures utterances from the microphone and transcribes them."""

    def __init__(
        self,
        device: int | None = None,
        model_size: str = MODEL_SIZE,
        silence_seconds: float = SILENCE_SECONDS,
        min_speech_seconds: float = MIN_SPEECH_SECONDS,
        noise_multiplier: float = NOISE_MULTIPLIER,
    ) -> None:
        print(f"Loading speech model ({model_size})...", flush=True)
        # int8 on CPU is the fast path on Apple Silicon.
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.device = device
        self.silence_seconds = silence_seconds
        self.min_speech_seconds = min_speech_seconds
        self.noise_multiplier = noise_multiplier
        self.threshold = FLOOR

    # -- capture -----------------------------------------------------------

    def calibrate(self) -> None:
        """Measure room noise so the threshold suits the actual environment."""
        print("Calibrating microphone, stay quiet...", flush=True)
        levels = []
        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, blocksize=BLOCK, device=self.device
        ) as stream:
            deadline = time.time() + CALIBRATION_SECONDS
            while time.time() < deadline:
                block, _ = stream.read(BLOCK)
                levels.append(_rms(block[:, 0]))

        peak = max(levels) if levels else 0.0
        if peak == 0.0:
            # Digital silence is not a quiet room -- the OS is handing us
            # nothing. Without this check the listener waits forever for a
            # loud block that can never arrive.
            raise MicrophoneBlocked(
                "The microphone returned pure silence.\n"
                "macOS has not granted microphone access to this terminal, "
                "or the input device is muted.\n"
                "Fix: System Settings > Privacy & Security > Microphone, "
                "enable your terminal app, then restart it.\n"
                "Check the input device with: python -c "
                "'import sounddevice; print(sounddevice.query_devices())'"
            )

        baseline = float(np.median(levels))
        self.threshold = max(baseline * self.noise_multiplier, FLOOR)
        print(f"Noise floor {baseline:.5f}, threshold {self.threshold:.5f}")

    def record_utterance(self, bot: Any = None) -> Any:
        """Block until speech is heard, then return audio once it stops.

        Returns a float32 numpy array, or None if interrupted.
        """
        frames: list[Any] = []
        speech_frames = 0
        silence_frames = 0
        started = False

        silence_limit = int(self.silence_seconds * SAMPLE_RATE / BLOCK)
        max_frames = int(MAX_UTTERANCE_SECONDS * SAMPLE_RATE / BLOCK)

        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, blocksize=BLOCK, device=self.device
        ) as stream:
            while True:
                block, overflowed = stream.read(BLOCK)
                if overflowed:
                    continue
                mono = block[:, 0].copy()

                # Never listen while the robot is talking, or it transcribes
                # its own voice and starts a conversation with itself.
                if bot is not None and bot.speaking.is_set():
                    frames, started, speech_frames, silence_frames = [], False, 0, 0
                    continue

                loud = _rms(mono) > self.threshold

                if not started:
                    if loud:
                        started = True
                        frames.append(mono)
                        speech_frames = 1
                    continue

                frames.append(mono)
                if loud:
                    speech_frames += 1
                    silence_frames = 0
                else:
                    silence_frames += 1

                if silence_frames >= silence_limit or len(frames) >= max_frames:
                    break

        if speech_frames * BLOCK / SAMPLE_RATE < self.min_speech_seconds:
            return None
        return np.concatenate(frames)

    # -- transcription -----------------------------------------------------

    def transcribe(self, audio: Any) -> str:
        """Return the transcript of an audio array, or '' if it's not speech."""
        segments, _ = self.model.transcribe(
            audio,
            language="en",
            beam_size=1,  # greedy: faster, ample for short commands
            vad_filter=True,
            condition_on_previous_text=False,  # stops runaway repetition
            # Without this the robot's name comes out as "Bob" or "Odd Bot".
            initial_prompt=NAME_HINT,
        )
        text = " ".join(s.text.strip() for s in segments).strip()

        if text.lower() in HALLUCINATIONS:
            return ""
        return text

    # -- driver ------------------------------------------------------------

    def listen_loop(self, bot: Any = None) -> Iterator[str]:
        """Yield transcripts of spoken utterances, forever."""
        self.calibrate()
        print("Listening. Speak when the eyes are blue. Ctrl-C to stop.\n")

        while True:
            try:
                audio = self.record_utterance(bot)
            except KeyboardInterrupt:
                return
            except sd.PortAudioError as e:
                print(f"[mic error] {e}", file=sys.stderr)
                return

            if audio is None:
                continue

            text = self.transcribe(audio)
            if text:
                yield text


if __name__ == "__main__":
    # Standalone check: transcribe one spoken utterance and print it.
    listener = Listener()
    listener.calibrate()
    print("Say something...")
    audio = listener.record_utterance()
    if audio is None:
        print("Nothing captured.")
    else:
        print(f"Heard: {listener.transcribe(audio)!r}")
