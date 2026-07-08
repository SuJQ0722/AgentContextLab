"""Visual context engine — render old messages as PDF/PNG images for VLM.

Produces two-tier compression:
  - far_history: older messages rendered at reduced resolution
  - recent_history: recent messages rendered at full resolution

Threshold: 32k tokens.

Config (context section in config.yaml):
  engine: visual
  strategy_config:
    image_width: 1024
    font_size: 8
    max_image_height: 4096
    dpi: 72
    layout: highlight
    history_scale: 0.75
    keep_rounds: 1
    recent_rounds: 5

Env overrides (take precedence over config):
  HERMES_VISUAL_LAYOUT=1d|plain|highlight
  HERMES_VISUAL_HISTORY_SCALE=0.0-1.0  (0=no history image, 0.5=2x downsample, 0.25=4x, 1.0=original)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from agent.context_engine import ContextEngine
from .render import VISUAL_CONTEXT_PROMPT

logger = logging.getLogger(__name__)

_THRESHOLD_TOKENS = 32768


class VisualEngine(ContextEngine):

    @property
    def name(self) -> str:
        return "visual"

    def __init__(self) -> None:
        self.model = ""
        self.base_url = ""
        self.api_key = ""
        self.provider = ""
        self.api_mode = ""
        self.context_length = 200000
        self.threshold_tokens = _THRESHOLD_TOKENS
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.compression_count = 0

        self._image_width = 1024
        self._font_size = 8
        self._max_image_height = 4096
        self._font_path: Optional[str] = None
        self._dpi = 72
        self._layout = "highlight"
        self._history_scale = 0.75
        self._keep_rounds = 1
        self._recent_rounds = 5
        self._save_dir: Optional[str] = None

        # Accumulated history of all messages that have been compressed.
        # On each compression, new messages (between head and tail) are appended
        # here, then the full history is re-rendered into far + recent images.
        self._full_history: List[Dict[str, Any]] = []

        # Cumulative compression token stats across all compress() calls.
        self._compression_stats: Dict[str, Any] = {
            "compressions": 0,
            "total_text_tokens": 0,
            "total_image_tokens": 0,
            "total_token_savings": 0,
            "per_compression": [],
        }

    def configure(self, ctx_cfg: Dict[str, Any]) -> None:
        sc = ctx_cfg.get("strategy_config") or {}
        self._image_width = int(sc.get("image_width", self._image_width))
        self._font_size = int(sc.get("font_size", self._font_size))
        self._max_image_height = int(sc.get("max_image_height", self._max_image_height))
        self._font_path = sc.get("font_path", self._font_path)
        self._dpi = int(sc.get("dpi", self._dpi))
        self._layout = sc.get("layout", self._layout)
        self._history_scale = float(sc.get("history_scale", self._history_scale))
        self._keep_rounds = int(sc.get("keep_rounds", self._keep_rounds))
        self._recent_rounds = int(sc.get("recent_rounds", self._recent_rounds))
        self._save_dir = sc.get("save_dir", self._save_dir)

        env_layout = os.getenv("HERMES_VISUAL_LAYOUT")
        if env_layout and env_layout.strip():
            val = env_layout.strip().lower()
            if val in ("plain_no_header", "plain", "highlight", "highlight_no_wrap"):
                self._layout = val
            else:
                logger.warning(
                    "Ignoring HERMES_VISUAL_LAYOUT=%r (must be plain_no_header/plain/highlight/highlight_no_wrap)",
                    env_layout,
                )

        env_scale = os.getenv("HERMES_VISUAL_HISTORY_SCALE")
        if env_scale and env_scale.strip():
            try:
                self._history_scale = float(env_scale)
            except ValueError:
                logger.warning(
                    "Ignoring HERMES_VISUAL_HISTORY_SCALE=%r (not a float)",
                    env_scale,
                )

    def update_model(
        self,
        model: str,
        context_length: int,
        base_url: str = "",
        api_key: str = "",
        provider: str = "",
        api_mode: str = "",
    ) -> None:
        self.model = model
        self.context_length = context_length
        self.base_url = base_url
        self.api_key = api_key
        self.provider = provider
        self.api_mode = api_mode
        self.threshold_tokens = _THRESHOLD_TOKENS

    def update_from_response(self, usage: Dict[str, Any]) -> None:
        self.last_prompt_tokens = usage.get("prompt_tokens", 0)
        self.last_completion_tokens = usage.get("completion_tokens", 0)

    def should_compress(self, prompt_tokens: Optional[int] = None) -> bool:
        tokens = prompt_tokens if prompt_tokens is not None else self.last_prompt_tokens
        return tokens >= self.threshold_tokens

    def on_session_reset(self) -> None:
        self.compression_count = 0
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self._full_history = []
        self._compression_stats = {
            "compressions": 0,
            "total_text_tokens": 0,
            "total_image_tokens": 0,
            "total_token_savings": 0,
            "per_compression": [],
        }

    def compress(
        self,
        messages: List[Dict[str, Any]],
        current_tokens: int = None,
        focus_topic: str = None,
    ) -> List[Dict[str, Any]]:
        from .render import render_visual_compression

        if len(messages) < 3:
            return messages

        head_end = self._protect_head_size(messages)

        # Determine which messages to keep as text (tail = last keep_rounds rounds)
        round_starts: List[int] = []
        for i, msg in enumerate(messages):
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                round_starts.append(i)

        if len(round_starts) <= self._keep_rounds:
            return messages

        if self._keep_rounds > 0:
            compact_boundary = round_starts[len(round_starts) - self._keep_rounds]
        else:
            compact_boundary = len(messages)

        # Collect new messages to compress (skip head, skip our own prior visual
        # user message if present — but keep genuine vision input from the user).
        new_msgs = []
        for msg in messages[head_end:compact_boundary]:
            if self._is_self_produced_visual_message(msg):
                continue
            new_msgs.append(msg)

        if not new_msgs and not self._full_history:
            return messages

        # Append new messages to accumulated history
        self._full_history.extend(new_msgs)

        # Render from full accumulated history, collecting per-compression stats
        render_stats: Dict[str, Any] = {}
        result = render_visual_compression(
            self._full_history,
            head_end=0,
            image_width=self._image_width,
            font_size=self._font_size,
            max_image_height=self._max_image_height,
            font_path=self._font_path,
            dpi=self._dpi,
            layout=self._layout,
            history_scale=self._history_scale,
            keep_rounds=0,
            recent_rounds=self._recent_rounds,
            save_dir=self._save_dir,
            compact_count=self.compression_count,
            stats=render_stats,
        )

        if result is self._full_history:
            # Rendering was skipped (not enough rounds) — return original
            return messages

        # result is [image_message(s)] since head_end=0, keep_rounds=0
        # Assemble: head (without old image) + image message + preserved tail
        final = []
        for msg in messages[:head_end]:
            if self._is_self_produced_visual_message(msg):
                continue
            final.append(msg)
        final.extend(result)
        final.extend(messages[compact_boundary:])

        self.compression_count += 1

        # Accumulate compression token stats
        text_tok = render_stats.get("text_tokens_estimate", 0)
        img_tok = render_stats.get("image_tokens_estimate", 0)
        savings = max(0, text_tok - img_tok)
        self._compression_stats["compressions"] = self.compression_count
        self._compression_stats["total_text_tokens"] = text_tok
        self._compression_stats["total_image_tokens"] = img_tok
        self._compression_stats["total_token_savings"] = savings
        self._compression_stats["per_compression"].append({
            "index": self.compression_count,
            "text_tokens": text_tok,
            "image_tokens": img_tok,
            "token_savings": savings,
            "image_count": render_stats.get("image_count", 0),
            "messages_rendered": render_stats.get("messages_rendered", 0),
        })
        self._write_stats_sidecar()

        logger.info(
            "Visual compression #%d: %d text tokens → %d image tokens (savings=%d, ratio=%.2fx)",
            self.compression_count, text_tok, img_tok, savings,
            text_tok / max(img_tok, 1),
        )

        return final

    @staticmethod
    def _is_self_produced_visual_message(msg: Dict[str, Any]) -> bool:
        """True iff this message is a visual-engine output from a previous compaction.

        We identify our own output by the fixed ``VISUAL_CONTEXT_PROMPT`` text in
        the first content part. This avoids dropping genuine user-supplied images
        (vision tool input, pasted screenshots) when re-compressing later.
        """
        if msg.get("role") != "user":
            return False
        content = msg.get("content")
        if not isinstance(content, list) or not content:
            return False
        first = content[0]
        if not isinstance(first, dict) or first.get("type") != "text":
            return False
        text = first.get("text") or ""
        return isinstance(text, str) and text.startswith(VISUAL_CONTEXT_PROMPT[:60])

    def _protect_head_size(self, messages: List[Dict[str, Any]]) -> int:
        head = 0
        if messages and messages[0].get("role") == "system":
            head = 1
        return head + 3

    def _write_stats_sidecar(self) -> None:
        save_dir = self._save_dir or os.getcwd()
        try:
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(save_dir, "compression_stats.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._compression_stats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Failed to write compression_stats.json: %s", e)
