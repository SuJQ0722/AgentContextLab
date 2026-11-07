#!/usr/bin/env python3
"""Reverse image search via Serper Google Lens."""

from __future__ import annotations

import base64
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from tools.path_security import validate_within_dir
from tools.registry import registry, tool_error, tool_result
from tools.url_safety import is_safe_url

logger = logging.getLogger(__name__)

SERPER_LENS_ENDPOINT = "https://google.serper.dev/lens"
IMGBB_ENDPOINT = "https://api.imgbb.com/1/upload"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_TOP_K = 10
_MAX_IMAGE_BYTES = 32 * 1024 * 1024


def _serper_api_key() -> str:
    return (os.getenv("SERP_API_KEY") or os.getenv("SERPER_API_KEY") or "").strip()


def _imgbb_key() -> str:
    return (os.getenv("IMAGE_UPLOAD_API_KEY") or "").strip()


def _allowed_roots() -> list[Path]:
    raw = (os.getenv("HERMES_IMAGE_ROOT") or "").strip()
    roots = [Path(part).expanduser().resolve() for part in raw.split(os.pathsep) if part.strip()]
    return roots or [Path.cwd().resolve()]


def _validate_local_image_path(path: Path) -> Optional[str]:
    errors = [validate_within_dir(path, root) for root in _allowed_roots()]
    if any(error is None for error in errors):
        return None
    roots = ", ".join(str(root) for root in _allowed_roots())
    return f"image_path escapes allowed root(s): {roots}"


def _cos_config() -> Optional[Dict[str, str]]:
    cfg = {
        "region": os.getenv("COS_REGION", "").strip(),
        "bucket": os.getenv("COS_BUCKET", "").strip(),
        "secret_id": os.getenv("COS_SECRET_ID", "").strip(),
        "secret_key": os.getenv("COS_SECRET_KEY", "").strip(),
        "endpoint": os.getenv("COS_ENDPOINT", "").strip(),
    }
    return cfg if all(cfg[k] for k in ("region", "bucket", "secret_id", "secret_key")) else None


def _oss_config() -> Optional[Dict[str, str]]:
    cfg = {
        "access_key_id": os.getenv("OSS_ACCESS_KEY_ID", "").strip(),
        "access_key_secret": os.getenv("OSS_ACCESS_KEY_SECRET", "").strip(),
        "endpoint": os.getenv("OSS_ENDPOINT", "").strip(),
        "bucket": os.getenv("OSS_BUCKET_NAME", "").strip(),
    }
    return cfg if all(cfg.values()) else None


def check_image_search_requirements() -> bool:
    return bool(_serper_api_key())


