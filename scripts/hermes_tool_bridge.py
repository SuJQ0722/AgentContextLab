#!/usr/bin/env python3
"""Execute the pinned Hermes tool handlers for a versioned DSH adapter.

One JSON request is read from stdin, one JSON result is written to stdout.
Credentials come only from the environment; no model inference is permitted.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
import uuid
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("web_search", "web_extract", "image_search", "image_crop", "image_zoom_in")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def python_no_proxy(value):
    """DSH/undici adds [::1]; httpx requires the unbracketed bypass literal."""
    entries = []
    for part in value.split(','):
        part = part.strip()
        if part.startswith('[') and part.endswith(']'):
            part = part[1:-1]
        if part and part not in entries:
            entries.append(part)
    return ','.join(entries)


def initialize(workspace):
    """Isolate Hermes state and reuse the exact selected web settings."""
    import yaml
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    settings = json.loads(os.environ.get("ACL_WEB_SECRETS", '{"search":{},"fetch":{}}'))
    home = workspace / ".hermes-tool-bridge"
    home.mkdir(mode=0o700, exist_ok=True)
    config = {"web": {"local_web": {"search": settings["search"], "fetch": {"fetch_server": settings["fetch"]}}}}
    temp = home / ("config-" + uuid.uuid4().hex + ".yaml")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        yaml.safe_dump(config, handle)
    os.replace(temp, home / "config.yaml")
    os.environ["HERMES_HOME"] = str(home)
    os.environ.setdefault("HERMES_IMAGE_ROOT", str(workspace))
    os.environ["HERMES_IMAGE_CACHE"] = str(workspace / "image-cache")
    if settings["search"].get("api_key"):
        os.environ["SERPER_API_KEY"] = settings["search"]["api_key"]
    bypass = [os.environ.get("NO_PROXY", ""), "localhost", "127.0.0.1", "::1",
              str(settings["search"].get("url", "")), urlsplit(settings["fetch"].get("base_url", "")).hostname or ""]
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = python_no_proxy(",".join(x for x in bypass if x))
    os.chdir(workspace)
    sys.path.insert(0, str(ROOT / "hermes-agent"))
    return settings


def handlers():
    from plugins.local_web import _handle_search, _handle_extract, WEB_SEARCH_SCHEMA, WEB_EXTRACT_SCHEMA
    from tools.image_search_tool import _handle_image_search, IMAGE_SEARCH_SCHEMA
    from tools.image_crop_tool import _handle_image_crop, IMAGE_CROP_SCHEMA
    from tools.image_zoom_in_tool import _handle_image_zoom_in, IMAGE_ZOOM_IN_SCHEMA
    return dict(zip(TOOLS, (
        (_handle_search, WEB_SEARCH_SCHEMA), (_handle_extract, WEB_EXTRACT_SCHEMA),
        (_handle_image_search, IMAGE_SEARCH_SCHEMA), (_handle_image_crop, IMAGE_CROP_SCHEMA),
        (_handle_image_zoom_in, IMAGE_ZOOM_IN_SCHEMA))))


def install_transport_audit(metrics, call_id):
    """Record transport outcomes without URLs, headers or credentials."""
    import httpx
    import requests
    metrics = Path(metrics)
    metrics.mkdir(parents=True, exist_ok=True)

    def reject_model(url):
        path = urlsplit(str(url)).path.rstrip("/")
        if path.endswith(("/chat/completions", "/responses", "/messages", "/generate")):
            raise RuntimeError("Model inference is forbidden in the Hermes tool bridge")

    def begin(url):
        transport_id = uuid.uuid4().hex
        with (metrics / "web-starts.jsonl").open("a") as handle:
            handle.write(json.dumps({"call_id": call_id, "transport_id": transport_id,
                "started_unix": time.time(), "path": urlsplit(str(url)).path}) + "\n")
        return transport_id

    def record(url, response, start, error, transport_id):
        path = urlsplit(str(url)).path
        kind = {"/search": "search", "/fetch": "fetch", "/lens": "image_search"}.get(path, "image_transfer")
        row = {"call_id": call_id, "transport_id": transport_id, "kind": kind, "proxy_http_status": getattr(response, "status_code", None),
               "cache_header": response.headers.get("X-Cached") if response is not None else None,
               "cache_layer": response.headers.get("X-ACL-Cache-Layer") if response is not None else None,
               "fetch_backend": response.headers.get("X-ACL-Fetch-Backend") if response is not None else None,
               "primary_cache_header": response.headers.get("X-ACL-Primary-Cache") if response is not None else None,
               "client_http_seconds": time.monotonic() - start, "origin_http_status": None,
               "error_type": type(error).__name__ if error else None,
               "http_success": response is not None and response.status_code < 400}
        with (metrics / "web.jsonl").open("a") as handle:
            handle.write(json.dumps(row) + "\n")

    old_sync, old_async, old_requests = httpx.Client.send, httpx.AsyncClient.send, requests.Session.send

    def send(client, request, *args, **kwargs):
        reject_model(request.url)
        transport_id = begin(request.url)
        start = time.monotonic(); response = None; error = None
        try:
            response = old_sync(client, request, *args, **kwargs)
            return response
        except BaseException as exc:
            error = exc; raise
        finally:
            record(request.url, response, start, error, transport_id)

    async def asend(client, request, *args, **kwargs):
        reject_model(request.url)
        transport_id = begin(request.url)
        start = time.monotonic(); response = None; error = None
        try:
            response = await old_async(client, request, *args, **kwargs)
            return response
        except BaseException as exc:
            error = exc; raise
        finally:
            record(request.url, response, start, error, transport_id)

    def rsend(client, request, *args, **kwargs):
        reject_model(request.url)
        transport_id = begin(request.url)
        start = time.monotonic(); response = None; error = None
        try:
            response = old_requests(client, request, *args, **kwargs)
            return response
        except BaseException as exc:
            error = exc; raise
        finally:
            record(request.url, response, start, error, transport_id)
    httpx.Client.send, httpx.AsyncClient.send, requests.Session.send = send, asend, rsend


def encode_result(raw, destination):
    """Keep Hermes text verbatim and archive native image bytes in content order."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if not isinstance(raw, dict) or not raw.get("_multimodal"):
        text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        return {"content": [{"type": "text", "text": text}], "metadata": {}}
    from PIL import Image
    content = []
    for index, part in enumerate(raw["content"]):
        if part.get("type") == "text":
            content.append({"type": "text", "text": part["text"]})
        elif part.get("type") == "image_url":
            url = part["image_url"]["url"]
            prefix, encoded = url.split(",", 1)
            if not prefix.startswith("data:image/") or not prefix.endswith(";base64"):
                raise ValueError("Hermes tool returned a non-inline image")
            data = base64.b64decode(encoded, validate=True)
            img = Image.open(io.BytesIO(data)); img.load()
            sha = digest(data)
            path = destination / (sha + "." + img.format.lower())
            path.write_bytes(data)
            content.append({"type": "image", "path": str(path), "media_type": prefix[5:-7],
                            "sha256": sha, "pixel_sha256": digest(img.mode.encode() + str(img.size).encode() + img.tobytes()),
                            "width": img.width, "height": img.height, "content_index": index,
                            "detail_present": "detail" in part["image_url"],
                            "detail": part["image_url"].get("detail", "auto")})
        else:
            raise ValueError("Unsupported Hermes multimodal part")
    return {"content": content, "metadata": raw.get("meta", {})}


