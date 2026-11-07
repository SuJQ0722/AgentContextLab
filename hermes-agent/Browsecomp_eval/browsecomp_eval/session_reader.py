from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


FINAL_FINISH_REASONS = {"stop", "end_turn", "done", "complete", "completed"}
TOOL_FINISH_REASONS = {"tool_calls", "function_call"}
RAW_TOOL_CALL_RE = re.compile(
    r"^\s*(?:<\s*tool_call\b|<\s*function\s*=|<\s*parameter\s*=)",
    re.IGNORECASE,
)


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()


def load_session(
    session_id: str | None,
    profile: str | None = None,
    include_ancestors: bool = False,
) -> dict[str, Any] | None:
    """Load a hermes session from state.db (or legacy JSON).

    When ``include_ancestors=True``, follows the ``parent_session_id`` chain
    to load messages from ALL sessions in the compression lineage (root → tip),
    giving the full uncompressed trajectory.
    """
    if not session_id:
        return None

    home = hermes_home()
    candidates = []
    if profile:
        candidates.append(home / "profiles" / profile / "state.db")
    candidates.append(home / "state.db")

    for db_path in candidates:
        if not db_path.exists():
            continue
        session = _load_sqlite_session(db_path, session_id, include_ancestors=include_ancestors)
        if session:
            return session

    legacy_candidates = []
    if profile:
        legacy_candidates.append(home / "profiles" / profile / "sessions" / f"session_{session_id}.json")
    legacy_candidates.append(home / "sessions" / f"session_{session_id}.json")

    for path in legacy_candidates:
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None


def _get_session_lineage(conn: sqlite3.Connection, session_id: str) -> list[str]:
    """Walk parent_session_id chain to find compression-lineage ancestors.

    Only follows parent links where the child is source='cli' (compression).
    Subagent sessions (source='subagent') use parent_session_id for delegation,
    not compression, so their parent link is NOT traversed.

    Returns [root_id, ..., session_id] in chronological order.
    """
    chain: list[str] = []
    current = session_id
    seen: set[str] = set()
    for _ in range(100):
        if not current or current in seen:
            break
        seen.add(current)
        chain.append(current)
        row = conn.execute(
            "SELECT parent_session_id, source FROM sessions WHERE id=?", (current,)
        ).fetchone()
        if row is None or not row[0]:
            break
        if row[1] == "subagent":
            break
        current = row[0]
    chain.reverse()
    return chain


def _load_sqlite_session(
    db_path: Path, session_id: str, include_ancestors: bool = False
) -> dict[str, Any] | None:
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            "SELECT id, model, started_at, ended_at, system_prompt, message_count "
            "FROM sessions WHERE id=?",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        session = {
            "session_id": row[0],
            "model": row[1],
            "session_start": _ts_to_iso(row[2]),
            "last_updated": _ts_to_iso(row[3]),
            "system_prompt": row[4] or "",
            "message_count": row[5] or 0,
            "messages": [],
        }

        if include_ancestors:
            session_ids = _get_session_lineage(conn, session_id)
            session["lineage_session_ids"] = session_ids
            session["compression_count"] = max(0, len(session_ids) - 1)
        else:
            session_ids = [session_id]

        if not session["last_updated"]:
            cur.execute("SELECT MAX(timestamp) FROM messages WHERE session_id=?", (session_id,))
            max_ts = cur.fetchone()
            if max_ts and max_ts[0]:
                session["last_updated"] = _ts_to_iso(max_ts[0])

        cur.execute("PRAGMA table_info(messages)")
        available = {row[1] for row in cur.fetchall()}
        wanted = ["role", "content", "tool_calls", "tool_name", "finish_reason", "tool_call_id", "reasoning_content"]
        select_cols = [col if col in available else f"NULL AS {col}" for col in wanted]

        has_timestamp = "timestamp" in available
        order_clause = "ORDER BY timestamp, id" if has_timestamp else "ORDER BY id"

        placeholders = ",".join("?" for _ in session_ids)
        cur.execute(
            f"SELECT {', '.join(select_cols)} FROM messages "
            f"WHERE session_id IN ({placeholders}) {order_clause}",
            tuple(session_ids),
        )
        for msg_row in cur.fetchall():
            role, content, tool_calls_json, tool_name, finish_reason, tool_call_id, reasoning_content = msg_row
            msg = {
                "role": role,
                "content": content or "",
                "finish_reason": finish_reason,
            }
            if tool_calls_json:
                try:
                    msg["tool_calls"] = json.loads(tool_calls_json)
                except Exception:
                    msg["tool_calls_raw"] = tool_calls_json
            if tool_name:
                msg["tool_name"] = tool_name
            if tool_call_id:
                msg["tool_call_id"] = tool_call_id
            if reasoning_content:
                msg["reasoning_content"] = reasoning_content
            session["messages"].append(msg)

        if include_ancestors:
            session["message_count"] = len(session["messages"])

        return session
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()


