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

    def test_keep_one_complete_round(self):
        engine = self._make_engine()
        engine.configure({"strategy_config": {"keep_rounds": 1}})
        msgs = _make_messages(n_tool_rounds=4)
        result = engine.compress(msgs)
        # 4 rounds, keep the last complete assistant/tool round
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"
        assert any(m.get("role") == "assistant" for m in result[2:])

    def test_env_overrides_keep_rounds(self, monkeypatch):
        # Env var should beat config value.
        monkeypatch.setenv("HERMES_DISCARD_KEEP_ROUNDS", "0")
        engine = self._make_engine()
        engine.configure({"strategy_config": {"keep_rounds": 5}})
        assert engine._keep_rounds == 0
        msgs = _make_messages(n_tool_rounds=3)
        result = engine.compress(msgs)
        # keep_rounds=0 -> system + original task, no replacement memory.
        assert [m["role"] for m in result] == ["system", "user"]
        assert not any(m.get("role") in ("assistant", "tool") for m in result)

    def test_env_invalid_falls_back_to_config(self, monkeypatch):
        monkeypatch.setenv("HERMES_DISCARD_KEEP_ROUNDS", "not-an-int")
        engine = self._make_engine()
        engine.configure({"strategy_config": {"keep_rounds": 3}})
        assert engine._keep_rounds == 3


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

    def test_max_compressions_stops_compression(self):
        engine = self._make_engine()
        engine.max_compressions = 10
        engine.compression_count = 10
        engine.last_prompt_tokens = engine.threshold_tokens
        msgs = _make_messages(n_tool_rounds=5)

        assert engine.should_compress() is False
        assert engine.compress(msgs) is msgs


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

    def test_compression_stats_tracked(self):
        engine = self._make_engine()
        msgs = _make_messages(n_tool_rounds=5)
        engine.compress(msgs)
        stats = engine._compression_stats
        assert stats["compressions"] == 1
        assert stats["total_text_tokens"] > 0
        assert stats["total_image_tokens"] > 0
        assert stats["total_token_savings"] >= 0
        assert len(stats["per_compression"]) == 1
        entry = stats["per_compression"][0]
        assert entry["index"] == 1
        assert entry["text_tokens"] > 0
        assert entry["image_count"] >= 1

    def test_skips_when_too_few_rounds(self):
        engine = self._make_engine()
        engine.configure({"strategy_config": {"keep_rounds": 5}})
        msgs = _make_messages(n_tool_rounds=2)
        result = engine.compress(msgs)
        assert result is msgs

    def test_env_layout_override(self, monkeypatch):
        monkeypatch.setenv("HERMES_VISUAL_LAYOUT", "plain_no_header")
        engine = self._make_engine()
        engine.configure({"strategy_config": {}})
        assert engine._layout == "plain_no_header"

    def test_env_layout_override_1d(self, monkeypatch):
        monkeypatch.setenv("HERMES_VISUAL_LAYOUT", "highlight_no_wrap")
        engine = self._make_engine()
        engine.configure({"strategy_config": {"layout": "highlight"}})
        assert engine._layout == "highlight_no_wrap"

    def test_env_layout_invalid_ignored(self, monkeypatch):
        monkeypatch.setenv("HERMES_VISUAL_LAYOUT", "invalid_mode")
        engine = self._make_engine()
        engine.configure({"strategy_config": {"layout": "highlight"}})
        assert engine._layout == "highlight"

    def test_env_history_scale_override(self, monkeypatch):
        monkeypatch.setenv("HERMES_VISUAL_HISTORY_SCALE", "0.25")
        engine = self._make_engine()
        engine.configure({"strategy_config": {"history_scale": 0.75}})
        assert engine._history_scale == 0.25

    def test_env_history_scale_zero_no_history(self, monkeypatch):
        monkeypatch.setenv("HERMES_VISUAL_HISTORY_SCALE", "0")
        engine = self._make_engine()
        engine.configure({"strategy_config": {}})
        assert engine._history_scale == 0.0
        msgs = _make_messages(n_tool_rounds=10)
        result = engine.compress(msgs)
        # With scale=0, history image should not be present (only recent)
        for m in result:
            content = m.get("content")
            if isinstance(content, list):
                texts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                assert not any("lower resolution" in t for t in texts)

    def test_layout_config_default_highlight(self):
        engine = self._make_engine()
        engine.configure({"strategy_config": {}})
        assert engine._layout == "highlight"

    def test_env_max_history_rounds(self, monkeypatch):
        monkeypatch.setenv("HERMES_VISUAL_MAX_HISTORY_ROUNDS", "3")
        engine = self._make_engine()
        engine.configure({"strategy_config": {}})
        assert engine._max_history_rounds == 3

    def test_env_history_max_image_height(self, monkeypatch):
        monkeypatch.setenv("HERMES_VISUAL_HISTORY_MAX_IMAGE_HEIGHT", "8192")
        engine = self._make_engine()
        engine.configure({"strategy_config": {}})
        assert engine._history_max_image_height == 8192

    def test_max_history_rounds_truncates(self):
        engine = self._make_engine()
        engine.configure({"strategy_config": {"max_history_rounds": 3}})
        # Compress with many rounds — history should be bounded
        msgs = _make_messages(n_tool_rounds=10)
        engine.compress(msgs)
        # _full_history should have at most 3 rounds worth of messages
        round_count = sum(
            1 for m in engine._full_history
            if m.get("role") == "assistant" and m.get("tool_calls")
        )
        assert round_count <= 3

    def test_history_pages_are_not_merged_before_model(self, monkeypatch, tmp_path):
        from plugins.context_engine.visual import render as visual_render

        one_pixel_png = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0l"
            "EQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
        )

        render_sizes = []

        def fake_blocks_to_pdf_bytes(*args, **kwargs):
            render_sizes.append((args[3], args[4]))
            return b"%PDF"

        def fake_pdf_to_images(pdf_bytes, dpi=72, save_dir=None, save_prefix="page"):
            if "history" in save_prefix:
                return [one_pixel_png, one_pixel_png]
            return [one_pixel_png]

        merge_calls = []

        def fake_merge_images_vertical(images):
            merge_calls.append(len(images))
            return one_pixel_png

        monkeypatch.setattr(visual_render, "_blocks_to_pdf_bytes", fake_blocks_to_pdf_bytes)
        monkeypatch.setattr(visual_render, "_pdf_bytes_to_image_b64_list", fake_pdf_to_images)
        monkeypatch.setattr(visual_render, "_merge_images_vertical", fake_merge_images_vertical)
        monkeypatch.setattr(visual_render, "_downscale_image_b64", lambda b64, scale=0.5: b64)
        monkeypatch.setattr(visual_render, "_concat_pdf_bytes", lambda pdfs: b"%PDF")

        result = visual_render.render_visual_compression(
            _make_messages(n_tool_rounds=8),
            head_end=0,
            history_scale=0.5,
            keep_rounds=0,
            recent_rounds=1,
            save_dir=str(tmp_path),
            history_max_image_height=6144,
        )

        content = next(m["content"] for m in result if isinstance(m.get("content"), list))
        image_parts = [
            p for p in content
            if isinstance(p, dict) and p.get("type") == "image_url"
        ]
        low_images = [
            p for p in image_parts
            if p.get("image_url", {}).get("detail") == "low"
        ]
        assert len(low_images) == 2
        assert len(image_parts) == 3
        assert merge_calls == []
        assert render_sizes == [(1024, 4096), (2048, 12288)]
        assert (tmp_path / "old_1_001.png").exists()
        assert (tmp_path / "old_1_002.png").exists()

    def test_recent_segment_renders_as_single_source_page(self, monkeypatch, tmp_path):
        from plugins.context_engine.visual import render as visual_render

        one_pixel_png = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0l"
            "EQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
        )

        render_calls = []

        def fake_blocks_to_pdf_bytes(*args, **kwargs):
            render_calls.append({
                "width": args[3],
                "height": args[4],
                "fit_to_content_height": kwargs.get("fit_to_content_height"),
            })
            return b"%PDF"

        monkeypatch.setattr(visual_render, "_blocks_to_pdf_bytes", fake_blocks_to_pdf_bytes)
        monkeypatch.setattr(visual_render, "_pdf_bytes_to_image_b64_list", lambda *a, **k: [one_pixel_png])
        monkeypatch.setattr(visual_render, "_downscale_image_b64", lambda b64, scale=0.5: b64)
        monkeypatch.setattr(visual_render, "_concat_pdf_bytes", lambda pdfs: b"%PDF")

        visual_render.render_visual_compression(
            _make_messages(n_tool_rounds=5),
            head_end=0,
            history_scale=0,
            keep_rounds=0,
            recent_rounds=5,
            save_dir=str(tmp_path),
            max_image_height=4096,
        )

        assert render_calls == [{
            "width": 1024,
            "height": 20480,
            "fit_to_content_height": True,
        }]


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
