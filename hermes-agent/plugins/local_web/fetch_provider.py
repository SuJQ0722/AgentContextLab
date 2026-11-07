"""local-web-fetch — HTTP client for an internal Reader HTTP Server.

Delegates all fetching / extraction / summarization to a companion
``fetch_server`` (see /mnt/afs_agents/pangcong/workspace/projects/fetch_server)
that exposes a Jina-Reader–compatible HTTP API. This provider only speaks
its ``POST /fetch`` endpoint — everything else (Trafilatura extraction,
Jina fallback for PDF/Office/image URLs, LLM Markdown summarization,
per-request proxy rotation, blocked-domain filtering) is the server's
responsibility.

The provider preserves ``name = "local-web-fetch"`` so users with
``web.extract_backend: local-web-fetch`` in their config.yaml don't need
to change anything when this plugin is updated in-place.

Configuration
-------------

``~/.hermes/config.yaml``::

    web:
      local_web:
        fetch:
          fetch_server:
            base_url:      "http://<host>:8080"   # required
            extract_mode:  "markdown"             # or "text"; default "markdown"
            timeout:       180.0                  # per-URL HTTP timeout (seconds)
            max_concurrent: 5                     # client-side concurrency cap
            jina_api_key:  "jina_..."             # required by server for PDF /
                                                  #   non-HTML Jina fallback
            llm_base_url:  "https://.../v1"       # required in markdown mode
            llm_model:     "..."                  # required in markdown mode
            llm_api_key:   "sk-..."               # optional; omit for no auth

Environment overrides (keep the "secrets-in-env" convention already used
by SERPER_API_KEY / JINA_API_KEY in the local-web search provider):

- ``FETCH_SERVER_URL``  overrides ``base_url``
- ``JINA_API_KEY``      overrides ``jina_api_key``
- ``LLM_API_KEY``       overrides ``llm_api_key``

Wire behavior (POST /fetch)
---------------------------

Per URL, one JSON request::

    POST {base_url}/fetch
    Content-Type: application/json
    {
      "url":          <target url>,
      "extractMode":  "markdown" | "text",
      "jina_api_key": <jina key or "">,
      "llm_base_url": <llm base url>,        # markdown mode only
      "llm_model":    <llm model>,           # markdown mode only
      "llm_api_key":  <llm key or "">,       # optional
    }

    → {"success": bool, "data": <string>, "error": null | <string>}

Note: no ``query`` is sent. The fetch_server, on receiving an empty
``query``, uses its built-in general-Markdown-summary system prompt
(see LLM_GENERAL_SUMMARY_SYSTEM_PROMPT in server.py) — we get a full,
non-targeted Markdown summary without ever surfacing a query parameter
to the model or the tool schema.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

_DEFAULT_EXTRACT_MODE = "markdown"
_DEFAULT_TIMEOUT_SECONDS = 180.0
_DEFAULT_MAX_CONCURRENT = 8


def _read_fetch_cfg() -> Dict[str, Any]:
    """Read ``web.local_web.fetch.fetch_server`` from hermes config.yaml.

    Missing config loader / missing section → empty defaults; callers
    surface a per-URL error rather than raising.
    """
    try:
        from hermes_cli.config import load_config

        raw = (
            (load_config() or {})
            .get("web", {})
            .get("local_web", {})
            .get("fetch", {})
            .get("fetch_server", {})
        ) or {}
    except Exception as exc:  # noqa: BLE001 — config read is best-effort
        logger.debug("Could not read web.local_web.fetch.fetch_server: %s", exc)
        raw = {}

    extract_mode = str(raw.get("extract_mode", _DEFAULT_EXTRACT_MODE) or _DEFAULT_EXTRACT_MODE).strip().lower()
    if extract_mode not in {"markdown", "text"}:
        extract_mode = _DEFAULT_EXTRACT_MODE

    try:
        timeout = float(raw.get("timeout", _DEFAULT_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT_SECONDS

    try:
        max_concurrent = int(raw.get("max_concurrent", _DEFAULT_MAX_CONCURRENT))
        if max_concurrent < 1:
            max_concurrent = _DEFAULT_MAX_CONCURRENT
    except (TypeError, ValueError):
        max_concurrent = _DEFAULT_MAX_CONCURRENT

    base_url = str(raw.get("base_url", "") or "").strip().rstrip("/")

    return {
        "base_url":       base_url,
        "extract_mode":   extract_mode,
        "timeout":        timeout,
        "max_concurrent": max_concurrent,
        "jina_api_key":   str(raw.get("jina_api_key", "") or "").strip(),
        "llm_base_url":   str(raw.get("llm_base_url", "") or "").strip(),
        "llm_model":      str(raw.get("llm_model", "") or "").strip(),
        "llm_api_key":    str(raw.get("llm_api_key", "") or "").strip(),
    }


def _apply_env_overrides(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Env vars override in-config secrets/endpoints."""
    env_base = os.getenv("FETCH_SERVER_URL", "").strip()
    if env_base:
        cfg["base_url"] = env_base.rstrip("/")
    env_jina = os.getenv("JINA_API_KEY", "").strip()
    if env_jina:
        cfg["jina_api_key"] = env_jina
    env_llm_key = os.getenv("LLM_API_KEY", "").strip()
    if env_llm_key:
        cfg["llm_api_key"] = env_llm_key
    return cfg


