"""search_server — HTTP ``/search`` backend for Hermes web_search.

This provider mirrors the search behavior from
``mcp_tools.tools.deepresearch.search_rl.SearchTool``:

    Hermes web_search(query) -> POST {endpoint}
    Serper-style {"organic": [...]} -> Hermes {"data": {"web": [...]}}
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List
from urllib.parse import urlparse

import httpx

from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)


def _read_search_server_cfg() -> Dict[str, Any]:
    """Read ``web.search_server`` from Hermes config."""
    try:
        from hermes_cli.config import load_config

        cfg = (load_config() or {}).get("web", {}).get("search_server", {}) or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not read web.search_server: %s", exc)
        cfg = {}

    endpoint = (
        os.getenv("SEARCH_SERVER_ENDPOINT", "").strip()
        or str(cfg.get("endpoint", "") or "").strip()
    )
    base_url = (
        os.getenv("SEARCH_SERVER_BASE_URL", "").strip()
        or str(cfg.get("base_url", "") or "").strip()
    )
    url = os.getenv("SEARCH_SERVER_URL", "").strip() or str(cfg.get("url", "") or "").strip()
    port = int(os.getenv("SEARCH_SERVER_PORT", "") or cfg.get("port", 80) or 80)

    return {
        "endpoint": _build_endpoint(endpoint, base_url, url, port),
        "base_url": base_url,
        "url": url,
        "port": int(os.getenv("SEARCH_SERVER_PORT", "") or cfg.get("port", 80) or 80),
        "api_key": (
            os.getenv("SEARCH_SERVER_API_KEY", "").strip()
            or str(cfg.get("api_key", "") or "").strip()
        ),
        "timeout": float(cfg.get("timeout", 30.0) or 30.0),
        "max_retries": max(1, int(cfg.get("max_retries", 3) or 3)),
        "retry_delay": float(cfg.get("retry_delay", 2.0) or 2.0),
    }


def _build_endpoint(endpoint: str, base_url: str, url: str, port: int) -> str:
    if endpoint:
        return endpoint.rstrip("/")
    if base_url:
        return _with_search_path(base_url)
    if not url:
        return ""

    parsed = urlparse(url)
    if parsed.scheme:
        return _with_search_path(url)
    return f"http://{url}:{port}/search"


def _with_search_path(value: str) -> str:
    value = value.rstrip("/")
    parsed = urlparse(value)
    if parsed.path.rstrip("/").endswith("/search"):
        return value
    return f"{value}/search"


def _payload(query: str) -> Dict[str, str]:
    if any("\u4E00" <= char <= "\u9FFF" for char in query):
        return {"q": query, "location": "China", "gl": "cn", "hl": "zh-cn"}
    return {"q": query, "location": "United States", "gl": "us", "hl": "en"}


def _parse_search_text(text: str, limit: int) -> List[Dict[str, Any]]:
    """Parse search_rl.py's formatted text into Hermes web_search rows."""
    rows: List[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None
    snippet_lines: List[str] = []
    in_snippet = False

    def flush() -> None:
        nonlocal current, snippet_lines, in_snippet
        if current is None:
            return
        current["description"] = "\n".join(snippet_lines).strip()
        if current.get("url") or current.get("title") or current.get("description"):
            current["position"] = len(rows) + 1
            rows.append(current)
        current = None
        snippet_lines = []
        in_snippet = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("[ID]:"):
            flush()
            current = {"title": "", "url": "", "description": ""}
            continue
        if current is None:
            continue
        if line.startswith("[Title]:"):
            current["title"] = line.split(":", 1)[1].strip()
            in_snippet = False
            continue
        if line.startswith("[URL]:"):
            current["url"] = line.split(":", 1)[1].strip()
            in_snippet = False
            continue
        if line.startswith("[Snippet]:"):
            in_snippet = True
            after = line.split(":", 1)[1].strip()
            if after:
                snippet_lines.append(after)
            continue
        if in_snippet:
            snippet_lines.append(line)

    flush()
    return rows[: max(1, int(limit))]


def _normalize_search_data(data: Any, limit: int) -> List[Dict[str, Any]]:
    """Accept mcp_tools search output variants and return Hermes web rows."""
    safe_limit = max(1, int(limit))
    if isinstance(data, str):
        return _parse_search_text(data, safe_limit)

    if isinstance(data, dict):
        if isinstance(data.get("web"), list):
            return data["web"][:safe_limit]
        if isinstance(data.get("organic"), list):
            source = data["organic"]
        elif isinstance(data.get("results"), list):
            source = data["results"]
        elif isinstance(data.get("text"), list):
            source = data["text"]
        else:
            result = data.get("result")
            if isinstance(result, str):
                return _parse_search_text(result, safe_limit)
            source = []
    elif isinstance(data, list):
        source = data
    else:
        source = []

    rows = []
    for index, item in enumerate(source[:safe_limit]):
        if not isinstance(item, dict):
            continue
        rows.append({
            "title": str(item.get("title", "")),
            "url": str(item.get("url") or item.get("link") or ""),
            "description": str(item.get("description") or item.get("snippet") or ""),
            "position": int(item.get("position") or index + 1),
        })
    return rows


class SearchServerProvider(WebSearchProvider):
    """Web-search provider backed by a SearchTool-compatible HTTP service."""

    @property
    def name(self) -> str:
        return "search_server"

    @property
    def display_name(self) -> str:
        return "Search Server"

    def is_available(self) -> bool:
        cfg = _read_search_server_cfg()
        return bool(cfg["endpoint"])

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return False

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        cfg = _read_search_server_cfg()
        if not cfg["endpoint"]:
            return {
                "success": False,
                "error": (
                    "web.search_server endpoint is not configured "
                    "(set endpoint, base_url, or url+port)"
                ),
            }
        if not cfg["api_key"]:
            return {
                "success": False,
                "error": (
                    "Search API key is not configured "
                    "(set web.search_server.api_key or SEARCH_SERVER_API_KEY)"
                ),
            }

        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": cfg["api_key"],
        }

        last_error = ""
        for attempt in range(1, cfg["max_retries"] + 1):
            try:
                response = httpx.post(
                    cfg["endpoint"],
                    headers=headers,
                    json=_payload(query),
                    timeout=cfg["timeout"],
                    trust_env=False,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("success") is False:
                    return {
                        "success": False,
                        "error": str(data.get("error") or "search_server returned success=false"),
                    }
                web = _normalize_search_data(data.get("data", data), limit)

                logger.info(
                    "search_server '%s': %d results",
                    query,
                    len(web),
                )
                return {"success": True, "data": {"web": web}}

            except httpx.TimeoutException as exc:
                last_error = f"timeout: {exc}"
                logger.warning("search_server timeout on attempt %d: %s", attempt, exc)
            except httpx.HTTPStatusError as exc:
                last_error = f"HTTP {exc.response.status_code}: {exc.response.text}"
                logger.warning("search_server HTTP error on attempt %d: %s", attempt, last_error)
            except httpx.RequestError as exc:
                last_error = f"request error: {exc}"
                logger.warning("search_server request error on attempt %d: %s", attempt, exc)
            except json.JSONDecodeError as exc:
                last_error = f"bad JSON: {exc}"
                logger.warning("search_server JSON error on attempt %d: %s", attempt, exc)

            if attempt < cfg["max_retries"]:
                time.sleep(cfg["retry_delay"])

        return {
            "success": False,
            "error": f"search_server failed after {cfg['max_retries']} attempts: {last_error}",
        }

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Search Server",
            "badge": "HTTP search",
            "tag": "Calls a SearchTool-compatible POST /search endpoint. Configure web.search_server.*.",
            "env_vars": [
                {
                    "key": "SEARCH_SERVER_URL",
                    "prompt": "Search server host/IP, base URL, or set SEARCH_SERVER_ENDPOINT",
                    "url": "",
                },
                {
                    "key": "SEARCH_SERVER_PORT",
                    "prompt": "Search server port",
                    "url": "",
                },
                {
                    "key": "SEARCH_SERVER_API_KEY",
                    "prompt": "Search server API key",
                    "url": "",
                },
            ],
        }
