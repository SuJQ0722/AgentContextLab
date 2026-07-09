"""local-web search — Serper through an internal cache proxy.

Hits a Serper.dev-compatible cache proxy (transparent X-API-KEY forwarder)
directly via httpx. No dependency on any external SDK — this provider
stands on its own.

Used only by the ``local-web`` plugin as the backend for the overridden
``web_search`` tool. Not registered with the web-search registry, so its
``name`` attribute below is internal-only.

Configuration
-------------

Fields under ``~/.hermes/config.yaml``::

    web:
      local_web:
        search:
          url: "10.120.6.133"        # cache proxy host
          port: 80                   # cache proxy port
          api_key: "fb58..."         # forwarded as X-API-KEY

``SERPER_API_KEY`` env var, when set, **overrides** ``api_key`` from
config.yaml. This lets the operator rotate keys without editing config
(matches the secrets-in-env convention while keeping the in-config
default convenient).

The endpoint URL is composed at call time as ``f"http://{url}:{port}/search"``.

Wire protocol
-------------

POST http://{url}:{port}/search
Headers:  X-API-KEY: <api_key>, Content-Type: application/json
Body:     {"q": query, "location": "China"/"United States",
           "gl": "cn"/"us", "hl": "zh-cn"/"en"}
            (zh switch driven by any U+4E00–U+9FFF in the query)
Response: standard Serper.dev shape — {"organic": [{"title","snippet","link"}]}
Cache headers (from proxy): X-Cached, X-Success, X-Error
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

import httpx

from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)


def _contains_chinese(text: str) -> bool:
    """Return True if *text* contains any CJK Unified Ideograph (U+4E00–U+9FFF)."""
    return any("一" <= c <= "鿿" for c in text)


def _read_http_search() -> Dict[str, Any]:
    """Read ``web.local_web.search`` from hermes config.yaml.

    Returns a dict with three keys: ``url``, ``port``, ``api_key``. Any key
    not present in config.yaml falls back to whatever is in DEFAULT_CONFIG
    (deep-merged by ``load_config``). Returns an empty dict if the config
    loader is unavailable.
    """
    try:
        from hermes_cli.config import load_config

        cfg = (
            (load_config() or {})
            .get("web", {})
            .get("local_web", {})
            .get("search", {})
        ) or {}
        return {
            "url": str(cfg.get("url", "")).strip(),
            "port": cfg.get("port", 0),
            "api_key": str(cfg.get("api_key", "")).strip(),
        }
    except Exception as exc:  # noqa: BLE001 — config read is best-effort
        logger.debug("Could not read web.local_web.search: %s", exc)
        return {"url": "", "port": 0, "api_key": ""}


def _resolve_api_key(cfg: Dict[str, Any]) -> str:
    """SERPER_API_KEY env var overrides config; otherwise use config.api_key."""
    env_key = os.getenv("SERPER_API_KEY", "").strip()
    if env_key:
        return env_key
    return str(cfg.get("api_key", "") or "").strip()


class LocalWebSearchProvider(WebSearchProvider):
    """Web-search provider that calls an internal Serper cache proxy."""

    @property
    def name(self) -> str:
        # Stable identifier — keep "local-web-search" for backward compat
        # with users who already set web.search_backend to this value.
        return "local-web-search"

    @property
    def display_name(self) -> str:
        return "Serper (internal cache proxy)"

    def is_available(self) -> bool:
        """Return True when url + port + (env_key or config_key) are all set.

        Cheap — runs on every ``hermes tools`` paint and at registration time.
        Must not make any network calls.
        """
        cfg = _read_http_search()
        if not cfg["url"] or not cfg["port"]:
            return False
        return bool(_resolve_api_key(cfg))

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return False

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Execute one search against the internal Serper cache proxy.

        Returns the Hermes search-response envelope. Per the
        :class:`WebSearchProvider` contract::

            success:  {"success": True, "data": {"web": [{title,url,description,position}, ...]}}
            failure:  {"success": False, "error": str}
        """
        cfg = _read_http_search()
        if not cfg["url"]:
            return {
                "success": False,
                "error": "web.local_web.search.url is not configured",
            }
        if not cfg["port"]:
            return {
                "success": False,
                "error": "web.local_web.search.port is not configured",
            }
        api_key = _resolve_api_key(cfg)
        if not api_key:
            return {
                "success": False,
                "error": (
                    "Serper API key is not configured "
                    "(set web.local_web.search.api_key or SERPER_API_KEY env var)"
                ),
            }

        endpoint = f"http://{cfg['url']}:{cfg['port']}/search"

        # Language-aware payload — language-aware Serper.dev payload.
        if _contains_chinese(query):
            payload = {"q": query, "location": "China", "gl": "cn", "hl": "zh-cn"}
        else:
            payload = {
                "q": query,
                "location": "United States",
                "gl": "us",
                "hl": "en",
            }

        try:
            resp = httpx.post(
                endpoint,
                content=json.dumps(payload),
                headers={
                    "X-API-KEY": api_key,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Serper cache HTTP %s: %s",
                exc.response.status_code,
                exc,
            )
            return {
                "success": False,
                "error": f"Serper proxy returned HTTP {exc.response.status_code}",
            }
        except httpx.RequestError as exc:
            logger.warning("Serper cache request error: %s", exc)
            return {"success": False, "error": f"Could not reach Serper proxy: {exc}"}
        except json.JSONDecodeError as exc:
            return {"success": False, "error": f"Bad JSON from Serper proxy: {exc}"}

        # Serper.dev returns results under "organic"; truncate to caller-requested limit.
        safe_limit = max(1, int(limit))
        organic = (data.get("organic") or [])[:safe_limit]

        web = [
            {
                "title": str(r.get("title", "")),
                "url": str(r.get("link", "")),
                "description": str(r.get("snippet", "")),
                "position": i + 1,
            }
            for i, r in enumerate(organic)
            if isinstance(r, dict)
        ]
        logger.info(
            "local-web-search '%s': %d results (cached=%s)",
            query,
            len(web),
            resp.headers.get("X-Cached", "?"),
        )
        return {"success": True, "data": {"web": web}}

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Serper (internal cache proxy)",
            "badge": "internal · cache · search only",
            "tag": (
                "Serper.dev through your internal cache proxy. "
                "Configure host/port/api_key under web.local_web.search "
                "in config.yaml (SERPER_API_KEY env var overrides api_key)."
            ),
            "env_vars": [
                {
                    "key": "SERPER_API_KEY",
                    "prompt": "Serper API key (overrides web.local_web.search.api_key)",
                    "url": "https://serper.dev/",
                },
            ],
        }