_TOKEN_COLUMNS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "api_call_count",
)

_TOKEN_DERIVED_COLUMNS = (
    "cache_total_tokens",
    "noncached_total_tokens",
    "prompt_tokens_including_cache",
    "total_tokens_including_cache",
)


def _empty_token_usage() -> dict[str, int]:
    usage = {col: 0 for col in _TOKEN_COLUMNS}
    usage["total_tokens"] = 0
    for col in _TOKEN_DERIVED_COLUMNS:
        usage[col] = 0
    usage["session_count"] = 0
    return usage


def _finalize_token_usage(usage: dict[str, int]) -> dict[str, int]:
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    cache_read_tokens = int(usage.get("cache_read_tokens", 0) or 0)
    cache_write_tokens = int(usage.get("cache_write_tokens", 0) or 0)
    existing_total_tokens = int(usage.get("total_tokens", 0) or 0)

    cache_total_tokens = cache_read_tokens + cache_write_tokens
    if input_tokens or output_tokens or cache_total_tokens or existing_total_tokens == 0:
        noncached_total_tokens = input_tokens + output_tokens
    else:
        noncached_total_tokens = existing_total_tokens
    prompt_tokens_including_cache = input_tokens + cache_total_tokens

    usage["cache_total_tokens"] = cache_total_tokens
    usage["noncached_total_tokens"] = noncached_total_tokens
    usage["total_tokens"] = noncached_total_tokens
    usage["prompt_tokens_including_cache"] = prompt_tokens_including_cache
    usage["total_tokens_including_cache"] = prompt_tokens_including_cache + output_tokens
    return usage


def load_token_usage(
    session_id: str | None,
    profile: str | None = None,
) -> dict[str, int]:
    """Sum the real token accounting hermes records on the ``sessions`` table
    across the whole compression lineage (root -> tip).

    Unlike the ``len(content)//4`` heuristic, these are the actual usage
    numbers hermes accumulates per API call: ``input_tokens`` / ``output_tokens``
    / cache / reasoning, plus ``api_call_count``. Returns zeros when the session
    or columns are unavailable so callers can rely on the shape.
    """
    usage = _empty_token_usage()
    if not session_id:
        return usage

    home = hermes_home()
    candidates = []
    if profile:
        candidates.append(home / "profiles" / profile / "state.db")
    candidates.append(home / "state.db")

    for db_path in candidates:
        if not db_path.exists():
            continue
        result = _load_token_usage_from_db(db_path, session_id)
        if result is not None:
            return result
    return usage


def _load_token_usage_from_db(
    db_path: Path, session_id: str
) -> dict[str, int] | None:
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT id FROM sessions WHERE id=?", (session_id,))
        if cur.fetchone() is None:
            return None

        cur.execute("PRAGMA table_info(sessions)")
        available = {row[1] for row in cur.fetchall()}
        cols = [c for c in _TOKEN_COLUMNS if c in available]
        if not cols:
            usage = _empty_token_usage()
            usage["session_count"] = len(_get_session_lineage(conn, session_id))
            return _finalize_token_usage(usage)

        session_ids = _get_session_lineage(conn, session_id)
        placeholders = ",".join("?" for _ in session_ids)
        select = ", ".join(f"COALESCE(SUM({c}), 0)" for c in cols)
        cur.execute(
            f"SELECT {select} FROM sessions WHERE id IN ({placeholders})",
            tuple(session_ids),
        )
        summed = cur.fetchone() or [0] * len(cols)

        usage = _empty_token_usage()
        for col, value in zip(cols, summed):
            usage[col] = int(value or 0)
        usage["session_count"] = len(session_ids)
        return _finalize_token_usage(usage)
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()