def _upload_imgbb(local_path: Path) -> Optional[str]:
    key = _imgbb_key()
    if not key:
        return None
    try:
        img_b64 = base64.b64encode(local_path.read_bytes()).decode("ascii")
        resp = requests.post(
            IMGBB_ENDPOINT,
            data={"key": key, "image": img_b64},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return str(resp.json()["data"]["url"])
    except Exception as exc:
        logger.warning("imgBB upload failed: %s", exc)
        return None


def _upload_cos(local_path: Path) -> Optional[str]:
    cfg = _cos_config()
    if cfg is None:
        return None
    try:
        from qcloud_cos import CosConfig, CosS3Client  # type: ignore
    except Exception as exc:
        logger.debug("qcloud_cos not installed: %s", exc)
        return None
    try:
        client = CosS3Client(
            CosConfig(
                Region=cfg["region"],
                SecretId=cfg["secret_id"],
                SecretKey=cfg["secret_key"],
                Endpoint=cfg.get("endpoint") or None,
            )
        )
        key = f"/uploads/{uuid.uuid4().hex}_{local_path.name}"
        with local_path.open("rb") as f:
            client.put_object(Bucket=cfg["bucket"], Body=f, Key=key, ACL="public-read")
        return f"https://{cfg['bucket']}.cos.{cfg['region']}.myqcloud.com{key}"
    except Exception as exc:
        logger.warning("COS upload failed: %s", exc)
        return None


def _upload_oss(local_path: Path) -> Optional[str]:
    cfg = _oss_config()
    if cfg is None:
        return None
    try:
        import oss2  # type: ignore
    except Exception as exc:
        logger.debug("oss2 not installed: %s", exc)
        return None
    try:
        auth = oss2.Auth(cfg["access_key_id"], cfg["access_key_secret"])
        bucket = oss2.Bucket(auth, cfg["endpoint"], cfg["bucket"])
        key = f"uploads/{uuid.uuid4().hex}_{local_path.name}"
        bucket.put_object_from_file(key, str(local_path))
        host = cfg["endpoint"].replace("https://", "").replace("http://", "")
        return f"https://{cfg['bucket']}.{host}/{key}"
    except Exception as exc:
        logger.warning("OSS upload failed: %s", exc)
        return None


def _upload_to_public_host(local_path: Path) -> Optional[str]:
    for upload in (_upload_imgbb, _upload_cos, _upload_oss):
        url = upload(local_path)
        if url:
            return url
    return None


def _download_image(image_url: str, tmp_dir: Path) -> Optional[Path]:
    if not is_safe_url(image_url):
        return None
    tmp = tmp_dir / f"{uuid.uuid4().hex}.bin"
    try:
        resp = requests.get(image_url, timeout=DEFAULT_TIMEOUT_SECONDS, stream=True)
        resp.raise_for_status()
        total = 0
        with tmp.open("wb") as f:
            for chunk in resp.iter_content(64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > _MAX_IMAGE_BYTES:
                    tmp.unlink(missing_ok=True)
                    return None
                f.write(chunk)
        return tmp if tmp.stat().st_size > 0 else None
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        logger.warning("Failed to download image: %s", exc)
        return None


def _resolve_image_input(image_url: str, image_path: str, image_base64: str, tmp_dir: Path) -> Optional[Path]:
    if image_url:
        return _download_image(image_url, tmp_dir)
    if image_path:
        path = Path(os.path.expanduser(image_path)).resolve()
        error = _validate_local_image_path(path)
        if error:
            logger.warning("%s", error)
            return None
        return path if path.is_file() else None
    if image_base64:
        try:
            data = base64.b64decode(image_base64.split(",", 1)[-1], validate=False)
        except Exception as exc:
            logger.warning("Failed to decode image_base64: %s", exc)
            return None
        if len(data) > _MAX_IMAGE_BYTES:
            return None
        tmp = tmp_dir / f"{uuid.uuid4().hex}.bin"
        tmp.write_bytes(data)
        return tmp
    return None


def _call_serper_lens(image_url: str, top_k: int, timeout: int, max_attempts: int) -> Optional[List[Dict[str, str]]]:
    headers = {"X-API-KEY": _serper_api_key(), "Content-Type": "application/json"}
    payload = {"url": image_url}
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            resp = requests.post(SERPER_LENS_ENDPOINT, headers=headers, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            results: List[Dict[str, str]] = []
            kg = data.get("knowledgeGraph")
            if isinstance(kg, dict) and kg.get("title"):
                results.append(
                    {
                        "title": kg.get("title") or "",
                        "link": kg.get("link") or "",
                        "source": "Knowledge Graph",
                        "description": kg.get("description") or "",
                    }
                )
            for item in (data.get("organic") or [])[:top_k]:
                results.append(
                    {
                        "title": item.get("title") or "Untitled",
                        "link": item.get("link") or "",
                        "source": item.get("source") or "",
                        "thumbnail_url": item.get("thumbnailUrl") or "",
                    }
                )
            for result in results:
                if result.get("link") and not is_safe_url(result["link"]):
                    result["link"] = ""
            return results
        except Exception as exc:
            last_error = exc
            logger.warning("Serper Lens attempt %s/%s failed: %s", attempt + 1, max_attempts, exc)
            if attempt < max_attempts - 1:
                time.sleep(1.0 * (attempt + 1))
    logger.error("Serper Lens failed after retries: %s", last_error)
    return None


def _format_lens_results(results: List[Dict[str, str]]) -> str:
    if not results:
        return "No matching images were found in reverse image search."
    parts = ["Reverse Image Search Results:"]
    for idx, item in enumerate(results, start=1):
        entry = f"{idx}. {item.get('title') or 'Untitled'}"
        if item.get("source"):
            entry += f"\n   Source: {item['source']}"
        if item.get("description"):
            entry += f"\n   {item['description']}"
        if item.get("link"):
            entry += f"\n   Link: {item['link']}"
        parts.append(entry)
    return "\n\n".join(parts)


def image_search_tool(
    image_url: str = "",
    image_path: str = "",
    image_base64: str = "",
    top_k: int = DEFAULT_TOP_K,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> str:
    if not (image_url or image_path or image_base64):
        return tool_error("Provide image_url, image_path, or image_base64.")
    if not _serper_api_key():
        return tool_error("SERP_API_KEY or SERPER_API_KEY is required for reverse image search.")

    top_k = max(1, min(int(top_k or DEFAULT_TOP_K), 20))
    timeout = max(5, int(timeout_seconds or DEFAULT_TIMEOUT_SECONDS))
    attempts = max(1, int(max_attempts or DEFAULT_MAX_ATTEMPTS))

    tmp_dir = Path(os.getenv("HERMES_IMAGE_CACHE") or "/tmp/hermes-image-search")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    cleanup_path: Optional[Path] = None

    try:
        if image_url and not image_path and not image_base64:
            if not is_safe_url(image_url):
                return tool_error(f"Blocked unsafe image URL: {image_url}")
            public_url = image_url
        else:
            local = _resolve_image_input(image_url, image_path, image_base64, tmp_dir)
            if local is None:
                return tool_error("Could not load the provided image.")
            cleanup_path = local if local.parent == tmp_dir else None
            public_url = _upload_to_public_host(local)
            if not public_url:
                return tool_error(
                    "No image-hosting backend configured for local/base64 input. "
                    "Set IMAGE_UPLOAD_API_KEY, COS_* or OSS_* credentials, or pass image_url directly."
                )

        if not is_safe_url(public_url):
            return tool_error(f"Image URL failed safety check: {public_url}")
        results = _call_serper_lens(public_url, top_k=top_k, timeout=timeout, max_attempts=attempts)
        if results is None:
            return tool_error("Serper reverse image search failed after retries.")
        return tool_result(
            success=True,
            provider="serper",
            tool="image_search",
            image_url=public_url,
            num_results=len(results),
            answer=_format_lens_results(results),
            results=results,
        )
    finally:
        if cleanup_path is not None:
            cleanup_path.unlink(missing_ok=True)


IMAGE_SEARCH_SCHEMA = {
    "name": "image_search",
    "description": (
        "Reverse image search via Serper Google Lens. Use to identify objects, people, "
        "locations, products, original sources, or visually similar images on the web."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "image_url": {"type": "string", "description": "Public HTTP(S) URL of the image to look up."},
            "image_path": {"type": "string", "description": "Local image path under HERMES_IMAGE_ROOT."},
            "image_base64": {"type": "string", "description": "Raw base64-encoded image bytes."},
            "top_k": {"type": "integer", "description": "Maximum number of results to return.", "default": DEFAULT_TOP_K},
        },
        "required": [],
    },
}


def _handle_image_search(args: Dict[str, Any], **_kw: Any) -> str:
    return image_search_tool(
        image_url=str(args.get("image_url") or "").strip(),
        image_path=str(args.get("image_path") or "").strip(),
        image_base64=str(args.get("image_base64") or "").strip(),
        top_k=int(args.get("top_k") or DEFAULT_TOP_K),
    )


registry.register(
    name="image_search",
    toolset="vision",
    schema=IMAGE_SEARCH_SCHEMA,
    handler=_handle_image_search,
    check_fn=check_image_search_requirements,
    requires_env=["SERP_API_KEY"],
    emoji="image",
    max_result_size_chars=60_000,
)