def apply_result_budget(raw, name, call_id, workspace, context_length=None):
    """Use the same post-handler persistence helper as Hermes tool_executor."""
    if not isinstance(raw, str):
        return raw
    from tools.budget_config import budget_for_context_window
    from tools.tool_result_storage import maybe_persist_tool_result
    budget = budget_for_context_window(context_length)
    if len(raw) <= budget.resolve_threshold(name):
        return raw
    from tools.environments.local import LocalEnvironment
    return maybe_persist_tool_result(raw, name, call_id, env=LocalEnvironment(cwd=str(workspace)), config=budget)


def apply_turn_budget(request, workspace):
    """Project a completed turn with Hermes' aggregate result budget helper."""
    from tools.budget_config import budget_for_context_window
    from tools.tool_result_storage import enforce_turn_budget
    from tools.environments.local import LocalEnvironment
    messages = request.get("messages")
    if not isinstance(messages, list) or any(not isinstance(m, dict) or not isinstance(m.get("content"), (str, list)) for m in messages):
        raise ValueError("tool_budget requires ordered tool messages")
    budget = budget_for_context_window(request.get("context_length"))
    original = digest(json.dumps(messages, ensure_ascii=False).encode())
    result = enforce_turn_budget(messages, env=LocalEnvironment(cwd=str(workspace)), config=budget)
    return {"version": 2, "operation": "tool_budget", "messages": result,
            "input_sha256": original, "output_sha256": digest(json.dumps(result, ensure_ascii=False).encode()),
            "turn_budget_chars": budget.turn_budget}


