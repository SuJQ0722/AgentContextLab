"""BrowseComp benchmark-leak guard.

The plugin is opt-in and remains inert unless the process is running a
BrowseComp evaluation (``BROWSE_COMP_RUN_ID`` is set). It blocks benchmark-
aware requests before execution and removes benchmark resources that appear in
web results or browser pages. A block is an ordinary tool failure: the agent
loop continues and the inference record is not marked as a policy violation.
"""

from __future__ import annotations

import html
import json
import os
import re
import threading
from typing import Any
from urllib.parse import unquote_plus


_ACTIVE_ENV = "BROWSE_COMP_RUN_ID"
_BLOCK_MESSAGE = (
    "Blocked by the BrowseComp anti-cheat guard. Continue using ordinary "
    "first-party or independent web sources."
)

# Match canonical names plus the variants observed in real cheating traces.
# Decode before matching so percent-encoding and nested URL parameters do not
# provide an escape hatch.
_BENCHMARK_RE = re.compile(
    r"(?:"
    r"\bbrowse\s*[._/-]?\s*comp(?:arison)?(?:\s*[._/-]?\s*plus)?(?![a-z0-9])"
    r"|\bbrowsecomp(?:[._/-]?plus)?(?![a-z0-9])"
    r"|\bmm\s*[._/-]?\s*browse\s*[._/-]?\s*comp(?![a-z0-9])"
    r"|\bmmbrowsecomp(?![a-z0-9])"
    r"|\bbc\s*[._/-]?\s*v3(?![a-z0-9])"
    r"|\bbc[._/-]?plus\b"
    r"|\bbc_eval_\d"
    r"|\bweb\s*[._/-]?\s*walker(?![a-z0-9])"
    r"|\bweb\s*[._/-]?\s*sailor(?![a-z0-9])"
    r"|\bweb\s*[._/-]?\s*dancer\s*[._/-]?\s*qwq(?![a-z0-9])"
    r"|\bx[._/-]?\s*bench(?:\s*[._/-]?\s*deep\s*[._/-]?\s*search)?(?![a-z0-9])"
    r"|\bxds(?:\s*[._/-]?\s*(?:deep\s*[._/-]?\s*search|benchmark|bench"
    r"|dataset|eval|answers?|leaderboard|ground\s*[._/-]?\s*truth))?(?![a-z0-9])"
    r"|\bseal\s*[._/-]?\s*(?:0|qa)(?![a-z0-9])"
    r"|\bseal(?:0|qa)(?![a-z0-9])"
    r"|\bvtllms\s*/\s*sealqa\b"
    r"|\bsealqa:[a-f0-9]{8}:"
    r"|\bgaia\s*[._/-]?\s*(?:benchmark|bench|dataset|eval|validation|test|answers?|leaderboard)(?![a-z0-9])"
    r"|\b(?:benchmark|bench|dataset|eval|validation|test|answers?|leaderboard)\s*[._/-]?\s*gaia(?![a-z0-9])"
    r")",
    re.IGNORECASE,
)
_HOSTING_RE = re.compile(
    r"(?:"
    r"\bhugging\s*face\b"
    r"|\bhuggingface(?:\.co)?\b"
    r"|\bhf\.co\b"
    r"|cdn-lfs\.huggingface\.co\b"
    r"|huggingfaceusercontent\.com\b"
    r")",
    re.IGNORECASE,
)

_SEARCH_TOOLS = frozenset({"web_search", "search_server"})
_EXTRACT_TOOLS = frozenset({"web_extract", "fetch_server"})
_BROWSER_RECOVERY_TOOLS = frozenset({"browser_back", "browser_navigate"})
_BROWSER_URL_CHECK_TOOLS = frozenset({
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_press",
    "browser_back",
    "browser_console",
    "browser_cdp",
})
_EXEC_CODE_FILE_ACCESS_RE = re.compile(
    r"(?:"
    r"\bopen\s*\("
    r"|\b(?:Path|pathlib\.Path)\s*\("
    r"|\b(?:os|shutil|glob)\s*\."
    r"|\bsubprocess\s*\."
    r"|\bfrom\s+hermes_tools\s+import\s+(?:read_file|search_files|terminal)\b"
    r"|\bimport\s+hermes_tools\b"
    r"|\bread_file\s*\("
    r"|\bsearch_files\s*\("
    r"|\bterminal\s*\("
    r")",
    re.IGNORECASE,
)
_quarantined_browser_sessions: set[tuple[str, str]] = set()
_quarantine_lock = threading.Lock()


