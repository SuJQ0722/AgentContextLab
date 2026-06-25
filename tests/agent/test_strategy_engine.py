"""Tests for the context engine plugins (summarize, sliding_window, discard, visual)."""

import os
import pytest
from typing import Any, Dict, List

from agent.context_engine import ContextEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_messages(n_tool_rounds: int = 5, extra_content: str = "x" * 200) -> List[Dict[str, Any]]:
    """Build a realistic message list with system + user + N tool-call rounds."""
    msgs = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Help me research topic X"},
        {"role": "assistant", "content": "Let me help you with that."},
        {"role": "user", "content": "Yes please search for it"},
    ]
    for i in range(n_tool_rounds):
        msgs.append({
            "role": "assistant",
            "content": f"Searching round {i}",
            "tool_calls": [{
                "id": f"call_{i}",
                "function": {"name": "web_search", "arguments": f'{{"query": "topic X part {i}"}}'},
            }],
        })
        msgs.append({
            "role": "tool",
            "tool_call_id": f"call_{i}",
            "content": f"Search results for round {i}: {extra_content}",
        })
    msgs.append({"role": "user", "content": "What did you find?"})
    return msgs


# ---------------------------------------------------------------------------
# Test SlidingWindowEngine
# ---------------------------------------------------------------------------

class TestSlidingWindow:
    def _make_engine(self):
        from plugins.context_engine.sliding_window import SlidingWindowEngine
        engine = SlidingWindowEngine()
        engine.update_model("test", context_length=200000)
        return engine

    def test_is_context_engine(self):
        engine = self._make_engine()
        assert isinstance(engine, ContextEngine)
        assert engine.name == "sliding_window"

    def test_threshold_32k(self):
        engine = self._make_engine()
        assert engine.threshold_tokens == 32768

    def test_should_compress(self):
        engine = self._make_engine()
        engine.update_from_response({"prompt_tokens": 1000})
        assert not engine.should_compress()
        engine.update_from_response({"prompt_tokens": 35000})
        assert engine.should_compress()

    def test_compress_blanks_old_tool_results(self):
        engine = self._make_engine()
        engine.configure({"strategy_config": {"window_size": 2}})
        msgs = _make_messages(n_tool_rounds=5)
        result = engine.compress(msgs)
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        blanked = [m for m in tool_msgs if m["content"] == "[tool response omitted]"]
        kept = [m for m in tool_msgs if m["content"] != "[tool response omitted]"]
        assert len(blanked) >= 2
        assert len(kept) == 2

    def test_no_compress_when_fewer_than_window(self):
        engine = self._make_engine()
        engine.configure({"strategy_config": {"window_size": 10}})
        msgs = _make_messages(n_tool_rounds=3)
        result = engine.compress(msgs)
        assert result is msgs

    def test_session_reset(self):
        engine = self._make_engine()
        engine.compression_count = 5
        engine.on_session_reset()
        assert engine.compression_count == 0


# ---------------------------------------------------------------------------
# Test DiscardEngine
# ---------------------------------------------------------------------------

class TestDiscard:
    def _make_engine(self):
        from plugins.context_engine.discard import DiscardEngine
        engine = DiscardEngine()
        engine.update_model("test", context_length=200000)
        return engine

    def test_is_context_engine(self):
        engine = self._make_engine()
        assert isinstance(engine, ContextEngine)
        assert engine.name == "discard"

    def test_discard_all_rounds(self):
        engine = self._make_engine()
        msgs = _make_messages(n_tool_rounds=3)
        result = engine.compress(msgs)
        # Should keep: system + first user only (all rounds discarded)
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 0

    def test_discard_75_percent(self):
        engine = self._make_engine()
        engine.configure({"strategy_config": {"discard_ratio": 0.75}})
        msgs = _make_messages(n_tool_rounds=4)
        result = engine.compress(msgs)
        # 4 rounds, discard 75% = 3 rounds discarded, 1 kept
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"
        assert any(m.get("role") == "assistant" for m in result[2:])


# ---------------------------------------------------------------------------
# Test SummarizeEngine (mocked LLM)
# ---------------------------------------------------------------------------

class TestSummarize:
    def _make_engine(self):
        from plugins.context_engine.summarize import SummarizeEngine
        engine = SummarizeEngine()
        engine.update_model("test", context_length=200000, base_url="http://test", api_key="sk-test")
        return engine

    def test_is_context_engine(self):
        engine = self._make_engine()
        assert isinstance(engine, ContextEngine)
        assert engine.name == "summarize"

    def test_compress_with_mocked_llm(self, monkeypatch):
        engine = self._make_engine()
        msgs = _make_messages(n_tool_rounds=5)

        class FakeChoice:
            class message:
                content = "## Active Task\nResearch topic X\n## Goal\nFind info"

        class FakeResponse:
            choices = [FakeChoice()]

        monkeypatch.setattr(
            "agent.auxiliary_client.call_llm",
            lambda **kwargs: FakeResponse(),
        )

        result = engine.compress(msgs)
        assert len(result) < len(msgs)
        all_content = " ".join(str(m.get("content", "")) for m in result)
        assert "CONTEXT COMPACTION" in all_content

    def test_compress_fallback_on_failure(self, monkeypatch):
        engine = self._make_engine()
        msgs = _make_messages(n_tool_rounds=5)

        monkeypatch.setattr(
            "agent.auxiliary_client.call_llm",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("API error")),
        )

        result = engine.compress(msgs)
        assert len(result) < len(msgs)
        all_content = " ".join(str(m.get("content", "")) for m in result)
        assert "unavailable" in all_content.lower()

    def test_session_reset_clears_summary(self):
        engine = self._make_engine()
        engine._previous_summary = "old summary"
        engine.compression_count = 3
        engine.on_session_reset()
        assert engine._previous_summary is None
        assert engine.compression_count == 0


# ---------------------------------------------------------------------------
# Test VisualEngine
# ---------------------------------------------------------------------------

class TestVisual:
    def _make_engine(self):
        from plugins.context_engine.visual import VisualEngine
        engine = VisualEngine()
        engine.update_model("test", context_length=200000)
        return engine

    def test_is_context_engine(self):
        engine = self._make_engine()
        assert isinstance(engine, ContextEngine)
        assert engine.name == "visual"

    def test_compress_produces_images(self):
        engine = self._make_engine()
        msgs = _make_messages(n_tool_rounds=5)
        result = engine.compress(msgs)
        # Should have at least one multimodal message with image_url
        has_image = any(
            isinstance(m.get("content"), list) and
            any(p.get("type") == "image_url" for p in m["content"] if isinstance(p, dict))
            for m in result
        )
        assert has_image
        assert len(result) < len(msgs)

    def test_skips_when_too_few_rounds(self):
        engine = self._make_engine()
        engine.configure({"strategy_config": {"keep_rounds": 5}})
        msgs = _make_messages(n_tool_rounds=2)
        result = engine.compress(msgs)
        assert result is msgs


# ---------------------------------------------------------------------------
# Test plugin discovery
# ---------------------------------------------------------------------------

class TestPluginDiscovery:
    def test_discover_all_engines(self):
        from plugins.context_engine import discover_context_engines
        available = discover_context_engines()
        names = [name for name, _, _ in available]
        assert "summarize" in names
        assert "sliding_window" in names
        assert "discard" in names
        assert "visual" in names

    def test_load_each_engine(self):
        from plugins.context_engine import load_context_engine
        for name in ["summarize", "sliding_window", "discard", "visual"]:
            engine = load_context_engine(name)
            assert engine is not None
            assert engine.name == name
