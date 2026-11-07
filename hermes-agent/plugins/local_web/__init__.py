"""local-web — bundled plugin overriding web_search / web_extract.

Ships two internal SenseTime backends as *tool overrides* rather than as
registry-level providers. Rationale: v2026.7.1's `check_web_api_key()` and
`_is_backend_available()` in tools/web_tools.py hard-code an 8-entry
legacy whitelist, so registering third-party providers through the
web_search_registry does not surface the tools in `hermes tools`.
Overriding the tools themselves — an officially supported PluginContext
mechanism (`register_tool(..., override=True)`) — sidesteps that gate
cleanly.

Design notes
------------
- `kind: standalone`: we don't want the plugin loader to enumerate our
  providers on behalf of the (buggy) gate. We register everything by hand
  in `register(ctx)`.
- Bundled plugins are auto-trusted for tool override
  (`PluginContext._tool_override_allowed`, line 458), so no
  `plugins.entries.local-web.allow_tool_override: true` opt-in is needed.
- Handlers are **thin adapters**:
    * web_search: interrupt-check → provider.search() → JSON envelope.
      (Old provider already returns the exact envelope Hermes expects.)
    * web_extract: replicates tools.web_tools.web_extract_tool wrapper
      logic verbatim (secret filter, SSRF filter, base64 image
      placeholder conversion, head+tail truncation, field trimming) but
      swaps the backend-dispatch step for a direct provider.extract()
      call. Everything else — including the wrapper's return shape — is
      byte-identical, so the model's schema expectations stay intact.
"""

from __future__ import annotations

import json
import logging
from typing import List

from tools.web_tools import WEB_SEARCH_SCHEMA, WEB_EXTRACT_SCHEMA

from plugins.local_web.search_provider import LocalWebSearchProvider
from plugins.local_web.fetch_provider import LocalWebFetchProvider

logger = logging.getLogger(__name__)

# Instantiate once — providers are stateless and read config.yaml on each
# call, so a shared instance is safe and cheap.
_SEARCH = LocalWebSearchProvider()
_FETCH = LocalWebFetchProvider()


# ---------------------------------------------------------------------------
# web_search — thin wrapper
# ---------------------------------------------------------------------------

def _search_check() -> bool:
    """Available iff the search provider has enough config to run."""
    try:
        return _SEARCH.is_available()
    except Exception:  # noqa: BLE001 — check_fn must never raise
        return False