def load_child_sessions(
    parent_session_id: str | None,
    profile: str | None = None,
) -> list[dict[str, Any]]:
    """Load delegate sub-sessions whose parent_session_id matches the given session.

    Returns a list of session dicts (same shape as load_session output), ordered
    by started_at. Empty list if none found.
    """
    if not parent_session_id:
        return []

    home = hermes_home()
    candidates = []
    if profile:
        candidates.append(home / "profiles" / profile / "state.db")
    candidates.append(home / "state.db")

    for db_path in candidates:
        if not db_path.exists():
            continue
        children = _query_child_session_ids(db_path, parent_session_id)
        if children:
            return [
                sess
                for child_id in children
                if (sess := load_session(child_id, profile)) is not None
            ]
    return []


def _query_child_session_ids(db_path: Path, parent_session_id: str) -> list[str]:
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM sessions WHERE parent_session_id = ? AND source = 'subagent' ORDER BY started_at",
            (parent_session_id,),
        )
        return [row[0] for row in cur.fetchall()]
    except Exception:
        return []
    finally:
        if conn is not None:
            conn.close()


def _ts_to_iso(value: Any) -> str:
    if not value:
        return ""
    try:
        return datetime.fromtimestamp(float(value)).isoformat()
    except Exception:
        return ""


def extract_last_assistant_message(session: dict[str, Any] | None) -> str:
    if not session:
        return ""
    for msg in reversed(session.get("messages", [])):
        if msg.get("role") == "assistant" and str(msg.get("content", "")).strip():
            return str(msg["content"]).strip()
    return ""


