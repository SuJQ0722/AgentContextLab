"""fetch_server plugin — Reader HTTP Server backend for web_extract."""

from __future__ import annotations

from plugins.web.fetch_server.provider import FetchServerProvider


def register(ctx) -> None:
    """Register the fetch_server provider with the plugin context."""
    ctx.register_web_search_provider(FetchServerProvider())