def _active() -> bool:
    return bool(os.environ.get(_ACTIVE_ENV, "").strip())


def _normalize_text(value: Any) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            text = str(value)

    # Repeated decoding handles URLs embedded inside encoded query parameters.
    for _ in range(3):
        decoded = html.unescape(unquote_plus(text))
        if decoded == text:
            break
        text = decoded
    return " ".join(text.replace("\\", "/").split())


def _contains_benchmark_material(value: Any) -> bool:
    normalized = _normalize_text(value)
    if _BENCHMARK_RE.search(normalized) or _HOSTING_RE.search(normalized):
        return True
    # Catch simple runtime-string construction such as
    # ``'Browse' + 'Comp'`` and ``['browse', 'comp'].join('')``.
    collapsed = re.sub(r"[\s'\"`+,\[\](){}]", "", normalized)
    return bool(_BENCHMARK_RE.search(collapsed) or _HOSTING_RE.search(collapsed))


def _browser_request_has_network_escape(tool_name: str, args: Any) -> bool:
    args = args if isinstance(args, dict) else {}
    if tool_name == "browser_console" and args.get("expression") is not None:
        expression = _normalize_text(args.get("expression")).lower()
        # Console evaluation remains available for DOM inspection and local
        # computation, but it may not become an unfiltered HTTP client.
        return any(
            marker in expression
            for marker in (
                "fetch",
                "xmlhttprequest",
                "websocket",
                "eventsource",
                "sendbeacon",
                "window.open",
                "createelement",
                "location=",
                "location.href=",
            )
        )
    if tool_name == "browser_cdp":
        method = str(args.get("method") or "").strip().lower()
        return (
            method in {
                "page.navigate",
                "page.getresourcecontent",
                "page.searchinresource",
                "target.createtarget",
                "runtime.evaluate",
                "runtime.callfunctionon",
                "debugger.evaluateoncallframe",
            }
            or method.startswith(("fetch.", "network."))
        )
    return False


def _execute_code_has_file_access(tool_name: str, args: Any) -> bool:
    if tool_name != "execute_code":
        return False
    args = args if isinstance(args, dict) else {}
    code = _normalize_text(args.get("code") or "")
    return bool(_EXEC_CODE_FILE_ACCESS_RE.search(code))


def _failure_result() -> str:
    return json.dumps(
        {"success": False, "error": _BLOCK_MESSAGE},
        ensure_ascii=False,
    )


def _browser_key(session_id: str = "", task_id: str = "") -> tuple[str, str]:
    run_id = os.environ.get(_ACTIVE_ENV, "").strip()
    return (str(session_id or run_id), str(task_id or run_id))


def _is_quarantined(key: tuple[str, str]) -> bool:
    with _quarantine_lock:
        return key in _quarantined_browser_sessions


def _set_quarantined(key: tuple[str, str], value: bool) -> None:
    with _quarantine_lock:
        if value:
            _quarantined_browser_sessions.add(key)
        else:
            _quarantined_browser_sessions.discard(key)


def _request_material(tool_name: str, args: Any) -> Any:
    args = args if isinstance(args, dict) else {}
    if tool_name in _SEARCH_TOOLS:
        return {"query": args.get("query"), "queries": args.get("queries")}
    if tool_name in _EXTRACT_TOOLS:
        return args.get("urls") or args.get("url")
    if tool_name == "browser_navigate":
        return args.get("url")
    if tool_name == "browser_type":
        return args.get("text") or args.get("value")
    if tool_name in {"browser_console", "browser_cdp"}:
        return args
    if tool_name == "vision_analyze":
        return args
    return None