def text_from_content(content: Any) -> str:
    parts: list[str] = []

    def collect(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            text = value.strip()
            if text:
                parts.append(text)
            return
        if isinstance(value, list):
            for item in value:
                collect(item)
            return
        if isinstance(value, dict):
            for key in ("text", "content", "value"):
                if key in value:
                    collect(value.get(key))

    collect(content)
    return "\n".join(parts).strip()


def extract_final_assistant_message(session: dict[str, Any] | None) -> tuple[str, str]:
    if not session:
        return "", "missing session"

    messages = session.get("messages", [])
    if not messages:
        return "", "empty session messages"

    last = messages[-1]
    if not isinstance(last, dict):
        return "", "last message is not an object"

    role = last.get("role")
    if role != "assistant":
        return "", f"last message role is {role!r}, not assistant"

    if last.get("tool_calls") or last.get("tool_calls_raw"):
        return "", "final assistant still has tool_calls"

    finish_reason_raw = last.get("finish_reason")
    finish_reason = str(finish_reason_raw).strip().lower() if finish_reason_raw is not None else ""
    if finish_reason:
        if finish_reason in TOOL_FINISH_REASONS:
            return "", f"final assistant finish_reason is {finish_reason}"
        if finish_reason not in FINAL_FINISH_REASONS:
            return "", f"unexpected final assistant finish_reason: {finish_reason_raw}"

    text = text_from_content(last.get("content"))
    if not text:
        return "", "empty final assistant content"
    if _looks_like_raw_tool_call(text):
        return "", "final assistant content looks like a raw tool call"
    return text, ""


def _looks_like_raw_tool_call(text: str) -> bool:
    stripped = text.strip()
    if RAW_TOOL_CALL_RE.search(stripped):
        return True
    lowered = stripped.lower()
    return "<tool_call" in lowered and "</tool_call>" in lowered


def extract_trace(session: dict[str, Any] | None) -> dict[str, Any]:
    if not session:
        return {
            "rounds": 0,
            "total_tokens_estimate": 0,
            "duration_seconds": 0.0,
            "tool_calls": {},
        }

    messages = session.get("messages", [])
    total_tokens_estimate = sum(len(str(m.get("content", ""))) for m in messages) // 4
    duration = _duration_seconds(session.get("session_start", ""), session.get("last_updated", ""))
    tool_calls = extract_tool_calls(messages)
    return {
        "rounds": len(messages),
        "total_tokens_estimate": total_tokens_estimate,
        "duration_seconds": duration,
        "tool_calls": tool_calls,
    }


def extract_tool_calls(messages: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("tool_name"):
            name = str(msg["tool_name"])
            counts[name] = counts.get(name, 0) + 1

    if counts:
        return counts

    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for call in msg.get("tool_calls", []) or []:
            fn = call.get("function", {}) if isinstance(call, dict) else {}
            name = (fn.get("name") or call.get("name")) if isinstance(call, dict) else None
            if name:
                counts[str(name)] = counts.get(str(name), 0) + 1
    return counts


def _duration_seconds(start: str, end: str) -> float:
    if not start or not end:
        return 0.0
    try:
        return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 2)
    except Exception:
        return 0.0


def _load_single_session_messages(db_path: Path, session_id: str) -> list[dict[str, Any]]:
    """Load messages for exactly one session (no lineage walk)."""
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(messages)")
        available = {row[1] for row in cur.fetchall()}
        wanted = ["role", "content", "tool_calls", "tool_name", "finish_reason", "tool_call_id", "reasoning_content"]
        select_cols = [col if col in available else f"NULL AS {col}" for col in wanted]
        has_timestamp = "timestamp" in available
        order_clause = "ORDER BY timestamp, id" if has_timestamp else "ORDER BY id"
        cur.execute(
            f"SELECT {', '.join(select_cols)} FROM messages "
            f"WHERE session_id = ? {order_clause}",
            (session_id,),
        )
        messages = []
        for msg_row in cur.fetchall():
            role, content, tool_calls_json, tool_name, finish_reason, tool_call_id, reasoning_content = msg_row
            msg: dict[str, Any] = {
                "role": role,
                "content": content or "",
                "finish_reason": finish_reason,
            }
            if tool_calls_json:
                try:
                    msg["tool_calls"] = json.loads(tool_calls_json)
                except Exception:
                    msg["tool_calls_raw"] = tool_calls_json
            if tool_name:
                msg["tool_name"] = tool_name
            if tool_call_id:
                msg["tool_call_id"] = tool_call_id
            if reasoning_content:
                msg["reasoning_content"] = reasoning_content
            messages.append(msg)
        return messages
    except Exception:
        return []
    finally:
        if conn is not None:
            conn.close()


def load_compression_snapshots(
    session_id: str | None,
    profile: str | None = None,
) -> list[dict[str, Any]]:
    """Build per-compression-event snapshots from the session lineage.

    For a lineage [S0, S1, S2, ...] where S0 is root and each Si (i>0) is
    created by a compression event, returns a list of snapshot dicts::

        [
          {
            "compress_index": 1,
            "pre_session_id": "S0",
            "post_session_id": "S1",
            "pre_compress_messages": [...],   # S0's messages (what existed before compress)
            "summary_message": {...},         # first assistant msg of S1 (the summary)
            "post_compress_messages": [...],  # S1's full messages (post-compress state)
          },
          ...
        ]

    Returns an empty list when there is no compression (single-session lineage).
    """
    if not session_id:
        return []

    home = hermes_home()
    candidates = []
    if profile:
        candidates.append(home / "profiles" / profile / "state.db")
    candidates.append(home / "state.db")

    for db_path in candidates:
        if not db_path.exists():
            continue
        conn = None
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("SELECT id FROM sessions WHERE id=?", (session_id,))
            if cur.fetchone() is None:
                continue
            lineage = _get_session_lineage(conn, session_id)
        except Exception:
            continue
        finally:
            if conn is not None:
                conn.close()

        if len(lineage) < 2:
            return []

        snapshots: list[dict[str, Any]] = []
        for i in range(1, len(lineage)):
            pre_id = lineage[i - 1]
            post_id = lineage[i]
            pre_msgs = _load_single_session_messages(db_path, pre_id)
            post_msgs = _load_single_session_messages(db_path, post_id)

            # Compressor input = pre session's full messages
            # Compressor output = post session's first user message (the compressed context)
            summary_output: dict[str, Any] | None = None
            for msg in post_msgs:
                if msg.get("role") == "user":
                    summary_output = msg
                    break

            snapshots.append({
                "compress_index": i,
                "pre_session_id": pre_id,
                "post_session_id": post_id,
                "pre_compress_messages": pre_msgs,
                "summary_message": {
                    "input": pre_msgs,
                    "output": summary_output,
                },
                "post_compress_messages": post_msgs,
            })
        return snapshots

    return []
