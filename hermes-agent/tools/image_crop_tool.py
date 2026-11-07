#!/usr/bin/env python3
"""Crop a region from an image and return it as a multimodal tool result."""

from __future__ import annotations

import ast
import logging
import math
import os
from pathlib import Path
from typing import Any, Dict, Optional

from tools.image_zoom_in_tool import (
    DEFAULT_MAX_PIXELS,
    DEFAULT_MIN_PIXELS,
    MIN_DIMENSION,
    _load_pil_image,
    _pil_to_data_url,
)
from tools.registry import registry, tool_error

logger = logging.getLogger(__name__)

DEFAULT_RELATIVE_COORD_MAX = 1000.0
DEFAULT_PADDING = (0.2, 0.2)
DEFAULT_PADDING_PX_CAP = 600.0


def _parse_bbox(bbox: Any) -> Optional[list[float]]:
    if isinstance(bbox, str):
        try:
            bbox = ast.literal_eval(bbox)
        except (ValueError, SyntaxError):
            return None
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        return [float(coord) for coord in bbox]
    except (TypeError, ValueError):
        return None


def _aligned_resize(image: Any, min_pixels: int, max_pixels: int, factor: int = 28) -> Any:
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
        scale = 1.0

    new_width = max(factor, int(round(width * scale / factor)) * factor)
    new_height = max(factor, int(round(height * scale / factor)) * factor)
    if (new_width, new_height) == (width, height):
        return image
    return image.resize((new_width, new_height), Image.Resampling.LANCZOS)


def _normalize_padding(padding: Any) -> tuple[float, float]:
    if padding is None:
        return DEFAULT_PADDING
    if isinstance(padding, (int, float)):
        value = float(padding)
        return value, value
    if isinstance(padding, (list, tuple)) and len(padding) == 2:
        try:
            return float(padding[0]), float(padding[1])
        except (TypeError, ValueError):
            return DEFAULT_PADDING
    return DEFAULT_PADDING


def _crop_image(
    image: Any,
    bbox: list[float],
    coord_format: str,
    relative_coord_max: float,
    padding: tuple[float, float],
) -> tuple[Optional[Any], Optional[str]]:
    from PIL import Image  # type: ignore

    image_width, image_height = image.size
    if image_width == 0 or image_height == 0:
        return None, "Source image has zero dimension"

    x1, y1, x2, y2 = bbox
    if coord_format == "relative":
        if not all(0 <= coord <= relative_coord_max for coord in (x1, y1, x2, y2)):
            return None, f"Relative coords must be in [0, {relative_coord_max}]. Got {bbox}"
        x1, x2 = x1 / relative_coord_max, x2 / relative_coord_max
        y1, y2 = y1 / relative_coord_max, y2 / relative_coord_max
    elif coord_format == "absolute":
        if not (0 <= x1 <= image_width and 0 <= x2 <= image_width and 0 <= y1 <= image_height and 0 <= y2 <= image_height):
            return None, f"Absolute coords must be within image bounds [0, {image_width}] x [0, {image_height}]. Got {bbox}"
        x1, x2 = x1 / image_width, x2 / image_width
        y1, y2 = y1 / image_height, y2 / image_height
    else:
        return None, f"coord_format must be 'relative' or 'absolute', got {coord_format!r}"

    if not (x1 < x2 and y1 < y2):
        return None, f"Invalid bbox: x1<x2 and y1<y2 required. Got {bbox}"

    pad_x = min(max(0.0, padding[0]), DEFAULT_PADDING_PX_CAP / image_width)
    pad_y = min(max(0.0, padding[1]), DEFAULT_PADDING_PX_CAP / image_height)
    x1, y1 = max(0.0, x1 - pad_x), max(0.0, y1 - pad_y)
    x2, y2 = min(1.0, x2 + pad_x), min(1.0, y2 + pad_y)

    crop_box = (
        int(x1 * image_width),
        int(y1 * image_height),
        int(x2 * image_width),
        int(y2 * image_height),
    )
    cropped = image.crop(crop_box)
    width, height = cropped.size
    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        cropped = cropped.resize((max(width, MIN_DIMENSION), max(height, MIN_DIMENSION)), Image.Resampling.LANCZOS)
    return cropped, None


def check_image_crop_requirements() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except Exception:
        return False


