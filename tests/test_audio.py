"""Audio device resolution."""

from __future__ import annotations

import pytest

from ohbot_kit import audio


class TestResolve:
    def test_direction_aware_matching(self) -> None:
        """THE case this exists for: a headset appears twice under one name,
        once as an input and once as an output. Matching on name alone picks
        the wrong one half the time."""
        mic = audio.resolve("Plantronics", audio.INPUT)
        speaker = audio.resolve("Plantronics", audio.OUTPUT)

        assert mic != speaker, "same index returned for both directions"

        input_indexes = [i for i, _ in audio.devices(audio.INPUT)]
        output_indexes = [i for i, _ in audio.devices(audio.OUTPUT)]
        assert mic in input_indexes
        assert speaker in output_indexes

    def test_case_insensitive_substring(self) -> None:
        assert audio.resolve("plantronics", audio.INPUT) == audio.resolve(
            "Plantronics Blackwire", audio.INPUT
        )

    def test_none_means_system_default(self) -> None:
        assert audio.resolve(None, audio.INPUT) is None
        assert audio.resolve("", audio.OUTPUT) is None

    def test_unknown_name_lists_real_devices(self) -> None:
        """The error has to be actionable -- a participant hits this when
        their headset is named differently from a teammate's."""
        with pytest.raises(audio.DeviceNotFound, match="MacBook Pro"):
            audio.resolve("Nonexistent Device", audio.OUTPUT)


class TestDescribe:
    def test_lists_inputs_and_outputs_separately(self) -> None:
        text = audio.describe()
        assert "Inputs:" in text and "Outputs:" in text

    def test_device_name_handles_default(self) -> None:
        assert audio.device_name(None) == "system default"
