"""Visual rendering utilities for the visual context engine.

Renders conversation messages as images (PDF->PNG with PIL fallback).
Produces two-tier output: far_history (downscaled) + recent_history (full res).
"""

from __future__ import annotations

import base64
import gc
import io
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Font resolution
# ---------------------------------------------------------------------------

_FONT_SEARCH_PATHS = [
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJKsc-Regular.otf",
]

_RE_CJK = re.compile(r"[一-鿿]")
_FONT_REGISTERED: Optional[str] = None


def _resolve_and_register_font(font_path: Optional[str]) -> str:
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return _FONT_REGISTERED

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = []
    if font_path and os.path.isfile(font_path):
        candidates.append(font_path)
    env_path = os.getenv("VISUAL_CONTEXT_FONT_PATH", "")
    if env_path and os.path.isfile(env_path):
        candidates.append(env_path)
    candidates.extend(_FONT_SEARCH_PATHS)

    for path in candidates:
        if not os.path.isfile(path):
            continue
        font_name = "HermesVisualFont"
        try:
            if path.endswith(".ttc"):
                pdfmetrics.registerFont(TTFont(font_name, path, subfontIndex=0))
            else:
                pdfmetrics.registerFont(TTFont(font_name, path))
            _FONT_REGISTERED = font_name
            return font_name
        except Exception:
            continue

    return "Helvetica"


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

def _densify_text(text: str) -> str:
    if not text:
        return text
    return re.sub(r"\s+", " ", text).strip()


def _build_tool_name_map(messages: List[Dict[str, Any]]) -> Dict[str, str]:
    mapping = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            if isinstance(tc, dict):
                tc_id = tc.get("id", "")
                fn = tc.get("function", {})
                name = fn.get("name", "") if isinstance(fn, dict) else ""
                if tc_id and name:
                    mapping[tc_id] = name
    return mapping