def _handle_search(args: dict, **_) -> str:
    """Blocking (sync) handler — matches official web_search registration."""
    from tools.interrupt import is_interrupted

    query = str(args.get("query", "") or "")
    limit = args.get("limit", 5)
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        limit = 5

    if is_interrupted():
        return json.dumps({"success": False, "error": "Interrupted"}, ensure_ascii=False)

    try:
        envelope = _SEARCH.search(query, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("local-web search failed")
        return json.dumps({"success": False, "error": f"web_search error: {exc}"}, ensure_ascii=False)

    return json.dumps(envelope, ensure_ascii=False)


# ---------------------------------------------------------------------------
# web_extract — replicates tools.web_tools.web_extract_tool wrapper 1:1
#               (only the backend-dispatch step is replaced with the local-web
#                provider's async extract()).
# ---------------------------------------------------------------------------

def _extract_check() -> bool:
    try:
        return _FETCH.is_available()
    except Exception:  # noqa: BLE001
        return False


async def _handle_extract(args: dict, **_) -> str:
    from tools.web_tools import (
        normalize_url_for_request,
        sensitive_query_param_name,
        async_is_safe_url,
        convert_base64_images_to_links,
        _truncate_with_footer,
        _get_extract_char_limit,
        DEFAULT_EXTRACT_CHAR_LIMIT,
        tool_error,
    )
    from agent.redact import _PREFIX_RE
    from urllib.parse import unquote

    raw_urls = args.get("urls", []) or []
    if not isinstance(raw_urls, list):
        raw_urls = []
    raw_urls = [u for u in raw_urls[:5] if isinstance(u, str)]
    char_limit = args.get("char_limit")

    # 1) Secret filter (URL-encoded + decoded forms)
    normalized_urls: List[str] = []
    for _url in raw_urls:
        normalized_url = normalize_url_for_request(_url)
        if (
            _PREFIX_RE.search(_url)
            or _PREFIX_RE.search(unquote(_url))
            or _PREFIX_RE.search(normalized_url)
            or _PREFIX_RE.search(unquote(normalized_url))
        ):
            return json.dumps({
                "success": False,
                "error": (
                    "Blocked: URL contains what appears to be an API key or "
                    "token. Secrets must not be sent in URLs."
                ),
            })
        sensitive_query_key = sensitive_query_param_name(normalized_url)
        if sensitive_query_key:
            return json.dumps({
                "success": False,
                "error": (
                    "Blocked: URL contains a credential-like query parameter "
                    f"({sensitive_query_key}). Web extract backends are third-party "
                    "readers; remove the sensitive query parameter or use a local "
                    "browser session when this access is explicitly required."
                ),
            })
        normalized_urls.append(normalized_url)

    # 2) SSRF filter
    safe_urls: List[str] = []
    ssrf_blocked: List[dict] = []
    for url in normalized_urls:
        if not await async_is_safe_url(url):
            ssrf_blocked.append({
                "url": url, "title": "", "content": "",
                "error": "Blocked: URL targets a private or internal network address",
            })
        else:
            safe_urls.append(url)

    # 3) Dispatch to local-web provider (bypasses backend registry entirely)
    try:
        if safe_urls:
            results = await _FETCH.extract(safe_urls, format="markdown")
        else:
            results = []
    except Exception as exc:  # noqa: BLE001
        logger.exception("local-web extract failed")
        return tool_error(f"Error extracting content: {exc}")

    if ssrf_blocked:
        results = ssrf_blocked + list(results)

    response = {"results": results}

    # 4) Char-limit clamp (2000..500000; defaults to config or 15000)
    effective_char_limit = char_limit if char_limit is not None else _get_extract_char_limit()
    try:
        effective_char_limit = max(2000, min(int(effective_char_limit), 500_000))
    except (TypeError, ValueError):
        effective_char_limit = DEFAULT_EXTRACT_CHAR_LIMIT

    # 5) Per-result: base64→placeholder, head+tail truncate w/ footer
    for result in response.get("results", []):
        if result.get("error"):
            continue
        url = result.get("url", "")
        raw_content = result.get("raw_content", "") or result.get("content", "")
        if not raw_content:
            continue
        clean = convert_base64_images_to_links(raw_content)
        model_text, _ = _truncate_with_footer(clean, url, effective_char_limit)
        result["content"] = model_text

    # 6) Trim to {url, title, content, error} (+ blocked_by_policy if present)
    trimmed_results = [
        {
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "content": r.get("content", ""),
            "error": r.get("error"),
            **({"blocked_by_policy": r["blocked_by_policy"]} if "blocked_by_policy" in r else {}),
        }
        for r in response.get("results", [])
    ]
    trimmed_response = {"results": trimmed_results}

    if trimmed_response.get("results") == []:
        result_json = tool_error("Content was inaccessible or not found")
    else:
        result_json = json.dumps(trimmed_response, indent=2, ensure_ascii=False)

    # 7) Belt-and-suspenders base64 sweep on serialized JSON
    return convert_base64_images_to_links(result_json)


# ---------------------------------------------------------------------------
# Plugin entrypoint
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Override web_search / web_extract with local-web backend handlers.

    Registered with ``override=True`` — bundled plugins are auto-trusted
    for this by ``PluginContext._tool_override_allowed``, so no operator
    opt-in is required.
    """
    ctx.register_tool(
        name="web_search",
        toolset="web",
        schema=WEB_SEARCH_SCHEMA,
        handler=_handle_search,
        check_fn=_search_check,
        requires_env=[],
        emoji="🔍",
        override=True,
    )
    ctx.register_tool(
        name="web_extract",
        toolset="web",
        schema=WEB_EXTRACT_SCHEMA,
        handler=_handle_extract,
        check_fn=_extract_check,
        requires_env=[],
        is_async=True,
        emoji="📄",
        override=True,
    )
    logger.info("local-web: overrode web_search + web_extract with local-web backends")
