"""Sliding window context engine.

Keeps the last N tool results intact and replaces older tool result contents
with a short placeholder. Non-tool messages are preserved. Threshold: 32k tokens.

Config (context section in config.yaml):
  engine: sliding_window
  strategy_config:
    window_size: 5   # number of recent tool results to keep
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agent.context_engine import ContextEngine

logger = logging.getLogger(__name__)

_THRESHOLD_TOKENS = 32768


class SlidingWindowEngine(ContextEngine):

    @property
    def name(self) -> str:
        return "sliding_window"

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
        self._window_size = 5

    def configure(self, ctx_cfg: Dict[str, Any]) -> None:
        sc = ctx_cfg.get("strategy_config") or {}
        self._window_size = int(sc.get("window_size", self._window_size))
        if self._window_size < 1:
            self._window_size = 1

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
        head_end = self._protect_head_size(messages)

        tool_indices = [
            i for i, m in enumerate(messages)
            if m.get("role") == "tool" and i >= head_end
        ]

        if len(tool_indices) <= self._window_size:
            return messages

        to_blank = set(tool_indices[:-self._window_size])
        result = []
        for i, msg in enumerate(messages):
            if i in to_blank:
                result.append({**msg, "content": "[tool response omitted]"})
            else:
                result.append(msg)

        self.compression_count += 1
        logger.info(
            "SlidingWindow: blanked %d tool result(s), kept %d",
            len(to_blank), self._window_size,
        )
        return result

    def _protect_head_size(self, messages: List[Dict[str, Any]]) -> int:
        head = 0
        if messages and messages[0].get("role") == "system":
            head = 1
        return head + 3