def _format_message_block(
    msg: Dict[str, Any],
    density: str = "dense",
    tool_name_map: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    role = msg.get("role", "unknown")
    body_parts: List[str] = []

    if role == "tool":
        tool_call_id = msg.get("tool_call_id", "")
        fn_name = (tool_name_map or {}).get(tool_call_id, "")
        header = f"TOOL · {fn_name}" if fn_name else "TOOL"
    elif role == "assistant":
        header = "ASSISTANT"
    elif role == "user":
        header = "USER"
    elif role == "system":
        header = "SYSTEM"
    else:
        header = role.upper()

    tool_calls = msg.get("tool_calls")
    if tool_calls:
        for tc in tool_calls:
            if isinstance(tc, dict):
                fn = tc.get("function", {})
                name = fn.get("name", "?")
                args = fn.get("arguments", "")
                if len(args) > 300:
                    args = args[:300] + "..."
                body_parts.append(f"→ call {name}({args})")

    content = msg.get("content", "")
    if isinstance(content, str) and content.strip():
        body_parts.append(content)
    elif isinstance(content, list):
        text_parts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        joined = "\n".join(text_parts)
        if joined.strip():
            body_parts.append(joined)

    body = "\n".join(body_parts)
    if density == "dense":
        body = _densify_text(body)
    elif density == "compact":
        body = re.sub(r"\n{3,}", "\n\n", body).strip()

    return {"role": role, "header": header, "body": body}


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------

_ROLE_COLORS = {
    "user": ("#1F6FEB", "#FFFFFF"),
    "assistant": ("#2DA44E", "#FFFFFF"),
    "tool": ("#BF8700", "#FFFFFF"),
    "system": ("#6E7781", "#FFFFFF"),
}
_DEFAULT_ROLE_COLOR = ("#444444", "#FFFFFF")


def _render_blocks_to_images(
    blocks: List[Dict[str, str]],
    font_path: Optional[str] = None,
    font_size: int = 8,
    page_width: int = 1024,
    max_image_height: int = 4096,
    dpi: int = 72,
    save_dir: Optional[str] = None,
    save_prefix: str = "page",
) -> List[str]:
    try:
        return _render_blocks_pdf(
            blocks, font_path, font_size, page_width, max_image_height, dpi, save_dir, save_prefix
        )
    except ImportError as e:
        logger.info("PDF rendering unavailable (%s), using PIL fallback.", e)
        return _text_to_images_fallback(blocks, font_size, page_width, max_image_height, save_dir, save_prefix)
    except Exception as e:
        logger.warning("PDF rendering failed (%s), using PIL fallback.", e)
        return _text_to_images_fallback(blocks, font_size, page_width, max_image_height, save_dir, save_prefix)


def _render_blocks_pdf(
    blocks: List[Dict[str, str]],
    font_path: Optional[str],
    font_size: int,
    page_width: int,
    max_image_height: int,
    dpi: int,
    save_dir: Optional[str],
    save_prefix: str,
) -> List[str]:
    import numpy as np
    from pdf2image import convert_from_bytes, pdfinfo_from_bytes
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate
    from xml.sax.saxutils import escape
    from PIL import Image

    font_name = _resolve_and_register_font(font_path)

    page_pt_width = page_width * 72.0 / dpi
    page_pt_height = max_image_height * 72.0 / dpi
    page_size = (page_pt_width, page_pt_height)

    full_text = "\n".join(b.get("body", "") + b.get("header", "") for b in blocks)
    has_cjk = _RE_CJK.search(full_text) is not None

    body_style = ParagraphStyle(
        name="Body",
        fontName=font_name,
        fontSize=font_size,
        leading=int(font_size * 1.2) + 1,
        textColor=colors.HexColor("#1A1A1A"),
        wordWrap="CJK" if has_cjk else None,
        alignment=TA_LEFT,
        spaceBefore=0,
        spaceAfter=0,
        leftIndent=0,
        rightIndent=0,
    )

    markup_parts = []
    for block in blocks:
        role = block.get("role", "unknown")
        header_text = block.get("header", "")
        body_text = block.get("body", "").replace("\xad", "").replace("​", "")
        bg, fg = _ROLE_COLORS.get(role, _DEFAULT_ROLE_COLOR)
        label_markup = f'<font backColor="{bg}" color="{fg}"><b>&nbsp;{escape(header_text)}&nbsp;</b></font>'
        body_markup = escape(body_text) if body_text else ""
        if body_markup:
            markup_parts.append(f"{label_markup}&nbsp;{body_markup}")
        else:
            markup_parts.append(label_markup)

    full_markup = " ".join(markup_parts)
    try:
        story = [Paragraph(full_markup, body_style)]
    except Exception:
        story = []
        for block in blocks:
            role = block.get("role", "unknown")
            header_text = block.get("header", "")
            body_text = block.get("body", "").replace("\xad", "").replace("​", "")
            bg, fg = _ROLE_COLORS.get(role, _DEFAULT_ROLE_COLOR)
            label = f'<font backColor="{bg}" color="{fg}"><b>&nbsp;{escape(header_text)}&nbsp;</b></font>'
            body_mk = escape(body_text)
            markup = f"{label}&nbsp;{body_mk}" if body_mk else label
            try:
                story.append(Paragraph(markup, body_style))
            except Exception:
                story.append(Paragraph(escape(f"[{header_text}] {body_text[:500]}"), body_style))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=page_size, leftMargin=0, rightMargin=0, topMargin=0, bottomMargin=0
    )
    bg_color = colors.HexColor("#FFFFFF")

    def _draw_bg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(bg_color)
        canvas.rect(0, 0, page_size[0], page_size[1], stroke=0, fill=1)
        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_bg, onLaterPages=_draw_bg)

    pdf_bytes = buf.getvalue()
    buf.close()

    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        with open(os.path.join(save_dir, f"{save_prefix}.pdf"), "wb") as f:
            f.write(pdf_bytes)

    info = pdfinfo_from_bytes(pdf_bytes)
    total_pages = info["Pages"]
    result: List[str] = []

    for start in range(1, total_pages + 1, 20):
        end = min(start + 19, total_pages)
        images = convert_from_bytes(pdf_bytes, dpi=dpi, first_page=start, last_page=end)
        for offset, img in enumerate(images, start=start):
            gray = np.array(img.convert("L"))
            bg_gray = np.median(gray[:2, :2])
            mask = np.abs(gray.astype(float) - float(bg_gray)) > 5
            cols = np.where(mask.any(axis=0))[0]
            rows = np.where(mask.any(axis=1))[0]
            if cols.size and rows.size:
                left = max(0, int(cols[0]) - 1)
                right = min(img.width, int(cols[-1]) + 2)
                top = max(0, int(rows[0]) - 1)
                bottom = min(img.height, int(rows[-1]) + 2)
                img = img.crop((left, top, right, bottom))
            img_buf = io.BytesIO()
            img.save(img_buf, format="PNG", optimize=True)
            result.append(base64.b64encode(img_buf.getvalue()).decode("ascii"))
            if save_dir:
                img.save(os.path.join(save_dir, f"{save_prefix}_{offset:03d}.png"), "PNG")
            img.close()
        images.clear()
        del images

    del pdf_bytes
    gc.collect()
    return result


