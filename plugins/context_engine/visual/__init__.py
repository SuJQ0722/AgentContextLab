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
    density: dense
    history_scale: 0.75
    keep_rounds: 1
    recent_rounds: 5
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agent.context_engine import ContextEngine

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
        self._density = "dense"
        self._history_scale = 0.75
        self._keep_rounds = 1
        self._recent_rounds = 5
        self._save_dir: Optional[str] = None

    def configure(self, ctx_cfg: Dict[str, Any]) -> None:
        sc = ctx_cfg.get("strategy_config") or {}
        self._image_width = int(sc.get("image_width", self._image_width))
        self._font_size = int(sc.get("font_size", self._font_size))
        self._max_image_height = int(sc.get("max_image_height", self._max_image_height))
        self._font_path = sc.get("font_path", self._font_path)
        self._dpi = int(sc.get("dpi", self._dpi))
        self._density = sc.get("density", self._density)
        self._history_scale = float(sc.get("history_scale", self._history_scale))
        self._keep_rounds = int(sc.get("keep_rounds", self._keep_rounds))
        self._recent_rounds = int(sc.get("recent_rounds", self._recent_rounds))
        self._save_dir = sc.get("save_dir", self._save_dir)

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

        result = render_visual_compression(
            messages,
            head_end=head_end,
            image_width=self._image_width,
            font_size=self._font_size,
            max_image_height=self._max_image_height,
            font_path=self._font_path,
            dpi=self._dpi,
            density=self._density,
            history_scale=self._history_scale,
            keep_rounds=self._keep_rounds,
            recent_rounds=self._recent_rounds,
            save_dir=self._save_dir,
            compact_count=self.compression_count,
        )

        if result is not messages:
            self.compression_count += 1
        return result

    def _protect_head_size(self, messages: List[Dict[str, Any]]) -> int:
        head = 0
        if messages and messages[0].get("role") == "system":
            head = 1
        return head + 3
