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
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
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
    layout: str = "highlight",
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
    if layout in ("plain", "plain_no_header", "highlight", "highlight_no_wrap"):
        body = re.sub(r"\n{3,}", "\n\n", body).strip()

    if layout == "plain_no_header":
        header = ""

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
    """Render blocks to a list of base64 PNG strings via PDF intermediate.

    Does NOT save the raw PDF — callers wanting the vector form should grab it
    from ``_blocks_to_pdf_bytes`` directly (see ``render_visual_compression``).
    """
    try:
        pdf_bytes = _blocks_to_pdf_bytes(
            blocks, font_path, font_size, page_width, max_image_height, dpi
        )
    except ImportError as e:
        logger.info("PDF rendering unavailable (%s), using PIL fallback.", e)
        return _text_to_images_fallback(blocks, font_size, page_width, max_image_height, save_dir, save_prefix)
    except Exception as e:
        logger.warning("PDF rendering failed (%s), using PIL fallback.", e)
        return _text_to_images_fallback(blocks, font_size, page_width, max_image_height, save_dir, save_prefix)

    try:
        return _pdf_bytes_to_image_b64_list(
            pdf_bytes, dpi=dpi, save_dir=save_dir, save_prefix=save_prefix
        )
    except ImportError as e:
        logger.info("pdf2image unavailable (%s), using PIL fallback.", e)
        return _text_to_images_fallback(blocks, font_size, page_width, max_image_height, save_dir, save_prefix)
    except Exception as e:
        logger.warning("PDF->image failed (%s), using PIL fallback.", e)
        return _text_to_images_fallback(blocks, font_size, page_width, max_image_height, save_dir, save_prefix)


def _markup_body(text: str) -> str:
    """Escape text, style URLs as blue underlined non-breaking, bold ID fields.

    Mirrors the reportlab branch of Vista (visual_compress.py:_markup_body).
    """
    from xml.sax.saxutils import escape

    if not text.strip():
        return ""
    url_re = re.compile(r"https?://\S+")
    segments: List[tuple] = []  # (text, is_url)
    pos = 0
    for m in url_re.finditer(text):
        before = text[pos:m.start()]
        if before:
            segments.append((before, False))
        segments.append((m.group(0), True))
        pos = m.end()
    tail = text[pos:]
    if tail:
        segments.append((tail, False))

    id_re = re.compile(r"(\[?\s*ID\s*\]?\s*:\s*)(\S+)", re.IGNORECASE)
    parts: List[str] = []
    for seg_text, is_url in segments:
        if is_url:
            escaped_url = escape(seg_text)
            # Insert zero-width spaces after : / ? & = to allow line breaks
            # (otherwise reportlab's CJK wrap keeps long URLs as a single
            # unbreakable token and may overflow the page width).
            for ch in (":", "/", "?", "&amp;", "="):
                escaped_url = escaped_url.replace(ch, ch + "&#8203;")
            parts.append(
                f'<font color="#0969DA"><u>{escaped_url}</u></font>'
            )
        else:
            sub_pos = 0
            for m in id_re.finditer(seg_text):
                before = seg_text[sub_pos:m.start()]
                if before:
                    parts.append(escape(before))
                parts.append(f"<b>{escape(m.group(1))}{escape(m.group(2))}</b>")
                sub_pos = m.end()
            remainder = seg_text[sub_pos:]
            if remainder:
                parts.append(escape(remainder))
    return "".join(parts)