def _text_to_images_fallback(
    blocks: List[Dict[str, str]],
    font_size: int = 8,
    page_width: int = 1024,
    max_image_height: int = 4096,
    save_dir: Optional[str] = None,
    save_prefix: str = "page",
) -> List[str]:
    import textwrap
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size=font_size
        )
    except Exception:
        font = ImageFont.load_default(size=font_size)

    line_height = int(font_size * 1.4)
    margin = 16
    usable_width = page_width - 2 * margin
    chars_per_line = max(int(usable_width / (font_size * 0.6)), 40)

    text = "\n".join(f"=== {b.get('header', '')} ===\n{b.get('body', '')}" for b in blocks)
    all_lines: List[str] = []
    for raw_line in text.split("\n"):
        wrapped = textwrap.wrap(raw_line, width=chars_per_line) or [""]
        all_lines.extend(wrapped)

    max_lines_per_page = max((max_image_height - 2 * margin) // line_height, 10)
    pages: List[List[str]] = []
    for start in range(0, len(all_lines), max_lines_per_page):
        pages.append(all_lines[start : start + max_lines_per_page])

    result: List[str] = []
    for page_idx, page_lines in enumerate(pages):
        img_height = min(len(page_lines) * line_height + 2 * margin, max_image_height)
        img = Image.new("RGB", (page_width, img_height), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        y = margin
        for line in page_lines:
            draw.text((margin, y), line, fill=(0, 0, 0), font=font)
            y += line_height
        img_buf = io.BytesIO()
        img.save(img_buf, format="PNG", optimize=True)
        result.append(base64.b64encode(img_buf.getvalue()).decode("ascii"))
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
            img.save(os.path.join(save_dir, f"{save_prefix}_{page_idx + 1:03d}.png"), "PNG")
        img.close()

    return result


# ---------------------------------------------------------------------------
# Image utilities
# ---------------------------------------------------------------------------

def _save_merged_image(b64_str: str, save_dir: str, filename: str) -> None:
    try:
        os.makedirs(save_dir, exist_ok=True)
        img_data = base64.b64decode(b64_str)
        path = os.path.join(save_dir, filename)
        with open(path, "wb") as f:
            f.write(img_data)
        logger.info("Visual: saved %s", path)
    except Exception as e:
        logger.warning("Visual: failed to save %s: %s", filename, e)


def _downscale_image_b64(b64_str: str, scale: float = 0.5) -> str:
    from PIL import Image

    img_data = base64.b64decode(b64_str)
    img = Image.open(io.BytesIO(img_data))
    new_w = max(1, int(img.width * scale))
    new_h = max(1, int(img.height * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    img.close()
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _merge_images_vertical(b64_list: List[str]) -> str:
    from PIL import Image

    if len(b64_list) == 1:
        return b64_list[0]
    imgs = []
    for b64 in b64_list:
        imgs.append(Image.open(io.BytesIO(base64.b64decode(b64))))
    total_w = max(im.width for im in imgs)
    total_h = sum(im.height for im in imgs)
    merged = Image.new("RGB", (total_w, total_h), (255, 255, 255))
    y = 0
    for im in imgs:
        merged.paste(im, (0, y))
        y += im.height
        im.close()
    buf = io.BytesIO()
    merged.save(buf, format="PNG", optimize=True)
    merged.close()
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

VISUAL_CONTEXT_PROMPT = (
    "The image(s) below contain a visual snapshot of your previous research history "
    "— including search queries, tool responses, your reasoning, and intermediate "
    "findings from earlier rounds. This is your compressed memory of work already done.\n\n"
    "When continuing your investigation:\n"
    "- Reference specific facts, URLs, and numbers visible in the image(s) when relevant\n"
    "- Do not re-search for information already found in your history\n"
    "- Cite sources using the [^index^] format visible in the image(s)\n"
    "- If you need precise details from the history that are hard to read, verify with a targeted search"
)


def render_visual_compression(
    messages: List[Dict[str, Any]],
    head_end: int,
    image_width: int = 1024,
    font_size: int = 8,
    max_image_height: int = 4096,
    font_path: Optional[str] = None,
    dpi: int = 72,
    density: str = "dense",
    history_scale: float = 0.75,
    keep_rounds: int = 1,
    save_dir: Optional[str] = None,
    compact_count: int = 0,
) -> List[Dict[str, Any]]:
    """Render messages as images and return compressed message list."""

    # Find round boundaries (assistant messages with tool_calls)
    round_starts: List[int] = []
    for i, msg in enumerate(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            round_starts.append(i)

    if len(round_starts) <= keep_rounds:
        logger.info("Visual: only %d rounds, need >%d. Skipping.", len(round_starts), keep_rounds)
        return messages

    # Determine boundary: keep the last N rounds as text
    if keep_rounds > 0:
        compact_boundary = round_starts[len(round_starts) - keep_rounds]
    else:
        compact_boundary = len(messages)

    to_render_msgs = messages[head_end:compact_boundary]
    if not to_render_msgs:
        return messages

    tool_name_map = _build_tool_name_map(messages)

    # Split into far_history and recent_history (50/50)
    count = compact_count + 1
    split_point = len(to_render_msgs) // 2
    far_msgs = to_render_msgs[:split_point] if split_point > 0 else []
    recent_msgs = to_render_msgs[split_point:] if split_point < len(to_render_msgs) else to_render_msgs

    # Determine the directory for saving final merged images.
    # If save_dir is not provided, use cwd (which is the workspace dir in browse_comp runs).
    effective_save_dir = save_dir or os.getcwd()

    # Render far history -> downscale
    history_b64: Optional[str] = None
    if far_msgs:
        far_blocks = [_format_message_block(m, density=density, tool_name_map=tool_name_map) for m in far_msgs]
        try:
            far_images = _render_blocks_to_images(
                far_blocks, font_path=font_path, font_size=font_size,
                page_width=image_width, max_image_height=max_image_height,
                dpi=dpi, save_dir=save_dir, save_prefix=f"compact_{count}_history",
            )
            if far_images:
                merged = _merge_images_vertical(far_images)
                history_b64 = _downscale_image_b64(merged, scale=history_scale)
                # Save old_N.png only for N>1 (first compression has no "old")
                if count > 1:
                    _save_merged_image(history_b64, effective_save_dir, f"old_{count}.png")
        except Exception as e:
            logger.error("Visual: far history rendering failed: %s", e)

    # Render recent history -> full resolution
    recent_b64: Optional[str] = None
    if recent_msgs:
        recent_blocks = [_format_message_block(m, density=density, tool_name_map=tool_name_map) for m in recent_msgs]
        try:
            recent_images = _render_blocks_to_images(
                recent_blocks, font_path=font_path, font_size=font_size,
                page_width=image_width, max_image_height=max_image_height,
                dpi=dpi, save_dir=save_dir, save_prefix=f"compact_{count}_recent",
            )
            if recent_images:
                recent_b64 = _merge_images_vertical(recent_images)
                _save_merged_image(recent_b64, effective_save_dir, f"recent_{count}.png")
        except Exception as e:
            logger.error("Visual: recent rendering failed: %s", e)
            return messages

    if not recent_b64 and not history_b64:
        logger.warning("Visual: no images generated.")
        return messages

    # Build multimodal content
    content_parts: List[Dict[str, Any]] = [
        {"type": "text", "text": VISUAL_CONTEXT_PROMPT},
    ]
    if history_b64:
        content_parts.append({"type": "text", "text": "[Older history — lower resolution]"})
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{history_b64}", "detail": "low"},
        })
    if recent_b64:
        if history_b64:
            content_parts.append({"type": "text", "text": "[Recent context — full resolution]"})
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{recent_b64}", "detail": "high"},
        })

    # Assemble: head + visual message + preserved tail
    result = list(messages[:head_end])
    result.append({"role": "user", "content": content_parts})
    result.extend(messages[compact_boundary:])

    logger.info("Visual: rendered %d messages as images, kept %d tail messages",
                len(to_render_msgs), len(messages) - compact_boundary)
    return result