def image_crop_tool(
    bbox: Any,
    image_url: str = "",
    image_path: str = "",
    image_base64: str = "",
    coord_format: str = "relative",
    relative_coord_max: float = DEFAULT_RELATIVE_COORD_MAX,
    padding: Any = None,
    use_smart_resize: bool = True,
    min_pixels: int = DEFAULT_MIN_PIXELS,
    max_pixels: int = DEFAULT_MAX_PIXELS,
) -> Any:
    parsed = _parse_bbox(bbox)
    if parsed is None:
        return tool_error("bbox must be a list of 4 numbers: [x1, y1, x2, y2].")
    if not (image_url or image_path or image_base64):
        return tool_error("Provide image_url, image_path, or image_base64.")

    tmp_dir = Path(os.getenv("HERMES_IMAGE_CACHE") or "/tmp/hermes-image-crop")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    img, source_or_error, cleanup_path = _load_pil_image(image_url, image_path, image_base64, tmp_dir)
    if img is None:
        return tool_error(source_or_error)

    try:
        coord_format = (coord_format or "relative").strip().lower()
        cropped, error = _crop_image(
            img,
            parsed,
            coord_format=coord_format,
            relative_coord_max=float(relative_coord_max or DEFAULT_RELATIVE_COORD_MAX),
            padding=_normalize_padding(padding),
        )
        if cropped is None:
            return tool_error(error or "Crop failed")
        if use_smart_resize:
            cropped = _aligned_resize(
                cropped,
                min_pixels=max(MIN_DIMENSION * MIN_DIMENSION, int(min_pixels or DEFAULT_MIN_PIXELS)),
                max_pixels=max(MIN_DIMENSION * MIN_DIMENSION, int(max_pixels or DEFAULT_MAX_PIXELS)),
            )

        summary = (
            f"Cropped region ({coord_format}, bbox={parsed}): "
            f"{img.size[0]}x{img.size[1]} source, {cropped.size[0]}x{cropped.size[1]} output."
        )
        return {
            "_multimodal": True,
            "content": [
                {"type": "text", "text": summary},
                {"type": "image_url", "image_url": {"url": _pil_to_data_url(cropped, fmt="PNG")}},
            ],
            "text_summary": summary,
            "meta": {
                "tool": "image_crop",
                "coord_format": coord_format,
                "bbox": parsed,
                "original_size": [img.size[0], img.size[1]],
                "new_size": [cropped.size[0], cropped.size[1]],
                "source": source_or_error[:200],
            },
        }
    except Exception as exc:
        logger.error("image_crop failed: %s", exc, exc_info=True)
        return tool_error(f"Image crop failed: {exc}")
    finally:
        if cleanup_path is not None:
            cleanup_path.unlink(missing_ok=True)


IMAGE_CROP_SCHEMA = {
    "name": "image_crop",
    "description": (
        "Crop a bounding-box region from an image and return the cropped region. "
        "Supports relative coordinates in [0,1000] and absolute pixel coordinates."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "bbox": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 4,
                "maxItems": 4,
                "description": "Bounding box [x1, y1, x2, y2].",
            },
            "image_url": {"type": "string", "description": "Public HTTP(S) URL of the source image."},
            "image_path": {"type": "string", "description": "Local image path under HERMES_IMAGE_ROOT."},
            "image_base64": {"type": "string", "description": "Raw base64-encoded image bytes."},
            "coord_format": {
                "type": "string",
                "enum": ["relative", "absolute"],
                "description": "'relative' uses [0, relative_coord_max]; 'absolute' uses source pixels.",
                "default": "relative",
            },
            "relative_coord_max": {
                "type": "number",
                "description": "Upper bound for relative coordinates.",
                "default": DEFAULT_RELATIVE_COORD_MAX,
            },
            "padding": {
                "anyOf": [
                    {"type": "number"},
                    {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                ],
                "description": "Padding fraction of image size: scalar or [pad_x, pad_y].",
            },
            "use_smart_resize": {"type": "boolean", "description": "Resize output into VLM-friendly pixel bounds.", "default": True},
            "min_pixels": {"type": "integer", "description": "Minimum output pixels after resizing.", "default": DEFAULT_MIN_PIXELS},
            "max_pixels": {"type": "integer", "description": "Maximum output pixels after resizing.", "default": DEFAULT_MAX_PIXELS},
        },
        "required": ["bbox"],
    },
}


def _handle_image_crop(args: Dict[str, Any], **_kw: Any) -> Any:
    return image_crop_tool(
        bbox=args.get("bbox") or args.get("bbox_2d"),
        image_url=str(args.get("image_url") or "").strip(),
        image_path=str(args.get("image_path") or "").strip(),
        image_base64=str(args.get("image_base64") or "").strip(),
        coord_format=str(args.get("coord_format") or "relative"),
        relative_coord_max=float(args.get("relative_coord_max") or DEFAULT_RELATIVE_COORD_MAX),
        padding=args.get("padding"),
        use_smart_resize=bool(args.get("use_smart_resize", True)),
        min_pixels=int(args.get("min_pixels") or DEFAULT_MIN_PIXELS),
        max_pixels=int(args.get("max_pixels") or DEFAULT_MAX_PIXELS),
    )


registry.register(
    name="image_crop",
    toolset="vision",
    schema=IMAGE_CROP_SCHEMA,
    handler=_handle_image_crop,
    check_fn=check_image_crop_requirements,
    requires_env=[],
    emoji="crop",
)