def _blocks_to_pdf_bytes(
    blocks: List[Dict[str, str]],
    font_path: Optional[str],
    font_size: int,
    page_width: int,
    max_image_height: int,
    dpi: int,
    layout: str = "highlight",
) -> bytes:
    """Render blocks to a single-paragraph PDF and return the raw bytes.

    layout controls styling:
      - "highlight": role-colored header chips + URL/ID markup (full styling)
      - "plain" / "1d": plain escaped text, no colors or markup
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate
    from xml.sax.saxutils import escape

    font_name = _resolve_and_register_font(font_path)

    page_pt_width = page_width * 72.0 / dpi
    if layout == "highlight_no_wrap":
        page_pt_width = 8192 * 72.0 / dpi
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
        header_text = block.get("header", "")
        body_text = block.get("body", "").replace("\xad", "").replace("​", "")

        if layout in ("highlight", "highlight_no_wrap"):
            role = block.get("role", "unknown")
            bg, fg = _ROLE_COLORS.get(role, _DEFAULT_ROLE_COLOR)
            label_markup = (
                f'<font backColor="{bg}" color="{fg}">'
                f"<b>&nbsp;{escape(header_text)}&nbsp;</b>"
                f"</font>"
            )
            body_markup = _markup_body(body_text)
            if body_markup:
                markup_parts.append(f"{label_markup}&nbsp;{body_markup}")
            else:
                markup_parts.append(label_markup)
        elif layout == "plain_no_header":
            markup_parts.append(escape(body_text))
        else:
            plain = escape(f"[{header_text}] {body_text}")
            markup_parts.append(plain)

    full_markup = " ".join(markup_parts)
    try:
        story = [Paragraph(full_markup, body_style)]
    except Exception:
        story = []
        for block in blocks:
            header_text = block.get("header", "")
            body_text = block.get("body", "").replace("\xad", "").replace("​", "")
            if layout in ("highlight", "highlight_no_wrap"):
                role = block.get("role", "unknown")
                bg, fg = _ROLE_COLORS.get(role, _DEFAULT_ROLE_COLOR)
                label = (
                    f'<font backColor="{bg}" color="{fg}">'
                    f"<b>&nbsp;{escape(header_text)}&nbsp;</b></font>"
                )
                body_mk = _markup_body(body_text)
                markup = f"{label}&nbsp;{body_mk}" if body_mk else label
            elif layout == "plain_no_header":
                markup = escape(body_text[:500])
            else:
                markup = escape(f"[{header_text}] {body_text[:500]}")
            try:
                story.append(Paragraph(markup, body_style))
            except Exception:
                story.append(Paragraph(escape(body_text[:500]), body_style))

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
    return pdf_bytes


def _pdf_bytes_to_image_b64_list(
    pdf_bytes: bytes,
    dpi: int = 72,
    save_dir: Optional[str] = None,
    save_prefix: str = "page",
) -> List[str]:
    """Convert PDF bytes to a list of base64 PNG strings, one per page (with auto-crop)."""
    import numpy as np
    from pdf2image import convert_from_bytes, pdfinfo_from_bytes

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
                os.makedirs(save_dir, exist_ok=True)
                img.save(os.path.join(save_dir, f"{save_prefix}_{offset:03d}.png"), "PNG")
            img.close()
        images.clear()
        del images

    gc.collect()
    return result


def _concat_pdf_bytes(pdfs: List[bytes]) -> bytes:
    """Concatenate multiple PDF byte strings into one. Empty/None entries are skipped."""
    pdfs = [p for p in pdfs if p]
    if not pdfs:
        return b""
    if len(pdfs) == 1:
        return pdfs[0]
    from PyPDF2 import PdfWriter, PdfReader

    writer = PdfWriter()
    readers = []  # keep alive until write
    for p in pdfs:
        r = PdfReader(io.BytesIO(p))
        readers.append(r)
        for page in r.pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


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


def _image_b64_dimensions(data_url: str) -> Optional[tuple]:
    """Extract (width, height) from a data:image/png;base64,... URL."""
    from PIL import Image
    try:
        if data_url.startswith("data:"):
            b64 = data_url.split(",", 1)[1]
        else:
            b64 = data_url
        img = Image.open(io.BytesIO(base64.b64decode(b64)))
        dims = img.size
        img.close()
        return dims
    except Exception:
        return None


def _estimate_vlm_image_tokens(width: int, height: int, tile_size: int = 28) -> int:
    """Estimate VLM image tokens using the Qwen2.5-VL / OpenAI high-detail formula."""
    import math
    return math.ceil(height / tile_size) * math.ceil(width / tile_size) * 4


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
    layout: str = "highlight",
    history_scale: float = 0.75,
    keep_rounds: int = 1,
    recent_rounds: int = 5,
    save_dir: Optional[str] = None,
    compact_count: int = 0,
    stats: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Render messages as images and return compressed message list.

    Split policy:
      - The last ``keep_rounds`` rounds stay in TEXT form (tail, never rendered).
      - Of the messages that ARE rendered, the last ``recent_rounds`` rounds
        keep full resolution (``recent_<N>.png``); everything before them is
        rendered identically and then additionally downscaled by
        ``history_scale`` (``old_<N>.png``). Both files are always saved when
        their segment is non-empty — recent and history are fully symmetric
        apart from the extra downscale step on history.
    """

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

    # Measure text content being replaced (for compression ratio stats)
    if stats is not None:
        text_chars = sum(len(str(m.get("content", ""))) for m in to_render_msgs)
        stats["text_chars"] = text_chars
        stats["text_tokens_estimate"] = (text_chars + 3) // 4
        stats["messages_rendered"] = len(to_render_msgs)

    tool_name_map = _build_tool_name_map(messages)

    # Split far/recent by ROUND COUNT (default: keep last 5 rounds at full resolution).
    # recent_rounds=0 forces everything into far (no recent segment).
    # If there are fewer than recent_rounds rounds inside the render range, everything
    # is recent and history stays empty.
    count = compact_count + 1
    render_round_starts = [i - head_end for i in round_starts if head_end <= i < compact_boundary]
    if recent_rounds <= 0:
        split_point = len(to_render_msgs)
    elif len(render_round_starts) <= recent_rounds:
        split_point = 0
    else:
        split_point = render_round_starts[len(render_round_starts) - recent_rounds]
    far_msgs = to_render_msgs[:split_point]
    recent_msgs = to_render_msgs[split_point:]

    # Determine the directory for saving final merged images.
    # If save_dir is not provided, use cwd (which is the workspace dir in browse_comp runs).
    effective_save_dir = save_dir or os.getcwd()

    def _render_segment(seg_msgs: List[Dict[str, Any]], prefix: str) -> tuple:
        """Render a slice of messages.

        Returns (pdf_bytes, merged_png_b64). Both are None on empty input;
        on PDF-render failure, falls back to PIL path (pdf_bytes will be b"").
        """
        if not seg_msgs:
            return None, None
        blocks = [_format_message_block(m, layout=layout, tool_name_map=tool_name_map) for m in seg_msgs]
        # Try the PDF path first so we get raw vector bytes too.
        pdf_bytes = b""
        try:
            pdf_bytes = _blocks_to_pdf_bytes(
                blocks, font_path, font_size, image_width, max_image_height, dpi,
                layout=layout,
            )
        except Exception as e:
            logger.warning("Visual: PDF render failed for %s (%s); using PIL fallback.", prefix, e)

        if pdf_bytes:
            try:
                images = _pdf_bytes_to_image_b64_list(
                    pdf_bytes, dpi=dpi, save_dir=save_dir, save_prefix=prefix
                )
            except Exception as e:
                logger.warning("Visual: PDF->image failed for %s (%s); using PIL fallback.", prefix, e)
                images = _text_to_images_fallback(
                    blocks, font_size, image_width, max_image_height, save_dir, prefix
                )
        else:
            images = _text_to_images_fallback(
                blocks, font_size, image_width, max_image_height, save_dir, prefix
            )

        if not images:
            return pdf_bytes, None
        return pdf_bytes, _merge_images_vertical(images)

    # Render recent first — it's the critical path. If it fails, abandon compression.
    try:
        recent_pdf, recent_b64 = _render_segment(recent_msgs, f"compact_{count}_recent")
    except Exception as e:
        logger.error("Visual: recent rendering failed: %s", e)
        return messages
    if recent_b64 is not None:
        _save_merged_image(recent_b64, effective_save_dir, f"recent_{count}.png")

    # Render far history identically, then additionally downscale.
    # Far failure is non-fatal — we still emit recent-only compression.
    # history_scale=0 means skip far history entirely (no history image).
    history_b64: Optional[str] = None
    history_pdf: bytes = b""
    if history_scale > 0:
        try:
            history_pdf, history_full = _render_segment(far_msgs, f"compact_{count}_history")
            if history_full is not None:
                if history_scale < 1.0:
                    history_b64 = _downscale_image_b64(history_full, scale=history_scale)
                else:
                    history_b64 = history_full
                _save_merged_image(history_b64, effective_save_dir, f"old_{count}.png")
        except Exception as e:
            logger.error("Visual: far history rendering failed: %s", e)

    # Save the combined pre-downscale vector PDF (history pages first, then recent)
    # as compact_<N>.pdf. This is the raw source the model would have seen before
    # any resolution drop; useful for offline inspection and debugging.
    try:
        combined_pdf = _concat_pdf_bytes([history_pdf, recent_pdf or b""])
        if combined_pdf:
            os.makedirs(effective_save_dir, exist_ok=True)
            pdf_out = os.path.join(effective_save_dir, f"compact_{count}.pdf")
            with open(pdf_out, "wb") as f:
                f.write(combined_pdf)
            logger.info("Visual: saved %s", pdf_out)
    except Exception as e:
        logger.warning("Visual: failed to save combined compact_%d.pdf: %s", count, e)

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

    # Populate image token stats for compression ratio tracking
    if stats is not None:
        image_tokens = 0
        for part in content_parts:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            detail = part.get("image_url", {}).get("detail", "high")
            if detail == "low":
                image_tokens += 85
            else:
                dims = _image_b64_dimensions(
                    part.get("image_url", {}).get("url", "")
                )
                if dims:
                    w, h = dims
                    image_tokens += _estimate_vlm_image_tokens(w, h)
                else:
                    image_tokens += 1500
        stats["image_tokens_estimate"] = image_tokens
        stats["image_count"] = sum(
            1 for p in content_parts
            if isinstance(p, dict) and p.get("type") == "image_url"
        )

    logger.info("Visual: rendered %d messages as images, kept %d tail messages",
                len(to_render_msgs), len(messages) - compact_boundary)
    return result
