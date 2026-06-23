"""search_server plugin — HTTP search backend for web_search."""

from __future__ import annotations

from plugins.web.search_server.provider import SearchServerProvider


def register(ctx) -> None:
    """Register the search_server provider with the plugin context."""
    ctx.register_web_search_provider(SearchServerProvider())
