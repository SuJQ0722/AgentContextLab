import pytest


def _ensure_search_fetch_plugins_loaded():
    from hermes_cli.plugins import _ensure_plugins_discovered
    from tools.registry import invalidate_check_fn_cache

    _ensure_plugins_discovered()
    invalidate_check_fn_cache()


def test_search_fetch_server_config_is_top_level_not_web():
    from hermes_cli.config import DEFAULT_CONFIG, OPTIONAL_ENV_VARS

    assert "search_server" in DEFAULT_CONFIG
    assert "fetch_server" in DEFAULT_CONFIG
    assert "search_server" not in DEFAULT_CONFIG["web"]
    assert "fetch_server" not in DEFAULT_CONFIG["web"]
    assert DEFAULT_CONFIG["search_server"]["port"] == 80
    assert DEFAULT_CONFIG["fetch_server"]["base_url"] == ""
    assert DEFAULT_CONFIG["fetch_server"]["extract_mode"] == "text"
    assert OPTIONAL_ENV_VARS["SEARCH_SERVER_API_KEY"]["tools"] == ["web_search"]
    assert OPTIONAL_ENV_VARS["FETCH_SERVER_BASE_URL"]["tools"] == ["web_extract"]


def test_search_fetch_server_are_web_backends_not_agent_tools():
    _ensure_search_fetch_plugins_loaded()

    from agent.web_search_registry import get_provider
    from tools.registry import registry
    from toolsets import resolve_toolset

    assert registry.get_entry("search_server") is None
    assert registry.get_entry("fetch_server") is None
    assert get_provider("search_server").supports_search() is True
    assert get_provider("search_server").supports_extract() is False
    assert get_provider("fetch_server").supports_search() is False
    assert get_provider("fetch_server").supports_extract() is True
    assert get_provider("mcp-tools-search") is None
    assert get_provider("mcp-tools-fetch") is None
    assert set(resolve_toolset("web")) == {"web_search", "web_extract"}
    assert set(resolve_toolset("search")) == {"web_search"}


def test_search_fetch_server_provider_names_match_backend_config():
    from plugins.web.fetch_server.provider import FetchServerProvider
    from plugins.web.search_server.provider import SearchServerProvider

    assert SearchServerProvider().name == "search_server"
    assert FetchServerProvider().name == "fetch_server"


def test_web_toolset_exposes_stable_agent_tool_names(monkeypatch):
    monkeypatch.setenv("SEARCH_SERVER_ENDPOINT", "http://search.local/search")
    monkeypatch.setenv("SEARCH_SERVER_API_KEY", "secret")
    monkeypatch.setenv("FETCH_SERVER_BASE_URL", "http://fetch.local")
    _ensure_search_fetch_plugins_loaded()

    import model_tools

    tool_defs = model_tools.get_tool_definitions(
        enabled_toolsets=["web", "browser", "terminal", "file", "code_execution"],
        quiet_mode=True,
        skip_tool_search_assembly=True,
    )
    names = {tool["function"]["name"] for tool in tool_defs}

    assert "web_search" in names
    assert "web_extract" in names
    assert "search_server" not in names
    assert "fetch_server" not in names


def test_search_server_provider_posts_to_configured_endpoint(monkeypatch):
    from plugins.web.search_server import provider as search_server

    monkeypatch.setenv("SEARCH_SERVER_ENDPOINT", "http://search.local/search")
    monkeypatch.setenv("SEARCH_SERVER_API_KEY", "secret")

    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "organic": [
                    {"title": "One", "link": "https://one.test", "snippet": "first"},
                    {"title": "Two", "url": "https://two.test", "description": "second"},
                ]
            }

    def fake_post(url, headers=None, json=None, timeout=None, trust_env=None):
        calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
                "trust_env": trust_env,
            }
        )
        return FakeResponse()

    monkeypatch.setattr(search_server.httpx, "post", fake_post)

    result = search_server.SearchServerProvider().search("hello", limit=1)

    assert result["success"] is True
    assert result["data"]["web"] == [
        {
            "title": "One",
            "url": "https://one.test",
            "description": "first",
            "position": 1,
        }
    ]
    assert calls[0]["url"] == "http://search.local/search"
    assert calls[0]["headers"]["X-API-KEY"] == "secret"
    assert calls[0]["json"] == {
        "q": "hello",
        "location": "United States",
        "gl": "us",
        "hl": "en",
    }
    assert calls[0]["trust_env"] is False


def test_search_server_check_requires_endpoint_and_api_key(monkeypatch):
    from plugins.web.search_server import provider as search_server

    monkeypatch.setattr(search_server, "_load_search_server_config", lambda: {})
    monkeypatch.setenv("SEARCH_SERVER_ENDPOINT", "http://search.local/search")
    monkeypatch.delenv("SEARCH_SERVER_API_KEY", raising=False)
    assert search_server.check_search_server_requirements() is False

    monkeypatch.setenv("SEARCH_SERVER_API_KEY", "secret")
    assert search_server.check_search_server_requirements() is True


@pytest.mark.asyncio
async def test_fetch_server_provider_posts_to_fetch_endpoint(monkeypatch):
    from plugins.web.fetch_server import provider as fetch_server

    monkeypatch.setattr(
        fetch_server,
        "_load_fetch_server_config",
        lambda: {"extract_mode": "markdown"},
    )
    monkeypatch.setenv("FETCH_SERVER_BASE_URL", "http://fetch.local")

    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"success": True, "data": "page text"}

    class FakeAsyncClient:
        def __init__(self, timeout=None, trust_env=None):
            self.timeout = timeout
            self.trust_env = trust_env

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, endpoint, json=None):
            calls.append({"endpoint": endpoint, "json": json, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr(fetch_server.httpx, "AsyncClient", FakeAsyncClient)

    result = await fetch_server.FetchServerProvider().extract(
        ["https://example.test"], format="markdown"
    )

    assert result[0]["content"] == "page text"
    assert result[0]["metadata"]["extract_mode"] == "markdown"
    assert calls == [
        {
            "endpoint": "http://fetch.local/fetch",
            "json": {"url": "https://example.test", "extractMode": "markdown"},
            "timeout": 180.0,
        }
    ]
