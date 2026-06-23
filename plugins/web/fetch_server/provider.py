"""fetch_server — Reader HTTP Server backend for Hermes web_extract.

This provider calls the HTTP service documented in:
``/mnt/afs_agents/pangcong/workspace/mcp_tools/fetch_server/README.md``.

It uses ``POST /fetch`` so LLM and Jina settings can be passed per request.
By default the provider requests ``extractMode: text``; that keeps Hermes'
existing ``web_extract`` auxiliary summarization path in charge and avoids
requiring LLM credentials until the user chooses to fill them in.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List

import httpx

from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)


def _read_fetch_server_cfg() -> Dict[str, Any]:
    """Read ``web.fetch_server`` from Hermes config."""
    try:
        from hermes_cli.config import load_config

        cfg = (load_config() or {}).get("web", {}).get("fetch_server", {}) or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not read web.fetch_server: %s", exc)
        cfg = {}

    base_url = (
        os.getenv("FETCH_SERVER_BASE_URL", "").strip()
        or os.getenv("FETCH_SERVER_URL", "").strip()
        or str(cfg.get("base_url") or cfg.get("url") or "http://localhost:8080").strip()
    )
    extract_mode = str(cfg.get("extract_mode") or "text").strip().lower()
    if extract_mode not in {"text", "markdown"}:
        extract_mode = "text"

    return {
        "base_url": base_url.rstrip("/"),
        "extract_mode": extract_mode,
        "timeout": float(cfg.get("timeout", 180.0) or 180.0),
        "max_concurrent": max(1, int(cfg.get("max_concurrent", 5) or 5)),
        "jina_api_key": (
            os.getenv("FETCH_SERVER_JINA_API_KEY", "").strip()
            or os.getenv("JINA_API_KEY", "").strip()
            or str(cfg.get("jina_api_key", "") or "").strip()
        ),
        "llm_base_url": (
            os.getenv("FETCH_SERVER_LLM_BASE_URL", "").strip()
            or str(cfg.get("llm_base_url", "") or "").strip()
        ),
        "llm_model": (
            os.getenv("FETCH_SERVER_LLM_MODEL", "").strip()
            or str(cfg.get("llm_model", "") or "").strip()
        ),
        "llm_api_key": (
            os.getenv("FETCH_SERVER_LLM_API_KEY", "").strip()
            or str(cfg.get("llm_api_key", "") or "").strip()
        ),
    }


def _payload_for_url(url: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "url": url,
        "extractMode": cfg["extract_mode"],
    }
    if cfg["jina_api_key"]:
        payload["jina_api_key"] = cfg["jina_api_key"]
    if cfg["llm_base_url"]:
        payload["llm_base_url"] = cfg["llm_base_url"]
    if cfg["llm_model"]:
        payload["llm_model"] = cfg["llm_model"]
    if cfg["llm_api_key"]:
        payload["llm_api_key"] = cfg["llm_api_key"]
    return payload


async def _fetch_one(
    client: httpx.AsyncClient,
    endpoint: str,
    url: str,
    cfg: Dict[str, Any],
    sem: asyncio.Semaphore,
) -> Dict[str, Any]:
    async with sem:
        try:
            response = await client.post(endpoint, json=_payload_for_url(url, cfg))
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("fetch_server request failed for %s: %s", url, exc)
            return {
                "url": url,
                "title": "",
                "content": "",
                "raw_content": "",
                "error": f"fetch_server request failed: {exc}",
            }

        if not data.get("success"):
            return {
                "url": url,
                "title": "",
                "content": "",
                "raw_content": "",
                "error": str(data.get("error") or "fetch_server returned success=false"),
            }

        content = str(data.get("data") or "")
        if not content.strip():
            return {
                "url": url,
                "title": "",
                "content": "",
                "raw_content": "",
                "error": "fetch_server returned empty content",
            }

        return {
            "url": url,
            "title": "",
            "content": content,
            "raw_content": content,
            "metadata": {
                "source": "fetch_server",
                "extract_mode": cfg["extract_mode"],
            },
        }


class FetchServerProvider(WebSearchProvider):
    """Web-extract provider backed by the Reader HTTP Server."""

    @property
    def name(self) -> str:
        return "fetch_server"

    @property
    def display_name(self) -> str:
        return "Fetch Server"

    def is_available(self) -> bool:
        return bool(_read_fetch_server_cfg()["base_url"])

    def supports_search(self) -> bool:
        return False

    def supports_extract(self) -> bool:
        return True

    async def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        if isinstance(urls, str):
            url_list = [urls]
        else:
            url_list = list(urls or [])

        if not url_list:
            return []

        cfg = _read_fetch_server_cfg()
        if not cfg["base_url"]:
            return [
                {
                    "url": url,
                    "title": "",
                    "content": "",
                    "raw_content": "",
                    "error": "web.fetch_server.base_url is not configured",
                }
                for url in url_list
            ]

        endpoint = f"{cfg['base_url']}/fetch"
        sem = asyncio.Semaphore(cfg["max_concurrent"])
        async with httpx.AsyncClient(timeout=cfg["timeout"]) as client:
            return await asyncio.gather(
                *(_fetch_one(client, endpoint, url, cfg, sem) for url in url_list)
            )

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Fetch Server",
            "badge": "HTTP extract",
            "tag": "Reader HTTP Server via POST /fetch. Configure web.fetch_server.*.",
            "env_vars": [
                {
                    "key": "FETCH_SERVER_BASE_URL",
                    "prompt": "Fetch Server base URL",
                    "url": "",
                },
                {
                    "key": "FETCH_SERVER_JINA_API_KEY",
                    "prompt": "Jina API key for fetch_server fallback",
                    "url": "https://jina.ai/reader/",
                },
                {
                    "key": "FETCH_SERVER_LLM_BASE_URL",
                    "prompt": "OpenAI-compatible LLM base URL for markdown mode",
                    "url": "",
                },
                {
                    "key": "FETCH_SERVER_LLM_MODEL",
                    "prompt": "LLM model name for markdown mode",
                    "url": "",
                },
                {
                    "key": "FETCH_SERVER_LLM_API_KEY",
                    "prompt": "LLM API key for markdown mode",
                    "url": "",
                },
            ],
        }
