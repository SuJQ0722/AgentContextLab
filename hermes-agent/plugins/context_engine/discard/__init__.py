"""Discard context engine — reset tool-call history to free context space.

Implements the Discard strategy from BrowseComp/DeepSeek:
  Once the running context exceeds a preset threshold, drop all earlier
  ``(thought, action, observation)`` tool-call turns and leave only:

    [system] + [first_user] + last ``keep_rounds`` rounds

  Unlike ``sliding_window`` (which keeps every role frame and only blanks tool
  *content*), discard removes the assistant/tool frames entirely so cumulative
  tool-call metadata does not bloat the prompt either.

Threshold: 32k tokens.

Config (context section in config.yaml):
  engine: discard
  strategy_config:
    keep_rounds: 0   # default: discard all history; keep system + original task

Env override (local-only, takes precedence over config when set):
  HERMES_DISCARD_KEEP_ROUNDS=<int>   # e.g. 0 to discard every prior round
"""

from __future__ import annotations

import logging
import os
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
        self._keep_rounds = 0

    def configure(self, ctx_cfg: Dict[str, Any]) -> None:
        sc = ctx_cfg.get("strategy_config") or {}
        keep = sc.get("keep_rounds", self._keep_rounds)
        env_keep = os.getenv("HERMES_DISCARD_KEEP_ROUNDS")
        if env_keep is not None and env_keep.strip() != "":
            try:
                keep = int(env_keep)
            except ValueError:
                logger.warning(
                    "Ignoring HERMES_DISCARD_KEEP_ROUNDS=%r (not an int); "
                    "falling back to config value %r",
                    env_keep, keep,
                )
        self._keep_rounds = max(0, int(keep))

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

        # 3. Identify rounds. A "round" starts with an assistant message and
        #    includes any contiguous tool messages that follow. Standalone
        #    user messages (e.g. an existing omission placeholder from a prior
        #    rotation, or a mid-stream user follow-up) are skipped — discard
        #    wipes them too.
        rounds: List[List[Dict[str, Any]]] = []
        current_round: List[Dict[str, Any]] = []

        for i in range(idx, len(messages)):
            msg = messages[i]
            role = msg.get("role")

            if role == "assistant":
                if current_round:
                    rounds.append(current_round)
                current_round = [msg]
            elif role == "tool":
                if current_round:
                    current_round.append(msg)
                # tool message with no preceding assistant in this window is
                # dropped — its assistant frame was already discarded.
            elif role == "user":
                # Boundary: any standalone user message ends the previous
                # round and is itself not preserved (the engine wipes
                # everything except the original first_user + last N rounds).
                if current_round:
                    rounds.append(current_round)
                    current_round = []
            # any other role (system mid-stream, etc.) is dropped

        if current_round:
            rounds.append(current_round)

        # 4. Decide which rounds to keep.
        n_rounds = len(rounds)
        keep = min(self._keep_rounds, n_rounds) if self._keep_rounds > 0 else 0
        n_discard = n_rounds - keep
        kept_rounds = rounds[n_discard:] if keep > 0 else []

        # 5. Preserve instructions and original task, but no synthetic memory.
        # Remaining assistant/tool rounds (if requested) stay paired.
        result: List[Dict[str, Any]] = list(head)
        result.append(first_user)

        for round_msgs in kept_rounds:
            result.extend(round_msgs)

        self.compression_count += 1
        logger.info(
            "Discard(keep_rounds=%d): dropped %d/%d rounds, kept %d messages",
            self._keep_rounds, n_discard, n_rounds, len(result),
        )
        return result
