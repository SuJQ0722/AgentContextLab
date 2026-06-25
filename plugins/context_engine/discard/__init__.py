"""Discard context engine — reset tool-call history to free context space.

Implements the Discard strategy from BrowseComp/DeepSeek:
  Once the running context exceeds a preset threshold, discard past
  (thought, action, observation) tool-call pairs from the prompt while
  keeping the original question and minimal task specification. The agent
  re-initiates from a fresh context.

Supports a configurable discard ratio:
  - discard_ratio: 1.0 (default, "discard-all") removes ALL tool-call history
  - discard_ratio: 0.75 ("discard-75%") removes the first 75% of rounds

Threshold: 32k tokens.

Config (context section in config.yaml):
  engine: discard
  strategy_config:
    discard_ratio: 1.0      # 0.0-1.0, fraction of rounds to discard from front
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agent.context_engine import ContextEngine

logger = logging.getLogger(__name__)

_THRESHOLD_TOKENS = 32768


class DiscardEngine(ContextEngine):

    @property
    def name(self) -> str:
        return "discard"

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
        self._discard_ratio = 1.0

    def configure(self, ctx_cfg: Dict[str, Any]) -> None:
        sc = ctx_cfg.get("strategy_config") or {}
        ratio = float(sc.get("discard_ratio", self._discard_ratio))
        self._discard_ratio = max(0.0, min(ratio, 1.0))

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
        # 1. Extract head (system prompt)
        head: List[Dict[str, Any]] = []
        idx = 0
        if messages and messages[0].get("role") == "system":
            head.append(messages[0])
            idx = 1

        # 2. Find the first user message (original question)
        first_user: Optional[Dict[str, Any]] = None
        for i in range(idx, len(messages)):
            if messages[i].get("role") == "user":
                first_user = messages[i]
                idx = i + 1
                break

        if first_user is None:
            return messages

        # 3. Identify rounds: each round starts with an assistant message
        #    and includes any following tool messages
        rounds: List[List[Dict[str, Any]]] = []
        current_round: List[Dict[str, Any]] = []
        last_user_msg: Optional[Dict[str, Any]] = None

        for i in range(idx, len(messages)):
            msg = messages[i]
            role = msg.get("role")

            if role == "user":
                if current_round:
                    rounds.append(current_round)
                    current_round = []
                last_user_msg = msg
            elif role == "assistant":
                if current_round:
                    rounds.append(current_round)
                    current_round = []
                current_round.append(msg)
            elif role == "tool":
                current_round.append(msg)
            else:
                current_round.append(msg)

        if current_round:
            rounds.append(current_round)

        if not rounds:
            return messages

        # 4. Calculate how many rounds to discard
        n_rounds = len(rounds)
        n_discard = int(n_rounds * self._discard_ratio)
        if self._discard_ratio < 1.0 and n_discard >= n_rounds:
            n_discard = n_rounds - 1

        # 5. Assemble result: head + first_user + kept rounds + last_user
        result: List[Dict[str, Any]] = list(head)
        result.append(first_user)

        kept_rounds = rounds[n_discard:]
        for round_msgs in kept_rounds:
            result.extend(round_msgs)

        if last_user_msg is not None and last_user_msg is not first_user:
            if not result or result[-1] is not last_user_msg:
                if last_user_msg not in result:
                    result.append(last_user_msg)

        self.compression_count += 1
        ratio_pct = int(self._discard_ratio * 100)
        logger.info(
            "Discard(%d%%): removed %d/%d rounds, kept %d messages",
            ratio_pct, n_discard, n_rounds, len(result),
        )
        return result
