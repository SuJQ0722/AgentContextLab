"""Discard-all context engine.

Two modes:
  - "tool_response" (default): Replace all tool result contents with a placeholder.
  - "full_history": Keep only head messages (system + first exchange).

Threshold: 32k tokens.

Config (context section in config.yaml):
  engine: discard_all
  strategy_config:
    discard_mode: tool_response   # or "full_history"
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agent.context_engine import ContextEngine

logger = logging.getLogger(__name__)

_THRESHOLD_TOKENS = 32768
_VALID_MODES = ("tool_response", "full_history")


class DiscardAllEngine(ContextEngine):

    @property
    def name(self) -> str:
        return "discard_all"

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
        self._discard_mode = "tool_response"

    def configure(self, ctx_cfg: Dict[str, Any]) -> None:
        sc = ctx_cfg.get("strategy_config") or {}
        mode = sc.get("discard_mode", self._discard_mode)
        if mode in _VALID_MODES:
            self._discard_mode = mode

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
        if self._discard_mode == "full_history":
            head_end = self._protect_head_size(messages)
            result = list(messages[:head_end])
            if not result:
                result = messages[:1]
            self.compression_count += 1
            logger.info("DiscardAll(full_history): kept %d head messages", len(result))
            return result

        # tool_response mode
        result = []
        for msg in messages:
            if msg.get("role") == "tool":
                result.append({**msg, "content": "[tool response discarded]"})
            else:
                result.append(msg)
        self.compression_count += 1
        logger.info("DiscardAll(tool_response): blanked all tool results")
        return result

    def _protect_head_size(self, messages: List[Dict[str, Any]]) -> int:
        head = 0
        if messages and messages[0].get("role") == "system":
            head = 1
        return head + 3