# ---------------------------------------------------------------------------
# provider
# ---------------------------------------------------------------------------

class LocalWebFetchProvider(WebSearchProvider):
    """Web-extract provider that forwards each URL to an internal fetch_server."""

    @property
    def name(self) -> str:
        # Stable identifier — keep "local-web-fetch" for backward compat
        # with users who already set web.extract_backend to this value.
        return "local-web-fetch"

    @property
    def display_name(self) -> str:
        return "Reader HTTP Server (internal fetch_server)"

    def is_available(self) -> bool:
        """Ready iff base_url is configured (env or config).

        Deliberately loose: markdown-mode requests may still fail at the
        server if ``llm_base_url`` / ``llm_model`` are missing, but that
        surfaces per-URL rather than gating the tool off entirely — same
        pattern as the search provider (see search_provider).
        """
        cfg = _apply_env_overrides(_read_fetch_cfg())
        return bool(cfg["base_url"])

    def supports_search(self) -> bool:
        return False

    def supports_extract(self) -> bool:
        return True

    async def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        """Fetch + (optionally) summarize each URL via fetch_server.

        Parameters
        ----------
        urls
            Target URLs (already SSRF-filtered by the caller wrapper).
        **kwargs
            Accepted for interface parity with WebSearchProvider.extract.
            Ignored — we don't expose ``query`` or ``format`` overrides here.

        Returns
        -------
        List[Dict[str, Any]]
            One dict per input URL, in the same shape hermes' upstream
            ``web_extract_tool`` wrapper expects::

                {"url": str, "title": str, "content": str,
                 "raw_content": str, "metadata": dict,
                 # only on failure:
                 "error": str}

            ``title`` is always ``""`` — fetch_server doesn't return one.
            The wrapper tolerates missing titles.
        """
        cfg = _apply_env_overrides(_read_fetch_cfg())

        if not cfg["base_url"]:
            return [_error_result(u, "web.local_web.fetch.fetch_server.base_url is not configured") for u in urls]

        # Markdown mode requires an LLM endpoint. Surface it early with a
        # clear per-URL error instead of letting the server 400.
        if cfg["extract_mode"] == "markdown" and (not cfg["llm_base_url"] or not cfg["llm_model"]):
            return [
                _error_result(
                    u,
                    "markdown mode requires web.local_web.fetch.fetch_server.llm_base_url "
                    "and llm_model to be set (or switch extract_mode to 'text')",
                )
                for u in urls
            ]

        endpoint = f"{cfg['base_url']}/fetch"
        sem = asyncio.Semaphore(cfg["max_concurrent"])

        # One shared client for the whole batch — connection reuse.
        async with httpx.AsyncClient(timeout=cfg["timeout"]) as client:
            tasks = [_fetch_one(client, sem, endpoint, url, cfg) for url in urls]
            return await asyncio.gather(*tasks)

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Reader HTTP Server (internal fetch_server)",
            "badge": "internal · markdown · summarize",
            "tag": (
                "POSTs each URL to a companion fetch_server that runs "
                "Trafilatura + Jina fallback + LLM Markdown summarization. "
                "Configure endpoints/keys under web.local_web.fetch.fetch_server "
                "in config.yaml (FETCH_SERVER_URL / JINA_API_KEY / LLM_API_KEY env vars override)."
            ),
            "env_vars": [
                {
                    "key": "FETCH_SERVER_URL",
                    "prompt": "Base URL of the internal fetch_server (overrides base_url)",
                    "url": "",
                },
                {
                    "key": "JINA_API_KEY",
                    "prompt": "Jina Reader API key (used by fetch_server for PDF/non-HTML fallback)",
                    "url": "https://jina.ai/",
                },
                {
                    "key": "LLM_API_KEY",
                    "prompt": "LLM API key for the summarization backend (optional)",
                    "url": "",
                },
            ],
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _error_result(url: str, msg: str) -> Dict[str, Any]:
    """Uniform per-URL error dict that matches the upstream wrapper's
    expected shape (see ``tools/web_tools.py::web_extract_tool``)."""
    return {
        "url": url,
        "title": "",
        "content": "",
        "raw_content": "",
        "metadata": {},
        "error": msg,
    }


