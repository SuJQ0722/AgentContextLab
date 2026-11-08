#!/usr/bin/env python3
"""Loopback, text-only deployment of the SHA-pinned shared ReaderEngine.

Uses our public deployment config and request-scoped Jina credentials. It never
loads the upstream owner's config.yaml and cannot dispatch model summaries.
"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
from contextlib import asynccontextmanager
from contextvars import ContextVar


def install_cache_observer(upstream):
    """Observe request-local fetch metadata without changing extraction/cache policy."""
    current = ContextVar('acl_reader_cache_observation', default=None)
    original_fetch = upstream.fetch_async
    original_read = upstream.ReaderEngine.read
    original_jina = upstream.ReaderEngine._fetch_with_jina

    async def fetch_observed(*args, **kwargs):
        state = current.get()
        before = len(state.get('lookups', [])) if state is not None else 0
        result = await original_fetch(*args, **kwargs)
        if state is not None:
            metadata = getattr(result, 'metadata', None)
            cached = metadata.get('from_cache') if isinstance(metadata, dict) else None
            # Fresh responses omit from_cache. A completed cache.get returning
            # None supplies actual miss evidence, without a second lookup.
            lookups = state.get('lookups', [])[before:]
            if not isinstance(cached, bool) and lookups and all(value is False for value in lookups):
                cached = False
            state['primary'].append(cached if isinstance(cached, bool) else None)
        return result

    async def read_observed(self, *args, **kwargs):
        result = await original_read(self, *args, **kwargs)
        state = current.get()
        if state is not None and result[1]:
            state['backend'] = 'primary-html'
            state['cached'] = state['primary'][-1] if state['primary'] else None
        return result

    async def jina_observed(self, *args, **kwargs):
        result = await original_jina(self, *args, **kwargs)
        state = current.get()
        if state is not None and result and result.strip():
            state['backend'] = 'jina'
            state['cached'] = None
        return result

    upstream.fetch_async = fetch_observed
    upstream.ReaderEngine.read = read_observed
    upstream.ReaderEngine._fetch_with_jina = jina_observed
    return current


def observe_cache_lookups(cache, current):
    """Observe the existing cache get exactly once, retaining miss/exception truth."""
    if cache is None:
        return
    original = cache.get

    def get(url):
        state = current.get()
        try:
            value = original(url)
        except BaseException:
            if state is not None:
                state.setdefault('lookups', []).append(None)
            raise
        if state is not None:
            state.setdefault('lookups', []).append(value is not None)
        return value
    cache.get = get


def cache_headers(state, success):
    """Only a final successful primary result can expose a known X-Cached."""
    backend = state['backend'] if success else None
    result = {'X-ACL-Fetch-Backend': backend or 'unknown',
              'X-ACL-Cache-Layer': 'fetch_url_package.content_cache' if backend == 'primary-html' else 'unknown'}
    if backend == 'primary-html' and isinstance(state['cached'], bool):
        result['X-Cached'] = 'true' if state['cached'] else 'false'
    primary = state['primary'][-1] if state['primary'] else None
    if isinstance(primary, bool):
        result['X-ACL-Primary-Cache'] = 'true' if primary else 'false'
    return result


def build_app(config):
    source = Path(config["source_path"]).resolve()
    if hashlib.sha256(source.read_bytes()).hexdigest() != config["source_sha256"]:
        raise RuntimeError("Shared Reader source changed; review and version the source pin")
    sys.path.insert(0, str(source.parent))
    upstream = importlib.import_module(source.stem)
    if Path(upstream.__file__).resolve() != source:
        raise RuntimeError("Reader source import resolved to an unexpected module")
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    observation = install_cache_observer(upstream)

    async def no_summary(*args, **kwargs):
        raise RuntimeError("Model summaries are forbidden in the text-only Reader service")
    upstream.LLMSummaryService.summarize = no_summary

    @asynccontextmanager
    async def lifespan(app):
        upstream.engine = upstream.ReaderEngine(upstream.ServerConfig(
            max_concurrent_requests=config["max_concurrent_requests"],
            extract_workers=config["extract_workers"], max_length=config["max_length"],
            fetch_timeout=config["fetch_timeout"], cache_size=config["cache_size"],
            default_extract_mode="text", proxy=None,
        ))
        observe_cache_lookups(upstream.engine.fetch_config.content_cache, observation)
        yield
        await upstream.engine.cleanup()

    app = FastAPI(title="AgentContextLab pinned Reader text v1", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok", "implementation": "reader-text-v1", "source_sha256": config["source_sha256"], "mode": "text", "model_inference": False}

    @app.get("/stats")
    async def stats():
        return upstream.get_engine().stats.get_stats()

    async def fetch(req):
        if req.extract_mode != "text" or req.llm_base_url or req.llm_model or req.llm_api_key:
            raise HTTPException(status_code=400, detail="This service accepts only explicit text mode without LLM fields")
        state = {'primary': [], 'backend': None, 'cached': None}
        token = observation.set(state)
        try:
            result = await upstream.fetch(req, authorization=None)
            return JSONResponse(result.model_dump(), headers=cache_headers(state, result.success))
        finally:
            observation.reset(token)
    # Set the original request type without importing owner settings.
    fetch.__annotations__["req"] = upstream.FetchRequest
    app.post("/fetch", response_model=upstream.FetchResponse)(fetch)
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if config["host"] not in ("127.0.0.1", "::1"):
        raise ValueError("Text Reader must listen only on loopback")
    import uvicorn
    uvicorn.run(build_app(config), host=config["host"], port=config["port"], access_log=False)


if __name__ == "__main__":
    main()
