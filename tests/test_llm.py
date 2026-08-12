"""LLM client: text sanitising, sentence splitting, and conversation handling.

Everything the robot says passes through sanitise() before it reaches the
speech synthesiser, so a mistake here is heard rather than seen.
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest

from ohbot_kit import llm


class TestSanitise:
    def test_strips_think_blocks(self) -> None:
        """Reasoning models emit <think> blocks. Spoken aloud they are
        gibberish, and they can be longer than the answer."""
        assert llm.sanitise("<think>hmm, let me work this out</think>Hello.") == "Hello."

    def test_strips_unclosed_think_block(self) -> None:
        """A response cut off by num_predict can leave <think> unterminated."""
        assert llm.sanitise("Fine.<think>still thinking and then cut") == "Fine."

    def test_strips_markdown(self) -> None:
        assert "*" not in llm.sanitise("**bold** and `code`")
        assert llm.sanitise("**bold**") == "bold"

    def test_strips_emoji(self) -> None:
        assert llm.sanitise("Hello there 🤖🎉") == "Hello there"

    def test_strips_bullets_and_numbered_markers(self) -> None:
        assert llm.sanitise("- first\n- second") == "first second"
        assert llm.sanitise("Sure! 1. France 2. Spain") == "Sure! France Spain"

    def test_preserves_decimals(self) -> None:
        """REGRESSION: the numbered-list stripper must not eat decimals --
        "3.5 kilograms" spoken as "3 5" is wrong."""
        assert "3.5" in llm.sanitise("It weighs 3.5 kilograms.")

    def test_collapses_whitespace(self) -> None:
        assert llm.sanitise("too    many\n\nspaces") == "too many spaces"

    def test_empty_input(self) -> None:
        assert llm.sanitise("") == ""
        assert llm.sanitise("   ") == ""


class TestSentenceSplitting:
    def split(self, text: str) -> list[str]:
        return llm._SENTENCE_END.split(text)

    def test_splits_on_sentence_ends(self) -> None:
        assert self.split("One. Two! Three?") == ["One.", "Two!", "Three?"]

    def test_does_not_split_decimals(self) -> None:
        """REGRESSION: "3.5 kg" split into "3." and "5 kg", so the robot said
        a fragment and then started a new utterance mid-number."""
        assert self.split("It costs 3.5 pounds. Really.") == ["It costs 3.5 pounds.", "Really."]

    def test_does_not_split_numbered_lists(self) -> None:
        """REGRESSION: "1. France 2. Spain" was treated as sentence ends, so
        the robot said "Sure thing! 1. France - Paris 2." and stopped.

        "Sure!" is a real sentence end, so two parts is correct -- what matters
        is that the list markers stay inside one of them rather than each
        starting a new utterance.
        """
        parts = self.split("Sure! 1. France 2. Spain")
        assert parts == ["Sure!", "1. France 2. Spain"]


def _stream_response(chunks: list[str]) -> mock.Mock:
    """Fake a streaming Ollama response."""
    lines = [json.dumps({"message": {"content": c}, "done": False}).encode() for c in chunks]
    lines.append(json.dumps({"message": {"content": ""}, "done": True}).encode())
    response = mock.Mock()
    response.iter_lines.return_value = lines
    response.raise_for_status.return_value = None
    response.__enter__ = mock.Mock(return_value=response)
    response.__exit__ = mock.Mock(return_value=False)
    return response


class TestStreamSentences:
    def test_yields_complete_sentences(self) -> None:
        convo = llm.Conversation()
        with mock.patch.object(
            llm.requests,
            "post",
            return_value=_stream_response(["Hello", " there.", " How are", " you?"]),
        ):
            assert list(convo.stream_sentences("hi")) == ["Hello there.", "How are you?"]

    def test_caps_sentences(self) -> None:
        """Small models ignore "be brief", so the cap is enforced in code.
        Without it the robot monologues and cannot be interrupted."""
        convo = llm.Conversation()
        with mock.patch.object(
            llm.requests,
            "post",
            return_value=_stream_response(["One. ", "Two. ", "Three. ", "Four. ", "Five."]),
        ):
            assert len(list(convo.stream_sentences("hi", max_sentences=2))) == 2

    def test_history_records_only_what_was_spoken(self) -> None:
        """Truncated sentences must not enter history, or a follow-up question
        about "that" refers to words the listener never heard."""
        convo = llm.Conversation()
        with mock.patch.object(
            llm.requests,
            "post",
            return_value=_stream_response(["One. ", "Two. ", "Three. ", "Four."]),
        ):
            spoken = list(convo.stream_sentences("hi", max_sentences=2))
        assert convo.messages[-1]["content"] == " ".join(spoken)

    def test_empty_reply_does_not_poison_history(self) -> None:
        """An empty response must leave the history clean, or every later turn
        carries a dangling user message with no answer."""
        convo = llm.Conversation()
        with mock.patch.object(llm.requests, "post", return_value=_stream_response([""])):
            assert list(convo.stream_sentences("hi")) == []
        assert convo.messages == []

    def test_reset_clears_history(self) -> None:
        convo = llm.Conversation()
        convo.messages = [{"role": "user", "content": "x"}]
        convo.reset()
        assert convo.messages == []


class TestRespondWithAction:
    def _action_response(self, payload: dict[str, Any]) -> mock.Mock:
        response = mock.Mock()
        response.json.return_value = {"message": {"content": json.dumps(payload)}}
        response.raise_for_status.return_value = None
        return response

    def test_returns_parsed_action(self) -> None:
        convo = llm.Conversation()
        payload = {"say": "I'm sorry.", "emotion": "sad", "gesture": "slow_nod"}
        with mock.patch.object(llm.requests, "post", return_value=self._action_response(payload)):
            action = convo.respond_with_action("bad news", ["sad", "happy"], ["slow_nod"])
        assert action["emotion"] == "sad"
        assert action["say"] == "I'm sorry."

    def test_uses_schema_not_tools(self) -> None:
        """REGRESSION: phi4-mini advertises a `tools` capability but returned
        tool_calls: None on every attempt and refused. The schema in `format`
        is what actually works, so a switch back to tools must fail loudly."""
        convo = llm.Conversation()
        payload = {"say": "hi", "emotion": "happy", "gesture": "nod"}
        with mock.patch.object(
            llm.requests, "post", return_value=self._action_response(payload)
        ) as post:
            convo.respond_with_action("hi", ["happy"], ["nod"])
        body = post.call_args.kwargs["json"]
        assert "format" in body, "structured output must use the `format` schema"
        assert "tools" not in body
        assert body["format"]["properties"]["emotion"]["enum"] == ["happy"]

    def test_action_temperature_is_cooler_than_chat(self) -> None:
        """Emotion choice is a classification, not a creative act. At 0.7 the
        same cases scored 12/12 on one run and 10/12 on the next."""
        convo = llm.Conversation(temperature=0.7)
        payload = {"say": "hi", "emotion": "happy", "gesture": "nod"}
        with mock.patch.object(
            llm.requests, "post", return_value=self._action_response(payload)
        ) as post:
            convo.respond_with_action("hi", ["happy"], ["nod"])
        assert post.call_args.kwargs["json"]["options"]["temperature"] < 0.7

    def test_bad_json_raises_ollama_error(self) -> None:
        convo = llm.Conversation()
        response = mock.Mock()
        response.json.return_value = {"message": {"content": "not json at all"}}
        response.raise_for_status.return_value = None
        with (
            mock.patch.object(llm.requests, "post", return_value=response),
            pytest.raises(llm.OllamaError),
        ):
            convo.respond_with_action("hi", ["happy"], ["nod"])
        assert convo.messages == []  # history not left dangling


class TestModelChecks:
    def test_unreachable_ollama_names_the_fix(self) -> None:
        import requests as real_requests

        with (
            mock.patch.object(
                llm.requests, "get", side_effect=real_requests.RequestException("refused")
            ),
            pytest.raises(llm.OllamaError, match="ollama serve"),
        ):
            llm.list_models()

    def test_missing_model_lists_what_is_installed(self) -> None:
        with mock.patch.object(llm, "list_models", return_value=["phi4-mini:latest"]):
            llm.check_model("phi4-mini")  # bare name matches the :latest tag
            with pytest.raises(llm.OllamaError, match="phi4-mini:latest"):
                llm.check_model("nonexistent")