def _on_pre_tool_call(
    tool_name: str = "",
    args: Any = None,
    session_id: str = "",
    task_id: str = "",
    **_: Any,
) -> dict[str, str] | None:
    if not _active():
        return None

    key = _browser_key(session_id, task_id)
    if (
        tool_name.startswith("browser_")
        and _is_quarantined(key)
        and tool_name not in _BROWSER_RECOVERY_TOOLS
    ):
        return {"action": "block", "message": _BLOCK_MESSAGE}

    if _browser_request_has_network_escape(tool_name, args):
        return {"action": "block", "message": _BLOCK_MESSAGE}

    if _execute_code_has_file_access(tool_name, args):
        return {"action": "block", "message": _BLOCK_MESSAGE}

    material = _request_material(tool_name, args)
    if material is not None and _contains_benchmark_material(material):
        return {"action": "block", "message": _BLOCK_MESSAGE}
    return None


def _filter_candidate_lists(value: Any) -> tuple[Any, int, int]:
    """Remove blocked web result/doc entries, returning value/removed/kept."""
    if not isinstance(value, dict):
        return value, 0, 0

    removed = 0
    kept = 0
    output: dict[str, Any] = {}
    for key, child in value.items():
        if key in {"web", "results", "documents"} and isinstance(child, list):
            filtered = []
            for item in child:
                if _contains_benchmark_material(item):
                    removed += 1
                else:
                    filtered.append(item)
                    kept += 1
            output[key] = filtered
            continue
        if isinstance(child, dict):
            nested, nested_removed, nested_kept = _filter_candidate_lists(child)
            output[key] = nested
            removed += nested_removed
            kept += nested_kept
        else:
            output[key] = child
    return output, removed, kept


def _filter_web_result(result: str) -> str | None:
    if not _contains_benchmark_material(result):
        return None
    try:
        parsed = json.loads(result)
    except (TypeError, ValueError):
        # Wrapped/non-JSON results cannot be selectively sanitized safely.
        return _failure_result()

    filtered, removed, kept = _filter_candidate_lists(parsed)
    if not removed:
        return _failure_result()
    if kept == 0:
        return _failure_result()
    if _contains_benchmark_material(filtered):
        # A marker outside the result/document lists (for example a benchmark
        # query echoed in metadata) must not be sent back to the model.
        return _failure_result()
    return json.dumps(filtered, ensure_ascii=False)


def _result_succeeded(result: str) -> bool:
    try:
        parsed = json.loads(result)
    except (TypeError, ValueError):
        return bool(re.search(r'"success"\s*:\s*true', result, re.IGNORECASE))
    return isinstance(parsed, dict) and parsed.get("success") is True


def _current_browser_url(task_id: str) -> str:
    """Read the post-action URL without re-entering the model tool hooks."""
    try:
        from tools.browser_tool import _last_session_key, _run_browser_command

        session_key = _last_session_key(task_id or "default")
        result = _run_browser_command(
            session_key,
            "eval",
            ["window.location.href"],
            timeout=10,
        )
        if not isinstance(result, dict) or not result.get("success"):
            return ""
        value = (result.get("data") or {}).get("result", "")
        if not isinstance(value, str):
            return ""
        return value.strip().strip('"').strip("'")
    except Exception:
        # The result-content check remains active if a backend cannot report
        # its current URL (for example, a cloud backend without agent-browser).
        return ""


def _on_transform_tool_result(
    tool_name: str = "",
    result: Any = None,
    session_id: str = "",
    task_id: str = "",
    **_: Any,
) -> str | None:
    if not _active() or not isinstance(result, str):
        return None

    if tool_name in _SEARCH_TOOLS or tool_name in _EXTRACT_TOOLS:
        return _filter_web_result(result)

    key = _browser_key(session_id, task_id)
    if tool_name.startswith("browser_"):
        current_url = ""
        if tool_name in _BROWSER_URL_CHECK_TOOLS and _result_succeeded(result):
            current_url = _current_browser_url(task_id)
        if _contains_benchmark_material(result) or (
            current_url and _contains_benchmark_material(current_url)
        ):
            _set_quarantined(key, True)
            return _failure_result()
        if tool_name in _BROWSER_RECOVERY_TOOLS:
            _set_quarantined(key, False)
        return None

    if tool_name == "vision_analyze":
        if _contains_benchmark_material(result):
            return _failure_result()
    return None


def _on_session_end(session_id: str = "", task_id: str = "", **_: Any) -> None:
    if not _active():
        return
    _set_quarantined(_browser_key(session_id, task_id), False)


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("transform_tool_result", _on_transform_tool_result)
    ctx.register_hook("on_session_end", _on_session_end)