def resolve_origin_arguments(arguments):
    """Use a verified original download URL; never substitute a crop's parent."""
    manifest = os.environ.get("ACL_IMAGE_ORIGIN_MAP")
    if not manifest or arguments.get("image_url") or arguments.get("image_base64") or not arguments.get("image_path"):
        return arguments, None
    from tools.image_search_tool import _validate_local_image_path
    path = Path(arguments["image_path"]).expanduser().resolve()
    if _validate_local_image_path(path):
        return arguments, None
    rows = json.loads(Path(manifest).read_text()).get("images", [])
    for row in rows:
        if row.get("kind") != "native_original" or Path(row["path"]).resolve() != path:
            continue
        if not path.is_file() or digest(path.read_bytes()) != row.get("sha256"):
            raise ValueError("Original image bytes no longer match the download ledger")
        if row.get("transformed", False) or not str(row.get("origin_url", "")).startswith(("https://", "http://")):
            raise ValueError("Only unmodified downloaded originals can resolve to an origin URL")
        resolved = {**arguments, "image_url": row["origin_url"], "image_path": ""}
        return resolved, {"path": str(path), "sha256": row["sha256"], "origin_url": row["origin_url"], "kind": "native_original"}
    return arguments, None


def execute(request, workspace, settings):
    if request.get("operation") == "tool_budget":
        return apply_turn_budget(request, workspace)
    name = request.get("tool")
    if name not in TOOLS or not isinstance(request.get("arguments"), dict):
        raise ValueError("Expected a supported tool and an arguments object")
    if name == "web_extract" and str(settings["fetch"].get("extract_mode", "markdown")).strip().lower() != "text":
        raise RuntimeError("Reader mode can invoke an LLM; explicit text mode is required for this no-model bridge")
    call_id = digest(str(request.get("call_id") or uuid.uuid4()).encode())[:24]
    destination = Path(workspace) / "tool-results" / call_id
    destination.mkdir(parents=True, exist_ok=True)
    install_transport_audit(Path(workspace) / "metrics", call_id)
    start = time.monotonic()
    handler, _ = handlers()[name]
    arguments, origin = resolve_origin_arguments(request["arguments"]) if name == "image_search" else (request["arguments"], None)
    raw = handler(arguments)
    if asyncio.iscoroutine(raw):
        raw = asyncio.run(raw)
    raw = apply_result_budget(raw, name, str(request.get("call_id") or call_id), workspace,
                              int(os.environ.get("ACL_CONTEXT_WINDOW", "0")) or None)
    result = {"version": 2, "tool": name, "call_id": request.get("call_id"),
              "handler_seconds": time.monotonic() - start, **encode_result(raw, destination)}
    if origin:
        result["metadata"]["origin_resolution"] = origin
    (destination / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--describe", action="store_true")
    args = parser.parse_args()
    # Imports may log status; stdout is reserved for the IPC result.
    with contextlib.redirect_stdout(sys.stderr):
        settings = initialize(args.workspace)
        result = {"version": 2, "tools": [pair[1] for pair in handlers().values()]} if args.describe else execute(json.load(sys.stdin), args.workspace.resolve(), settings)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
