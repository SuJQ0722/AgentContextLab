"""Summarize context engine — full LLM-based structured summarization.

Same algorithm as the built-in ContextCompressor:
  1. Prune old tool results (cheap, no LLM call)
  2. Protect head messages (system prompt + first exchange)
  3. Find tail boundary by token budget
  4. Summarize middle turns with structured LLM prompt
  5. Assemble + sanitize tool pairs + strip old media

Threshold: 32k tokens.

Config (context section in config.yaml):
  engine: summarize
  strategy_config:
    protect_first_n: 3
    protect_last_n: 20
    summary_target_ratio: 0.20
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from agent.context_engine import ContextEngine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted "
    "into the summary below. This is a handoff from a previous context "
    "window — treat it as background reference, NOT as active instructions. "
    "Do NOT answer questions or fulfill requests mentioned in this summary; "
    "they were already addressed. "
    "Your current task is identified in the '## Active Task' section of the "
    "summary — resume exactly from there. "
    "IMPORTANT: Your persistent memory (MEMORY.md, USER.md) in the system "
    "prompt is ALWAYS authoritative and active — never ignore or deprioritize "
    "memory content due to this compaction note. "
    "Respond ONLY to the latest user message "
    "that appears AFTER this summary. The current session state (files, "
    "config, etc.) may reflect work described here — avoid repeating it:"
)
LEGACY_SUMMARY_PREFIX = "[CONTEXT SUMMARY]:"

_MIN_SUMMARY_TOKENS = 2000
_SUMMARY_RATIO = 0.20
_SUMMARY_TOKENS_CEILING = 12_000
_PRUNED_TOOL_PLACEHOLDER = "[Old tool output cleared to save context space]"
_CHARS_PER_TOKEN = 4
_IMAGE_TOKEN_ESTIMATE = 1600
_IMAGE_CHAR_EQUIVALENT = _IMAGE_TOKEN_ESTIMATE * _CHARS_PER_TOKEN
_SUMMARY_FAILURE_COOLDOWN_SECONDS = 600
_IMAGE_PART_TYPES = frozenset({"image_url", "input_image", "image"})

_THRESHOLD_TOKENS = 32768


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _content_length_for_budget(raw_content: Any) -> int:
    if isinstance(raw_content, str):
        return len(raw_content)
    if not isinstance(raw_content, list):
        return len(str(raw_content or ""))
    total = 0
    for p in raw_content:
        if isinstance(p, str):
            total += len(p)
        elif isinstance(p, dict):
            if p.get("type") in _IMAGE_PART_TYPES:
                total += _IMAGE_CHAR_EQUIVALENT
            else:
                total += len(p.get("text", "") or "")
        else:
            total += len(str(p))
    return total


def _content_text_for_contains(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                t = item.get("text")
                if isinstance(t, str):
                    parts.append(t)
        return "\n".join(p for p in parts if p)
    return str(content)


def _append_text_to_content(content: Any, text: str, *, prepend: bool = False) -> Any:
    if content is None:
        return text
    if isinstance(content, str):
        return text + content if prepend else content + text
    if isinstance(content, list):
        block = {"type": "text", "text": text}
        return [block, *content] if prepend else [*content, block]
    rendered = str(content)
    return text + rendered if prepend else rendered + text


def _is_image_part(part: Any) -> bool:
    return isinstance(part, dict) and part.get("type") in _IMAGE_PART_TYPES


def _content_has_images(content: Any) -> bool:
    return isinstance(content, list) and any(_is_image_part(p) for p in content)


def _strip_images_from_content(content: Any) -> Any:
    if not isinstance(content, list):
        return content
    if not any(_is_image_part(p) for p in content):
        return content
    return [
        {"type": "text", "text": "[Attached image — stripped after compression]"} if _is_image_part(p) else p
        for p in content
    ]


def _strip_image_parts_from_parts(parts: Any) -> Any:
    if not isinstance(parts, list):
        return None
    had_image = False
    out = []
    for part in parts:
        if isinstance(part, dict) and part.get("type") in _IMAGE_PART_TYPES:
            had_image = True
            out.append({"type": "text", "text": "[screenshot removed to save context]"})
        else:
            out.append(part)
    return out if had_image else None


def _strip_historical_media(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not messages:
        return messages
    anchor = -1
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, dict) and msg.get("role") == "user" and _content_has_images(msg.get("content")):
            anchor = i
            break
    if anchor <= 0:
        return messages
    changed = False
    result: List[Dict[str, Any]] = []
    for i, msg in enumerate(messages):
        if i >= anchor or not isinstance(msg, dict):
            result.append(msg)
            continue
        content = msg.get("content")
        if not _content_has_images(content):
            result.append(msg)
            continue
        new_msg = msg.copy()
        new_msg["content"] = _strip_images_from_content(content)
        result.append(new_msg)
        changed = True
    return result if changed else messages


def _truncate_tool_call_args_json(args: str, head_chars: int = 200) -> str:
    try:
        parsed = json.loads(args)
    except (ValueError, TypeError):
        return args

    def _shrink(obj):
        if isinstance(obj, str) and len(obj) > head_chars:
            return obj[:head_chars] + "...[truncated]"
        if isinstance(obj, dict):
            return {k: _shrink(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_shrink(v) for v in obj]
        return obj

    return json.dumps(_shrink(parsed), ensure_ascii=False)


def _summarize_tool_result(tool_name: str, tool_args: str, tool_content: str) -> str:
    try:
        args = json.loads(tool_args) if tool_args else {}
    except (json.JSONDecodeError, TypeError):
        args = {}
    content = tool_content or ""
    content_len = len(content)
    line_count = content.count("\n") + 1 if content.strip() else 0

    if tool_name == "terminal":
        cmd = args.get("command", "")
        if len(cmd) > 80:
            cmd = cmd[:77] + "..."
        exit_match = re.search(r'"exit_code"\s*:\s*(-?\d+)', content)
        exit_code = exit_match.group(1) if exit_match else "?"
        return f"[terminal] ran `{cmd}` -> exit {exit_code}, {line_count} lines output"
    if tool_name == "read_file":
        path = args.get("path", "?")
        offset = args.get("offset", 1)
        return f"[read_file] read {path} from line {offset} ({content_len:,} chars)"
    if tool_name == "write_file":
        path = args.get("path", "?")
        return f"[write_file] wrote to {path}"
    if tool_name == "search_files":
        pattern = args.get("pattern", "?")
        path = args.get("path", ".")
        return f"[search_files] '{pattern}' in {path} ({content_len:,} chars)"
    if tool_name == "web_search":
        query = args.get("query", "?")
        return f"[web_search] query='{query}' ({content_len:,} chars)"
    return f"[{tool_name}] ({content_len:,} chars)"


def _estimate_tokens(messages: List[Dict[str, Any]]) -> int:
    total = 0
    for msg in messages:
        total += 10
        total += _content_length_for_budget(msg.get("content") or "") // _CHARS_PER_TOKEN
        for tc in msg.get("tool_calls") or []:
            if isinstance(tc, dict):
                total += len(tc.get("function", {}).get("arguments", "")) // _CHARS_PER_TOKEN
    return total


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class SummarizeEngine(ContextEngine):

    @property
    def name(self) -> str:
        return "summarize"

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
        self.max_compressions: int | None = None

        self._protect_first_n = 3
        self._protect_last_n = 20
        self._summary_target_ratio = 0.20
        self._previous_summary: Optional[str] = None
        self._summary_failure_cooldown_until = 0.0

    def configure(self, ctx_cfg: Dict[str, Any]) -> None:
        sc = ctx_cfg.get("strategy_config") or {}
        self._protect_first_n = int(sc.get("protect_first_n", self._protect_first_n))
        self._protect_last_n = int(sc.get("protect_last_n", self._protect_last_n))
        r = float(sc.get("summary_target_ratio", self._summary_target_ratio))
        self._summary_target_ratio = max(0.10, min(r, 0.80))

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
        if self.max_compressions is not None and self.compression_count >= self.max_compressions:
            return False
        return tokens >= self.threshold_tokens

    def on_session_reset(self) -> None:
        self.compression_count = 0
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self._previous_summary = None
        self._summary_failure_cooldown_until = 0.0

    def compress(
        self,
        messages: List[Dict[str, Any]],
        current_tokens: int = None,
        focus_topic: str = None,
    ) -> List[Dict[str, Any]]:
        if self.max_compressions is not None and self.compression_count >= self.max_compressions:
            logger.warning(
                "Compression skipped — maximum compression count (%d) reached",
                self.max_compressions,
            )
            return messages
        n_messages = len(messages)
        head_end = self._protect_head_size(messages)
        if n_messages <= head_end + 4:
            return messages

        # Phase 1: Prune old tool results
        messages, pruned = self._prune_old_tool_results(messages)
        if pruned:
            logger.info("Pre-compression: pruned %d old tool result(s)", pruned)

        # Phase 2: Determine boundaries
        compress_start = self._align_forward(messages, head_end)
        compress_end = self._find_tail_cut(messages, compress_start)

        if compress_start >= compress_end:
            return messages

        turns_to_summarize = messages[compress_start:compress_end]

        # Check for existing summary
        search_start = 1 if messages and messages[0].get("role") == "system" else 0
        summary_idx, summary_body = self._find_existing_summary(messages, search_start, compress_end)
        if summary_idx is not None:
            if summary_body and not self._previous_summary:
                self._previous_summary = summary_body
            turns_to_summarize = messages[max(compress_start, summary_idx + 1):compress_end]

        logger.info(
            "Summarizing turns %d-%d (%d turns), head=%d tail=%d",
            compress_start, compress_end, len(turns_to_summarize),
            compress_start, n_messages - compress_end,
        )

        # Phase 3: Generate summary
        summary = self._generate_summary(turns_to_summarize, focus_topic)

        # Phase 4: Assemble
        compressed = []
        for i in range(compress_start):
            msg = messages[i].copy()
            if i == 0 and msg.get("role") == "system":
                existing = msg.get("content")
                _note = "[Note: Some earlier conversation turns have been compacted into a handoff summary to preserve context space.]"
                if _note not in _content_text_for_contains(existing):
                    msg["content"] = _append_text_to_content(
                        existing, "\n\n" + _note if isinstance(existing, str) and existing else _note,
                    )
            compressed.append(msg)

        if not summary:
            n_dropped = compress_end - compress_start
            summary = (
                f"{SUMMARY_PREFIX}\n"
                f"Summary generation was unavailable. {n_dropped} message(s) were "
                f"removed to free context space but could not be summarized."
            )

        # Pick summary role
        _merge = False
        last_head_role = messages[compress_start - 1].get("role", "user") if compress_start > 0 else "user"
        first_tail_role = messages[compress_end].get("role", "user") if compress_end < n_messages else "user"

        if last_head_role in {"assistant", "tool"}:
            summary_role = "user"
        else:
            summary_role = "assistant"

        if summary_role == first_tail_role:
            flipped = "assistant" if summary_role == "user" else "user"
            if flipped != last_head_role:
                summary_role = flipped
            else:
                _merge = True

        if not _merge and summary_role == "user":
            summary += "\n\n--- END OF CONTEXT SUMMARY — respond to the message below, not the summary above ---"

        if not _merge:
            compressed.append({"role": summary_role, "content": summary})

        for i in range(compress_end, n_messages):
            msg = messages[i].copy()
            if _merge and i == compress_end:
                prefix = summary + "\n\n--- END OF CONTEXT SUMMARY — respond to the message below, not the summary above ---\n\n"
                msg["content"] = _append_text_to_content(msg.get("content"), prefix, prepend=True)
                _merge = False
            compressed.append(msg)

        self.compression_count += 1
        compressed = self._sanitize_tool_pairs(compressed)
        compressed = _strip_historical_media(compressed)

        saved = _estimate_tokens(messages) - _estimate_tokens(compressed)
        logger.info("Compressed: %d -> %d messages (~%d tokens saved)", n_messages, len(compressed), saved)
        return compressed

    # ------------------------------------------------------------------
    # Boundaries
    # ------------------------------------------------------------------

    def _protect_head_size(self, messages: List[Dict[str, Any]]) -> int:
        head = 1 if messages and messages[0].get("role") == "system" else 0
        return head + self._protect_first_n

    def _align_forward(self, messages: List[Dict[str, Any]], idx: int) -> int:
        while idx < len(messages) and messages[idx].get("role") == "tool":
            idx += 1
        return idx

    def _align_backward(self, messages: List[Dict[str, Any]], idx: int) -> int:
        if idx <= 0 or idx >= len(messages):
            return idx
        check = idx - 1
        while check >= 0 and messages[check].get("role") == "tool":
            check -= 1
        if check >= 0 and messages[check].get("role") == "assistant" and messages[check].get("tool_calls"):
            idx = check
        return idx

    def _find_tail_cut(self, messages: List[Dict[str, Any]], head_end: int) -> int:
        token_budget = int(self.threshold_tokens * self._summary_target_ratio)
        n = len(messages)
        min_tail = min(3, n - head_end - 1) if n - head_end > 1 else 0
        soft_ceiling = int(token_budget * 1.5)
        accumulated = 0
        cut_idx = n

        for i in range(n - 1, head_end - 1, -1):
            msg = messages[i]
            msg_tokens = _content_length_for_budget(msg.get("content") or "") // _CHARS_PER_TOKEN + 10
            for tc in msg.get("tool_calls") or []:
                if isinstance(tc, dict):
                    msg_tokens += len(tc.get("function", {}).get("arguments", "")) // _CHARS_PER_TOKEN
            if accumulated + msg_tokens > soft_ceiling and (n - i) >= min_tail:
                break
            accumulated += msg_tokens
            cut_idx = i

        fallback_cut = n - min_tail
        cut_idx = min(cut_idx, fallback_cut)
        if cut_idx <= head_end:
            cut_idx = max(fallback_cut, head_end + 1)

        cut_idx = self._align_backward(messages, cut_idx)

        # Ensure last user message is in tail
        last_user = -1
        for i in range(n - 1, head_end - 1, -1):
            if messages[i].get("role") == "user":
                last_user = i
                break
        if last_user >= 0 and last_user < cut_idx:
            cut_idx = max(last_user, head_end + 1)

        return max(cut_idx, head_end + 1)

    # ------------------------------------------------------------------
    # Pruning
    # ------------------------------------------------------------------

    def _prune_old_tool_results(self, messages: List[Dict[str, Any]]) -> tuple:
        if not messages:
            return messages, 0

        result = [m.copy() for m in messages]
        pruned = 0

        call_id_to_tool: Dict[str, tuple] = {}
        for msg in result:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls") or []:
                    if isinstance(tc, dict):
                        cid = tc.get("id", "")
                        fn = tc.get("function", {})
                        call_id_to_tool[cid] = (fn.get("name", "unknown"), fn.get("arguments", ""))

        # Token-budget prune boundary
        tail_budget = int(self.threshold_tokens * self._summary_target_ratio)
        accumulated = 0
        prune_boundary = len(result)
        min_protect = min(self._protect_last_n, len(result))
        for i in range(len(result) - 1, -1, -1):
            msg = result[i]
            msg_tokens = _content_length_for_budget(msg.get("content") or "") // _CHARS_PER_TOKEN + 10
            for tc in msg.get("tool_calls") or []:
                if isinstance(tc, dict):
                    msg_tokens += len(tc.get("function", {}).get("arguments", "")) // _CHARS_PER_TOKEN
            if accumulated + msg_tokens > tail_budget and (len(result) - i) >= min_protect:
                prune_boundary = i
                break
            accumulated += msg_tokens
            prune_boundary = i
        budget_count = len(result) - prune_boundary
        prune_boundary = len(result) - max(budget_count, min_protect)

        # Dedup pass
        content_hashes: dict = {}
        for i in range(len(result) - 1, -1, -1):
            msg = result[i]
            if msg.get("role") != "tool":
                continue
            content = msg.get("content") or ""
            if not isinstance(content, str) or len(content) < 200:
                continue
            h = hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()[:12]
            if h in content_hashes:
                result[i] = {**msg, "content": "[Duplicate tool output — same content as a more recent call]"}
                pruned += 1
            else:
                content_hashes[h] = i

        # Replace old tool results
        for i in range(prune_boundary):
            msg = result[i]
            if msg.get("role") != "tool":
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                stripped = _strip_image_parts_from_parts(content)
                if stripped is not None:
                    result[i] = {**msg, "content": stripped}
                    pruned += 1
                continue
            if not isinstance(content, str) or not content or content == _PRUNED_TOOL_PLACEHOLDER:
                continue
            if content.startswith("[Duplicate tool output"):
                continue
            if len(content) > 200:
                call_id = msg.get("tool_call_id", "")
                tool_name, tool_args = call_id_to_tool.get(call_id, ("unknown", ""))
                result[i] = {**msg, "content": _summarize_tool_result(tool_name, tool_args, content)}
                pruned += 1

        # Truncate large tool_call arguments
        for i in range(prune_boundary):
            msg = result[i]
            if msg.get("role") != "assistant" or not msg.get("tool_calls"):
                continue
            new_tcs = []
            modified = False
            for tc in msg["tool_calls"]:
                if isinstance(tc, dict):
                    args = tc.get("function", {}).get("arguments", "")
                    if len(args) > 500:
                        new_args = _truncate_tool_call_args_json(args)
                        if new_args != args:
                            tc = {**tc, "function": {**tc["function"], "arguments": new_args}}
                            modified = True
                new_tcs.append(tc)
            if modified:
                result[i] = {**msg, "tool_calls": new_tcs}

        return result, pruned

    # ------------------------------------------------------------------
    # Summary generation
    # ------------------------------------------------------------------

    _CONTENT_MAX = 6000
    _CONTENT_HEAD = 4000
    _CONTENT_TAIL = 1500
    _TOOL_ARGS_MAX = 1500
    _TOOL_ARGS_HEAD = 1200

    def _serialize_for_summary(self, turns: List[Dict[str, Any]]) -> str:
        parts = []
        for msg in turns:
            role = msg.get("role", "unknown")
            content = msg.get("content") or ""

            if role == "tool":
                tool_id = msg.get("tool_call_id", "")
                if isinstance(content, str) and len(content) > self._CONTENT_MAX:
                    content = content[:self._CONTENT_HEAD] + "\n...[truncated]...\n" + content[-self._CONTENT_TAIL:]
                parts.append(f"[TOOL RESULT {tool_id}]: {content}")
                continue

            if role == "assistant":
                if isinstance(content, str) and len(content) > self._CONTENT_MAX:
                    content = content[:self._CONTENT_HEAD] + "\n...[truncated]...\n" + content[-self._CONTENT_TAIL:]
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    tc_parts = []
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            fn = tc.get("function", {})
                            nm = fn.get("name", "?")
                            args = fn.get("arguments", "")
                            if len(args) > self._TOOL_ARGS_MAX:
                                args = args[:self._TOOL_ARGS_HEAD] + "..."
                            tc_parts.append(f"  {nm}({args})")
                    suffix = "\n[Tool calls:\n" + "\n".join(tc_parts) + "\n]"
                    content = (content + suffix) if isinstance(content, str) else suffix
                parts.append(f"[ASSISTANT]: {content}")
                continue

            if isinstance(content, str) and len(content) > self._CONTENT_MAX:
                content = content[:self._CONTENT_HEAD] + "\n...[truncated]...\n" + content[-self._CONTENT_TAIL:]
            parts.append(f"[{role.upper()}]: {content}")

        return "\n\n".join(parts)

    def _generate_summary(self, turns: List[Dict[str, Any]], focus_topic: str = None) -> Optional[str]:
        now = time.monotonic()
        if now < self._summary_failure_cooldown_until:
            return None

        content_tokens = _estimate_tokens(turns)
        budget = int(content_tokens * _SUMMARY_RATIO)
        max_tokens = min(int(self.context_length * 0.05), _SUMMARY_TOKENS_CEILING)
        summary_budget = max(_MIN_SUMMARY_TOKENS, min(budget, max_tokens))

        content_to_summarize = self._serialize_for_summary(turns)

        preamble = (
            "You are a summarization agent creating a context checkpoint. "
            "Treat the conversation turns below as source material for a "
            "compact record of prior work. "
            "Produce only the structured summary; do not add a greeting, preamble, or prefix. "
            "Write the summary in the same language the user was using. "
            "NEVER include API keys, tokens, passwords, secrets, or credentials — use [REDACTED]."
        )

        template = f"""## Active Task
