#!/usr/bin/env python3
"""Crop and super-resolve a region of an image for closer visual inspection."""

from __future__ import annotations

import base64
import io
import logging
import math
import os
import uuid
from math import ceil, floor
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

from tools.path_security import validate_within_dir
from tools.registry import registry, tool_error
from tools.url_safety import is_safe_url

logger = logging.getLogger(__name__)

MIN_DIMENSION = 28
DEFAULT_MIN_PIXELS = 65_536
DEFAULT_MAX_PIXELS = 3_686_400
DEFAULT_SR_SCALE = 4
DEFAULT_DOWNLOAD_TIMEOUT = 30
_MAX_IMAGE_BYTES = 32 * 1024 * 1024

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    _CV2_AVAILABLE = True
except Exception:
    _CV2_AVAILABLE = False


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


def _load_pil_image(image_url: str, image_path: str, image_base64: str, tmp_dir: Path) -> Tuple[Optional[Any], str, Optional[Path]]:
    try:
        from PIL import Image  # type: ignore
    except Exception as exc:
        return None, f"Pillow is required: {exc}", None

    if image_url:
        if not is_safe_url(image_url):
            return None, f"Blocked unsafe image URL: {image_url}", None
        tmp = tmp_dir / f"{uuid.uuid4().hex}.bin"
        try:
            resp = requests.get(image_url, timeout=DEFAULT_DOWNLOAD_TIMEOUT, stream=True)
            resp.raise_for_status()
            total = 0
            with tmp.open("wb") as f:
                for chunk in resp.iter_content(64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > _MAX_IMAGE_BYTES:
                        tmp.unlink(missing_ok=True)
                        return None, "Image exceeds size cap", None
                    f.write(chunk)
            return Image.open(tmp).convert("RGB"), image_url, tmp
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            return None, f"Failed to download image: {exc}", None

    if image_path:
        path = Path(os.path.expanduser(image_path)).resolve()
        error = _validate_local_image_path(path)
        if error:
            return None, error, None
        if not path.is_file():
            return None, f"image_path not a file: {path}", None
        try:
            return Image.open(path).convert("RGB"), str(path), None
        except Exception as exc:
            return None, f"Failed to open image_path: {exc}", None

    if image_base64:
        try:
            data = base64.b64decode(image_base64.split(",", 1)[-1], validate=False)
        except Exception as exc:
            return None, f"Invalid image_base64: {exc}", None
        if len(data) > _MAX_IMAGE_BYTES:
            return None, "image_base64 exceeds size cap", None
        tmp = tmp_dir / f"{uuid.uuid4().hex}.bin"
        try:
            tmp.write_bytes(data)
            return Image.open(tmp).convert("RGB"), "image_base64", tmp
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            return None, f"Failed to decode image_base64: {exc}", None

    return None, "Provide image_url, image_path, or image_base64", None


def _pil_to_data_url(img: Any, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    mime = "image/png" if fmt.upper() == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{encoded}"


def _validate_bbox(left: float, top: float, right: float, bottom: float) -> bool:
    if not (left < right and top < bottom):
        return False
    height, width = bottom - top, right - left
    if min(height, width) == 0:
        return False
    return max(height, width) / min(height, width) <= 100


def _maybe_resize_bbox(bbox_2d: list[float], image_width: int, image_height: int) -> Optional[list[int]]:
    left, top, right, bottom = bbox_2d
    left = max(0.0, float(left))
    top = max(0.0, float(top))
    right = min(float(image_width), float(right))
    bottom = min(float(image_height), float(bottom))
    if not _validate_bbox(left, top, right, bottom):
        return None

    height, width = bottom - top, right - left
    current = [left, top, right, bottom]
    if height < MIN_DIMENSION or width < MIN_DIMENSION:
        cx, cy = (left + right) / 2.0, (top + bottom) / 2.0
        ratio = MIN_DIMENSION / min(height, width)
        target_w, target_h = width * ratio, height * ratio
        if target_w > image_width:
            scale = image_width / target_w
            target_w, target_h = image_width, target_h * scale
        if target_h > image_height:
            scale = image_height / target_h
            target_h, target_w = image_height, target_w * scale

        new_left = max(0.0, cx - target_w / 2.0)
        new_top = max(0.0, cy - target_h / 2.0)
        if new_left + target_w > image_width:
            new_left = image_width - target_w
        if new_top + target_h > image_height:
            new_top = image_height - target_h
        current = [floor(new_left), floor(new_top), ceil(new_left + target_w), ceil(new_top + target_h)]

    final_left, final_top, final_right, final_bottom = current
    if not _validate_bbox(final_left, final_top, final_right, final_bottom):
        return None
    if (floor(final_bottom) - floor(final_top)) < MIN_DIMENSION or (floor(final_right) - floor(final_left)) < MIN_DIMENSION:
        return None
    return [int(final_left), int(final_top), int(final_right), int(final_bottom)]


def _apply_super_resolution(image: Any, scale: int) -> tuple[Any, str]:
    from PIL import Image  # type: ignore

    factor = max(2, int(scale or DEFAULT_SR_SCALE))
    model_path = (os.getenv("SR_MODEL_PATH") or "").strip()
    if _CV2_AVAILABLE and model_path and os.path.exists(model_path) and factor in (2, 3, 4):
        try:
            cv_img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            sr = cv2.dnn_superres.DnnSuperResImpl_create()
            sr.readModel(model_path)
            sr.setModel("edsr", factor)
            upsampled = sr.upsample(cv_img)
            return Image.fromarray(cv2.cvtColor(upsampled, cv2.COLOR_BGR2RGB)), f"edsr-x{factor}"
        except Exception as exc:
            logger.warning("EDSR failed, falling back to LANCZOS: %s", exc)

    width, height = image.size
    return image.resize((width * factor, height * factor), Image.Resampling.LANCZOS), f"lanczos-x{factor}"


def _smart_resize(image: Any, min_pixels: int, max_pixels: int) -> Any:
    from PIL import Image  # type: ignore

    width, height = image.size
    pixels = width * height
    if pixels <= 0:
        return image
    if pixels < min_pixels:
        scale = math.sqrt(min_pixels / pixels)
    elif pixels > max_pixels:
        scale = math.sqrt(max_pixels / pixels)
    else:
        return image
    return image.resize(
        (max(MIN_DIMENSION, int(width * scale)), max(MIN_DIMENSION, int(height * scale))),
        Image.Resampling.LANCZOS,
    )


def check_image_zoom_in_requirements() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except Exception:
        return False


def image_zoom_in_tool(
    bbox_2d: Any,
    image_url: str = "",
    image_path: str = "",
    image_base64: str = "",
    label: str = "",
    use_super_resolution: bool = True,
    use_smart_resize: bool = True,
    min_pixels: int = DEFAULT_MIN_PIXELS,
    max_pixels: int = DEFAULT_MAX_PIXELS,
    sr_scale: int = DEFAULT_SR_SCALE,
) -> Any:
    if not bbox_2d or not isinstance(bbox_2d, (list, tuple)) or len(bbox_2d) != 4:
        return tool_error("bbox_2d must be [x1, y1, x2, y2] in absolute pixel coordinates.")
    try:
        bbox = [float(coord) for coord in bbox_2d]
    except (TypeError, ValueError):
        return tool_error(f"bbox_2d coordinates must be numeric: {bbox_2d}")
    if not (image_url or image_path or image_base64):
        return tool_error("Provide image_url, image_path, or image_base64.")

    tmp_dir = Path(os.getenv("HERMES_IMAGE_CACHE") or "/tmp/hermes-image-zoom-in")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    img, source_or_error, cleanup_path = _load_pil_image(image_url, image_path, image_base64, tmp_dir)
    if img is None:
        return tool_error(source_or_error)

    try:
        resized_bbox = _maybe_resize_bbox(bbox, image_width=img.size[0], image_height=img.size[1])
        if resized_bbox is None:
            return tool_error(
                f"Bounding box {bbox_2d} is invalid or smaller than the minimum {MIN_DIMENSION}x{MIN_DIMENSION}."
            )

        cropped = img.crop(tuple(resized_bbox))
        crop_size = cropped.size
        sr_backend = "off"
        if use_super_resolution:
            cropped, sr_backend = _apply_super_resolution(cropped, scale=sr_scale)
        if use_smart_resize:
            cropped = _smart_resize(
                cropped,
                min_pixels=max(MIN_DIMENSION * MIN_DIMENSION, int(min_pixels or DEFAULT_MIN_PIXELS)),
                max_pixels=max(MIN_DIMENSION * MIN_DIMENSION, int(max_pixels or DEFAULT_MAX_PIXELS)),
            )

        summary = (
            f"Zoomed into region {bbox_2d}"
            f"{f' (label: {label.strip()})' if label.strip() else ''}: "
            f"{img.size[0]}x{img.size[1]} source, {crop_size[0]}x{crop_size[1]} crop, "
            f"{cropped.size[0]}x{cropped.size[1]} output, super-resolution={sr_backend}."
        )
        return {
            "_multimodal": True,
            "content": [
                {"type": "text", "text": summary},
                {"type": "image_url", "image_url": {"url": _pil_to_data_url(cropped, fmt="PNG")}},
            ],
            "text_summary": summary,
            "meta": {
                "tool": "image_zoom_in",
                "bbox_2d": bbox,
                "resized_bbox": resized_bbox,
                "label": label.strip(),
                "super_resolution": sr_backend,
                "original_size": [img.size[0], img.size[1]],
                "crop_size": [crop_size[0], crop_size[1]],
                "new_size": [cropped.size[0], cropped.size[1]],
                "source": source_or_error[:200],
            },
        }
    except Exception as exc:
        logger.error("image_zoom_in failed: %s", exc, exc_info=True)
        return tool_error(f"Image zoom-in failed: {exc}")
    finally:
        if cleanup_path is not None:
            cleanup_path.unlink(missing_ok=True)


IMAGE_ZOOM_IN_SCHEMA = {
    "name": "image_zoom_in",
    "description": (
        "Zoom into a specific image region. The tool crops an absolute-pixel bbox, "
        "then directly applies super-resolution to the crop before returning the enlarged image."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "bbox_2d": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 4,
                "maxItems": 4,
                "description": "Pixel bbox [x1, y1, x2, y2] from top-left to bottom-right.",
            },
            "image_url": {"type": "string", "description": "Public HTTP(S) URL of the source image."},
            "image_path": {"type": "string", "description": "Local image path under HERMES_IMAGE_ROOT."},
            "image_base64": {"type": "string", "description": "Raw base64-encoded image bytes."},
            "label": {"type": "string", "description": "Optional label for the target region."},
            "use_super_resolution": {"type": "boolean", "description": "Apply super-resolution to the crop.", "default": True},
            "use_smart_resize": {"type": "boolean", "description": "Resize output into VLM-friendly pixel bounds.", "default": True},
            "min_pixels": {"type": "integer", "description": "Minimum output pixels after resizing.", "default": DEFAULT_MIN_PIXELS},
            "max_pixels": {"type": "integer", "description": "Maximum output pixels after resizing.", "default": DEFAULT_MAX_PIXELS},
            "sr_scale": {"type": "integer", "description": "Super-resolution scale factor.", "default": DEFAULT_SR_SCALE},
        },
        "required": ["bbox_2d"],
    },
}


def _handle_image_zoom_in(args: Dict[str, Any], **_kw: Any) -> Any:
    return image_zoom_in_tool(
        bbox_2d=args.get("bbox_2d") or args.get("bbox"),
        image_url=str(args.get("image_url") or "").strip(),
        image_path=str(args.get("image_path") or "").strip(),
        image_base64=str(args.get("image_base64") or "").strip(),
        label=str(args.get("label") or "").strip(),
        use_super_resolution=bool(args.get("use_super_resolution", True)),
        use_smart_resize=bool(args.get("use_smart_resize", True)),
        min_pixels=int(args.get("min_pixels") or DEFAULT_MIN_PIXELS),
        max_pixels=int(args.get("max_pixels") or DEFAULT_MAX_PIXELS),
        sr_scale=int(args.get("sr_scale") or os.getenv("SR_SCALE") or DEFAULT_SR_SCALE),
    )


registry.register(
    name="image_zoom_in",
    toolset="vision",
    schema=IMAGE_ZOOM_IN_SCHEMA,
    handler=_handle_image_zoom_in,
    check_fn=check_image_zoom_in_requirements,
    requires_env=[],
    emoji="zoom",
)