def _build_payload(url: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Build the POST /fetch body. No ``query`` — fetch_server defaults to
    the general-Markdown-summary system prompt when query is empty."""
    payload: Dict[str, Any] = {
        "url": url,
        "extractMode": cfg["extract_mode"],
    }
    # Only include optional fields when non-empty so we don't send stray
    # empty strings as if they were meaningful settings.
    if cfg["jina_api_key"]:
        payload["jina_api_key"] = cfg["jina_api_key"]
    if cfg["extract_mode"] == "markdown":
        payload["llm_base_url"] = cfg["llm_base_url"]
        payload["llm_model"] = cfg["llm_model"]
        if cfg["llm_api_key"]:
            payload["llm_api_key"] = cfg["llm_api_key"]
    return payload


async def _fetch_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    endpoint: str,
    url: str,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """One POST /fetch call with semaphore-bounded concurrency."""
    payload = _build_payload(url, cfg)

    async with sem:
        try:
            resp = await client.post(endpoint, json=payload)
        except httpx.TimeoutException as exc:
            return _error_result(url, f"fetch_server timeout after {cfg['timeout']:.0f}s: {exc}")
        except httpx.RequestError as exc:
            return _error_result(url, f"fetch_server unreachable: {exc}")
        except Exception as exc:  # noqa: BLE001 — defensive
            return _error_result(url, f"fetch_server error: {exc}")

        # Server returned *something*. Try to parse; be forgiving of odd
        # error payloads (FastAPI 4xx/5xx typically returns {"detail": ...}).
        try:
            body = resp.json()
        except ValueError:
            return _error_result(
                url,
                f"fetch_server returned non-JSON (HTTP {resp.status_code}): {resp.text[:200]}",
            )

        if resp.status_code >= 400:
            detail = _extract_error_message(body) or f"HTTP {resp.status_code}"
            return _error_result(url, f"fetch_server error: {detail}")

        if not isinstance(body, dict):
            return _error_result(url, f"fetch_server returned unexpected JSON: {str(body)[:200]}")

        if not body.get("success"):
            return _error_result(url, body.get("error") or "fetch_server returned success=false")

        content = str(body.get("data") or "")
        logger.info(
            "fetch_server %s (%s, %d chars)",
            url,
            cfg["extract_mode"],
            len(content),
        )
        return {
            "url": url,
            "title": "",           # fetch_server does not return a title
            "content": content,
            "raw_content": content,
            "metadata": {},
        }


def _extract_error_message(body: Any) -> Optional[str]:
    """Pull a readable error out of common FastAPI/handler shapes."""
    if isinstance(body, dict):
        for key in ("error", "detail", "message"):
            val = body.get(key)
            if isinstance(val, str) and val.strip():
                return val
            if val is not None:
                return str(val)
    return None