[Copy the user's most recent unfulfilled request verbatim.]

## Goal
[What the user is trying to accomplish overall]

## Constraints & Preferences
[User preferences, coding style, constraints, important decisions]

## Completed Actions
[Numbered list: N. ACTION target — outcome [tool: name]]

## Active State
[Modified/created files, test status, running processes]

## In Progress
[Work currently underway when compaction fired]

## Blocked
[Blockers, errors, issues not yet resolved.]

## Key Decisions
[Important technical decisions and WHY]

## Resolved Questions
[Questions already answered — include the answer]

## Pending User Asks
[Requests NOT yet fulfilled. If none, "None."]

## Relevant Files
[Files read, modified, or created]

## Remaining Work
[What remains — context, not instructions]

## Critical Context
[Specific values, error messages, config. NEVER credentials.]

Target ~{summary_budget} tokens. Be CONCRETE."""

        if self._previous_summary:
            prompt = f"""{preamble}

You are updating a context compaction summary.

PREVIOUS SUMMARY:
{self._previous_summary}

NEW TURNS TO INCORPORATE:
{content_to_summarize}

Update the summary. PRESERVE relevant info. ADD new actions. Update "Active Task" to the user's most recent unfulfilled request.

{template}"""
        else:
            prompt = f"""{preamble}

Create a structured checkpoint summary.

TURNS TO SUMMARIZE:
{content_to_summarize}

Use this structure:

{template}"""

        if focus_topic:
            prompt += f'\n\nFOCUS TOPIC: "{focus_topic}"\nPrioritise preserving info related to this topic.'

        try:
            from agent.auxiliary_client import call_llm
            call_kwargs: Dict[str, Any] = {
                "task": "compression",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": int(summary_budget * 1.3),
            }
            if self.model:
                call_kwargs["main_runtime"] = {
                    "model": self.model,
                    "provider": self.provider,
                    "base_url": self.base_url,
                    "api_key": self.api_key,
                    "api_mode": self.api_mode,
                }
            response = call_llm(**call_kwargs)
            content = response.choices[0].message.content
            if not isinstance(content, str):
                content = str(content) if content else ""
            summary = content.strip()
            self._previous_summary = summary
            self._summary_failure_cooldown_until = 0.0
            return f"{SUMMARY_PREFIX}\n{summary}"
        except RuntimeError:
            self._summary_failure_cooldown_until = time.monotonic() + _SUMMARY_FAILURE_COOLDOWN_SECONDS
            logger.warning("Summarize engine: no provider available.")
            return None
        except Exception as e:
            self._summary_failure_cooldown_until = time.monotonic() + 60
            logger.warning("Summarize engine: summary failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Summary detection
    # ------------------------------------------------------------------

    def _find_existing_summary(self, messages: List[Dict[str, Any]], start: int, end: int) -> tuple:
        for idx in range(end - 1, start - 1, -1):
            text = _content_text_for_contains(messages[idx].get("content")).lstrip()
            if text.startswith(SUMMARY_PREFIX) or text.startswith(LEGACY_SUMMARY_PREFIX):
                body = text
                for prefix in (SUMMARY_PREFIX, LEGACY_SUMMARY_PREFIX):
                    if body.startswith(prefix):
                        body = body[len(prefix):].lstrip()
                        break
                return idx, body
        return None, ""

    # ------------------------------------------------------------------
    # Tool pair sanitization
    # ------------------------------------------------------------------

    @staticmethod
    def _get_tc_id(tc) -> str:
        if isinstance(tc, dict):
            return tc.get("call_id", "") or tc.get("id", "") or ""
        return getattr(tc, "call_id", "") or getattr(tc, "id", "") or ""

    def _sanitize_tool_pairs(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        surviving_ids: set = set()
        for msg in messages:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls") or []:
                    cid = self._get_tc_id(tc)
                    if cid:
                        surviving_ids.add(cid)

        result_ids: set = set()
        for msg in messages:
            if msg.get("role") == "tool":
                cid = msg.get("tool_call_id")
                if cid:
                    result_ids.add(cid)

        orphaned = result_ids - surviving_ids
        if orphaned:
            messages = [m for m in messages if not (m.get("role") == "tool" and m.get("tool_call_id") in orphaned)]

        missing = surviving_ids - result_ids
        if missing:
            patched: List[Dict[str, Any]] = []
            for msg in messages:
                patched.append(msg)
                if msg.get("role") == "assistant":
                    for tc in msg.get("tool_calls") or []:
                        cid = self._get_tc_id(tc)
                        if cid in missing:
                            patched.append({
                                "role": "tool",
                                "content": "[Result from earlier conversation — see context summary above]",
                                "tool_call_id": cid,
                            })
            messages = patched

        return messages
