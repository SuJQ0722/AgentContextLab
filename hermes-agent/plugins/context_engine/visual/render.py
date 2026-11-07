"""Visual rendering utilities for the visual context engine.

Renders conversation messages as images (PDF->PNG with PIL fallback).
Produces two-tier output: far_history (downscaled) + recent_history (full res).
"""

from __future__ import annotations

import base64
import gc
import hashlib
import io
import json
import logging
import math
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

    # Fallback: use ReportLab's built-in CID font for CJK support
    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        _FONT_REGISTERED = "STSong-Light"
        return "STSong-Light"
    except Exception:
        pass

    return "Helvetica"


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

def _build_tool_name_map(messages: List[Dict[str, Any]]) -> Dict[str, tuple]:
    """Map tool_call_id -> (function_name, arguments_str).

    Also builds positional mapping for datasets where tool messages lack
    tool_call_id but have sequential tool_name fields.  Uses a synthetic
    key ``__pos_<msg_index>`` so callers can look up by message index.
    """
    mapping: Dict[str, tuple] = {}
    pending_calls: List[tuple] = []
    for i, msg in enumerate(messages):
        role = msg.get("role", "")
        if role == "assistant":
            pending_calls = []
            for tc in msg.get("tool_calls") or []:
                if isinstance(tc, dict):
                    tc_id = tc.get("id", "")
                    fn = tc.get("function", {})
                    name = fn.get("name", "") if isinstance(fn, dict) else ""
                    args = fn.get("arguments", "") if isinstance(fn, dict) else ""
                    if tc_id and name:
                        mapping[tc_id] = (name, args)
                    pending_calls.append((name, args))
        elif role == "tool":
            tc_id = msg.get("tool_call_id", "")
            if tc_id:
                pass  # already mapped above
            elif pending_calls:
                name, args = pending_calls.pop(0)
                mapping[f"__pos_{i}"] = (name, args)
    return mapping


def _extract_images_from_msg(
    msg: Dict[str, Any],
    tool_name_map: Optional[Dict[str, str]] = None,
) -> List[tuple]:
    """Extract image paths/URLs from message content or tool call arguments.

    Returns list of (path, tool_name) tuples, max 2.
    """
    images: List[tuple] = []
    content = msg.get("content", "")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "image_url":
                url_obj = item.get("image_url", {})
                url = url_obj.get("url", "") if isinstance(url_obj, dict) else str(url_obj)
                if url and not url.startswith("data:"):
                    images.append((url, "user_image"))

    tool_calls = msg.get("tool_calls")
    if tool_calls:
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function", {})
            name = (fn.get("name", "") if isinstance(fn, dict) else "").lower()
            if name not in ("vision_analyze", "image_search", "image_crop", "image_zoom_in"):
                continue
            args_str = fn.get("arguments", "") if isinstance(fn, dict) else ""
            for key in ("image_url", "image_path", "image"):
                pat = re.compile(rf'"{key}"\s*:\s*"([^"]+)"')
                m = pat.search(args_str)
                if m:
                    val = m.group(1)
                    if val and not val.startswith("data:"):
                        if not any(v[0] == val for v in images):
                            images.append((val, name))
    return images[:2]


# ---------------------------------------------------------------------------
# Remote image download/cache
# ---------------------------------------------------------------------------

_IMAGE_CACHE: Dict[str, Optional[str]] = {}


def _download_image_to_cache(url: str, cache_dir: str, timeout: float = 15.0) -> Optional[str]:
    """Download a remote image URL to a local cache directory.

    Returns the local file path on success, None on failure.
    Results are cached in-memory so the same URL is only fetched once per process.
    """
    if url in _IMAGE_CACHE:
        return _IMAGE_CACHE[url]

    if not url.startswith(("http://", "https://")):
        _IMAGE_CACHE[url] = None
        return None

    try:
        import urllib.request
        import urllib.error

        os.makedirs(cache_dir, exist_ok=True)

        ext = os.path.splitext(url.split("?")[0])[1] or ".png"
        name_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        local_path = os.path.join(cache_dir, f"{name_hash}{ext}")

        if os.path.isfile(local_path):
            _IMAGE_CACHE[url] = local_path
            return local_path

        proxy_url = os.getenv("HERMES_IMAGE_PROXY", "http://10.120.0.246:7890")
        proxy_handler = urllib.request.ProxyHandler({
            "http": proxy_url,
            "https": proxy_url,
        })
        opener = urllib.request.build_opener(proxy_handler)
        req = urllib.request.Request(url, headers={"User-Agent": "HermesVisual/1.0"})
        with opener.open(req, timeout=timeout) as resp:
            data = resp.read(10 * 1024 * 1024)  # 10 MB cap
        with open(local_path, "wb") as f:
            f.write(data)

        _IMAGE_CACHE[url] = local_path
        logger.info("Visual: downloaded %s -> %s", url, local_path)
        return local_path

    except Exception as e:
        logger.warning("Visual: failed to download image %s: %s", url, e)
        _IMAGE_CACHE[url] = None
        return None


def _resolve_image_path(
    img_ref: str,
    cache_dir: Optional[str] = None,
) -> Optional[str]:
    """Resolve an image reference (local path or URL) to a local file path.

    Local paths are returned as-is if they exist.
    Remote URLs are downloaded to cache_dir/source_images/.
    """
    expanded = os.path.expanduser(img_ref)
    if os.path.isfile(expanded):
        return expanded

    if img_ref.startswith(("http://", "https://")) and cache_dir:
        source_dir = os.path.join(cache_dir, "source_images")
        return _download_image_to_cache(img_ref, source_dir)

    return None


_TABLE_TRAILER_RE = re.compile(r"\[(\d+)\s+rows?\s*[x×]\s*(\d+)\s+columns?\]")
_PIPE_TABLE_RE = re.compile(r"^\s*\|.*\|.*\|", re.MULTILINE)


def _detect_table(text: str) -> Optional[List[List[str]]]:
    """Detect DataFrame repr or pipe-table in text. Returns rows or None."""
    if _PIPE_TABLE_RE.search(text):
        rows: List[List[str]] = []
        for line in text.split("\n"):
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= {"-", ":", " "} for c in cells):
                continue
            rows.append(cells)
        if len(rows) >= 2:
            return rows[:30]

    if _TABLE_TRAILER_RE.search(text) or re.search(r"^.+\s{3,}\S+", text, re.MULTILINE):
        lines = text.split("\n")
        data_lines = []
        for line in lines:
            stripped = line.rstrip()
            if not stripped:
                continue
            if stripped.startswith("[") and stripped.endswith("]"):
                continue
            if "dtype:" in stripped or "Name:" in stripped:
                continue
            data_lines.append(stripped)
        if len(data_lines) < 2:
            return None
        rows = []
        for line in data_lines[:15]:
            cells = re.split(r"\s{2,}", line.strip())
            if cells:
                rows.append(cells)
        if len(rows) >= 2:
            max_cols = max(len(r) for r in rows)
            if max_cols >= 2:
                for i, r in enumerate(rows):
                    while len(r) < max_cols:
                        r.append("")
                    rows[i] = r[:max_cols]
                return rows[:15]
    return None


def _strip_table_text(body: str, inner_table_text: str) -> str:
    """Remove the tabular portion from body text to avoid duplication with rendered table."""
    output_match = re.search(r'["\']output["\']\s*:\s*["\'](.+?)["\'](?:\s*,|\s*\})', body, re.DOTALL)
    if output_match:
        return body[:output_match.start(1)] + "[table]" + body[output_match.end(1):]

    if inner_table_text in body:
        return body.replace(inner_table_text, "[table]")

    lines_to_remove = set()
    for line in inner_table_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"\s{2,}", stripped) or stripped.startswith("|"):
            lines_to_remove.add(stripped)
    if lines_to_remove:
        result_lines = [l for l in body.split("\n") if l.strip() not in lines_to_remove]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(result_lines)).strip()
    return body


def _format_message_block(
    msg: Dict[str, Any],
    layout: str = "highlight",
    tool_name_map: Optional[Dict[str, str]] = None,
    msg_index: int = -1,
) -> Dict[str, Any]:
    role = msg.get("role", "unknown")
    body_parts: List[str] = []

    if role == "tool":
        tool_call_id = msg.get("tool_call_id", "")
        tc_entry = (tool_name_map or {}).get(tool_call_id) or \
                   (tool_name_map or {}).get(f"__pos_{msg_index}") or ("", "")
        fn_name = tc_entry[0] if isinstance(tc_entry, tuple) else tc_entry
        if not fn_name:
            fn_name = msg.get("tool_name", "")
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
    if isinstance(content, dict):
        output_val = content.get("output", "")
        if isinstance(output_val, str) and output_val.strip():
            body_parts.append(output_val)
    elif isinstance(content, str) and content.strip():
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

    images = _extract_images_from_msg(msg, tool_name_map)

    _DATA_FILE_RE = re.compile(r"\.(csv|parquet|tsv|xlsx?|feather|h5|hdf5|jsonl?)\b", re.IGNORECASE)

    table_data = None
    table_source = ""
    if role == "tool" and body:
        tool_call_id = msg.get("tool_call_id", "")
        tc_entry = (tool_name_map or {}).get(tool_call_id) or \
                   (tool_name_map or {}).get(f"__pos_{msg_index}") or ("", "")
        if isinstance(tc_entry, tuple):
            table_source, tc_args = tc_entry
        else:
            table_source, tc_args = tc_entry, ""
        if not table_source:
            table_source = msg.get("tool_name", "")
        if table_source in ("execute_code", "terminal") and _DATA_FILE_RE.search(tc_args or body):
            inner = body
            output_match = re.search(r"['\"]output['\"]\s*:\s*['\"](.+?)['\"](?:\s*,|\s*\})", body, re.DOTALL)
            if output_match:
                inner = output_match.group(1).replace("\\n", "\n").replace("\\'", "'")
            table_data = _detect_table(inner)
            if table_data:
                body = _strip_table_text(body, inner)

    return {"role": role, "header": header, "body": body, "images": images, "table_data": table_data, "table_source": table_source}


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
    blocks: List[Dict[str, Any]],
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


def _render_image_flowable(image_path: str, max_height_pt: float = 60.0, max_width_pt: float = 150.0):
    """Load an image from local path and return a ReportLab Image flowable, or None."""
    from reportlab.platypus import Image as RLImage
    from PIL import Image as PILImage

    try:
        path = os.path.expanduser(image_path)
        if not os.path.isfile(path):
            return None
        img = PILImage.open(path)
        w, h = img.size
        img.close()
        if h <= 0 or w <= 0:
            return None
        scale = min(1.0, max_height_pt / h, max_width_pt / w)
        return RLImage(path, width=w * scale, height=h * scale)
    except Exception:
        return None


def _render_table_flowable(table_data: List[List[str]], font_name: str, font_size: int, page_pt_width: float):
    """Create a compact ReportLab Table flowable from detected table data."""
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors

    if not table_data:
        return None
    max_cols = max(len(r) for r in table_data)
    cell_font_size = max(9, font_size + 2)
    # Wide tables (many cols) can use more page width; narrow tables stay compact
    max_table_frac = min(0.98, 0.55 + max_cols * 0.12)
    max_cell_chars = max(16, int(page_pt_width * max_table_frac / (max_cols * cell_font_size * 0.30)))
    truncated = []
    for row in table_data[:15]:
        truncated.append([c[:max_cell_chars] for c in row])

    try:
        col_widths = []
        for col_idx in range(max_cols):
            max_len = max((len(truncated[r][col_idx]) if col_idx < len(truncated[r]) else 0) for r in range(len(truncated)))
            col_widths.append(max(cell_font_size * 3, min(max_len * cell_font_size * 0.65 + 6, page_pt_width * max_table_frac / max_cols)))
        total_w = sum(col_widths)
        if total_w > page_pt_width * max_table_frac:
            scale = page_pt_width * max_table_frac / total_w
            col_widths = [w * scale for w in col_widths]

        t = Table(truncated, colWidths=col_widths)
        style_cmds = [
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("FONTSIZE", (0, 0), (-1, -1), cell_font_size),
            ("LEADING", (0, 0), (-1, -1), cell_font_size + 3),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#AAAAAA")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAEAEA")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        t.setStyle(TableStyle(style_cmds))
        t.hAlign = "LEFT"
        return t
    except Exception:
        return None


def _blocks_to_pdf_bytes(
    blocks: List[Dict[str, Any]],
    font_path: Optional[str],
    font_size: int,
    page_width: int,
    max_image_height: int,
    dpi: int,
    layout: str = "highlight",
    fit_to_content_height: bool = False,
    text_only: bool = False,
    image_cache_dir: Optional[str] = None,
) -> bytes:
    """Render blocks to PDF with per-message paragraphs, text-wrapped images and tables."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.platypus.flowables import ImageAndFlowables
    from xml.sax.saxutils import escape

    font_name = _resolve_and_register_font(font_path)

    page_pt_width = page_width * 72.0 / dpi
    if layout == "highlight_no_wrap":
        page_pt_width = 8192 * 72.0 / dpi
    max_page_pt_height = max_image_height * 72.0 / dpi

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

    spacer_height = max(2.0, font_size * 0.3)
    story: List[Any] = []

    caption_font_size = font_size * 2
    caption_style = ParagraphStyle(
        name="Caption",
        fontName=font_name,
        fontSize=caption_font_size,
        leading=int(caption_font_size * 1.2) + 1,
        textColor=colors.HexColor("#D92D20"),
        alignment=2,  # TA_RIGHT
        spaceBefore=0,
        spaceAfter=0,
    )

    def _make_para(block):
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
            markup = f"{label_markup}&nbsp;{body_markup}" if body_markup else label_markup
        elif layout == "plain_no_header":
            markup = escape(body_text)
        else:
            markup = escape(f"[{header_text}] {body_text}")
        try:
            return Paragraph(markup, body_style)
        except Exception:
            return Paragraph(escape(body_text[:500]), body_style)

    def _make_img_flowable(img_path):
        return _render_image_flowable(img_path, max_height_pt=120.0, max_width_pt=200.0)

    class _TableFloat(Table):
        """A captioned table implementing ImageAndFlowables' size protocol.

        Unlike an image, text must not shrink to fit the remaining page height.
        Returning its real size lets the surrounding flowable move to the next
        page when necessary.
        """

        def _restrictSize(self, availWidth, availHeight):
            return self._width, self._height

        def _unRestrictSize(self):
            pass

    # SimpleDocTemplate's frame has 6pt padding on each side.
    frame_width = page_pt_width - 12

    def _make_captioned_table(table_data, table_source):
        table_f = _render_table_flowable(table_data, font_name, font_size, frame_width)
        if not table_f:
            return None
        caption_text = table_source.replace("_", " ") if table_source else "output"
        cap = Paragraph(
            f'<font color="#D92D20"><b>{escape(caption_text)}</b></font>',
            caption_style,
        )
        return cap, table_f

    # Pre-build paragraphs and side elements for each block
    block_paras = []  # (Paragraph, images_tuples, table_data, table_source)
    for block in blocks:
        para = _make_para(block)
        images = block.get("images") or []
        table_data = block.get("table_data")
        table_source = block.get("table_source", "")
        block_paras.append((para, images, table_data, table_source))

    if text_only:
        block_paras = [(p, [], None, "") for p, _, td, ts in block_paras]

    i = 0
    while i < len(block_paras):
        para, images, table_data, table_source = block_paras[i]

        # Build image flowables for this block
        img_results = []  # (tool_name, Image flowable)
        for img_path, tool_name in images:
            resolved = _resolve_image_path(img_path, image_cache_dir) if img_path else None
            if resolved:
                img_f = _make_img_flowable(resolved)
                if img_f:
                    img_results.append((tool_name, img_f))

        if img_results:
            # Collect paragraphs to wrap around images: current block + following blocks
            all_wrap = [para, Spacer(1, spacer_height)]
            j = i + 1
            while j < len(block_paras):
                next_para, next_imgs, next_td, next_ts = block_paras[j]
                has_own_imgs = any(
                    _resolve_image_path(p, image_cache_dir) is not None
                    for p, _ in (next_imgs or [])
                    if p
                )
                if has_own_imgs or next_td:
                    break
                all_wrap.append(next_para)
                all_wrap.append(Spacer(1, spacer_height))
                j += 1

            # Split wrap flowables across images
            n_imgs = len(img_results)
            chunk = max(1, len(all_wrap) // n_imgs)

            try:
                for idx, (img_name, img_f) in enumerate(img_results):
                    cap_text = img_name.replace("_", " ") if img_name else "image"
                    story.append(Paragraph(
                        f'<font color="#D92D20"><b>{escape(cap_text)}</b></font>',
                        caption_style,
                    ))
                    if idx < n_imgs - 1:
                        portion = all_wrap[idx * chunk : (idx + 1) * chunk]
                    else:
                        portion = all_wrap[idx * chunk :]
                    if not portion:
                        portion = [Paragraph("&nbsp;", body_style)]
                    story.append(ImageAndFlowables(
                        img_f, portion,
                        imageLeftPadding=4,
                        imageRightPadding=0,
                        imageTopPadding=0,
                        imageBottomPadding=2,
                        imageSide="right",
                    ))
            except Exception:
                story.append(para)
                story.append(Spacer(1, spacer_height))
                for _, img_f in img_results:
                    story.append(img_f)
                j = i + 1

            i = j
            continue

        # No images — check if there's a table to wrap text around
        if table_data:
            result = _make_captioned_table(table_data, table_source)
            if result:
                cap, tf = result
                # Wrap only beside the caption/table height; remaining text
                # returns to the full frame width, including on later pages.
                wrap_flowables = [para, Spacer(1, spacer_height)]
                j = i + 1
                while j < len(block_paras):
                    next_para, next_imgs, next_td, next_ts = block_paras[j]
                    if next_td or any(
                        _resolve_image_path(p, image_cache_dir) is not None
                        for p, _ in (next_imgs or []) if p
                    ):
                        break
                    wrap_flowables.extend([next_para, Spacer(1, spacer_height)])
                    j += 1
                tw, _ = tf.wrap(frame_width, 10_000_000)
                side_table = _TableFloat([[cap], [tf]], colWidths=[tw])
                side_table.setStyle(TableStyle([
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]))
                _, side_height = side_table.wrap(frame_width, 10_000_000)
                min_text_width = max(font_size * 12, frame_width * 0.25)
                if (frame_width - tw - 4 >= min_text_width
                        and side_height + 2 <= max_page_pt_height - 12):
                    story.append(ImageAndFlowables(
                        side_table, wrap_flowables,
                        imageLeftPadding=4, imageRightPadding=0,
                        imageTopPadding=0, imageBottomPadding=2,
                        imageSide="right",
                    ))
                else:
                    # Wide or page-tall tables remain ordinary, splittable
                    # flowables rather than overflowing a narrow side column.
                    story.extend([para, Spacer(1, 1), cap, tf])
                    j = i + 1
                i = j
                continue
            else:
                story.append(para)
        else:
            story.append(para)

        story.append(Spacer(1, spacer_height))
        i += 1

    if not story:
        story.append(Paragraph("&nbsp;", body_style))

    page_pt_height = max_page_pt_height
    if fit_to_content_height and story:
        try:
            from reportlab.pdfgen.canvas import Canvas

            measure_canvas = Canvas(io.BytesIO())
            story_height = sum(
                float(flowable.wrapOn(measure_canvas, frame_width, 10_000_000.0)[1])
                for flowable in story
            )
            padding = max(24.0, float(body_style.leading) * 3.0)
            page_pt_height = min(max_page_pt_height, max(1.0, story_height + padding))
        except Exception as e:
            logger.debug("Visual: failed to estimate PDF story height: %s", e)

    page_size = (page_pt_width, page_pt_height)

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


def _clear_stale_render_outputs(save_dir: str) -> None:
    """Remove image/PDF sidecars from a previous run in the same attempt dir."""
    if not save_dir or not os.path.isdir(save_dir):
        return
    for name in os.listdir(save_dir):
        if (
            name.startswith("old_")
            or name.startswith("recent_")
            or name.startswith("compact_")
        ):
            try:
                os.remove(os.path.join(save_dir, name))
            except OSError as e:
                logger.warning("Visual: failed to remove stale sidecar %s: %s", name, e)


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
    history_max_image_height: Optional[int] = None,
    font_path: Optional[str] = None,
    dpi: int = 72,
    layout: str = "highlight",
    history_scale: float = 0.75,
    keep_rounds: int = 1,
    recent_rounds: int = 5,
    save_dir: Optional[str] = None,
    compact_count: int = 0,
    stats: Optional[Dict[str, Any]] = None,
    text_only: bool = False,
) -> List[Dict[str, Any]]:
    """Render messages as images and return compressed message list.

    Split policy:
      - The last ``keep_rounds`` rounds stay in TEXT form (tail, never rendered).
      - Of the messages that ARE rendered, the last ``recent_rounds`` rounds
        keep full resolution (``recent_<N>.png``); everything before them uses
        larger history pages, then each page is downscaled by ``history_scale``
        and sent as a separate old-history image. Keeping old pages separate
        avoids creating one very tall request image.
    """
    history_image_height = int(history_max_image_height or max_image_height)

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
    if save_dir and count == 1:
        _clear_stale_render_outputs(effective_save_dir)

    def _render_segment(
        seg_msgs: List[Dict[str, Any]],
        prefix: str,
        segment_image_width: int,
        segment_max_image_height: int,
        fit_to_content_height: bool = False,
        msg_offset: int = 0,
    ) -> tuple:
        """Render a slice of messages.

        Returns (pdf_bytes, png_b64_pages). Both are None on empty input;
        on PDF-render failure, falls back to PIL path (pdf_bytes will be b"").
        """
        if not seg_msgs:
            return None, None
        blocks = [_format_message_block(m, layout=layout, tool_name_map=tool_name_map, msg_index=msg_offset + i) for i, m in enumerate(seg_msgs)]
        # Try the PDF path first so we get raw vector bytes too.
        pdf_bytes = b""
        try:
            pdf_bytes = _blocks_to_pdf_bytes(
                blocks, font_path, font_size, segment_image_width, segment_max_image_height, dpi,
                layout=layout,
                fit_to_content_height=fit_to_content_height,
                text_only=text_only,
                image_cache_dir=effective_save_dir,
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
                    blocks, font_size, segment_image_width, segment_max_image_height, save_dir, prefix
                )
        else:
            images = _text_to_images_fallback(
                blocks, font_size, segment_image_width, segment_max_image_height, save_dir, prefix
            )

        if not images:
            return pdf_bytes, None
        return pdf_bytes, images

    # Render recent first — it's the critical path. If it fails, abandon compression.
    try:
        recent_round_count = sum(
            1 for msg in recent_msgs
            if msg.get("role") == "assistant" and msg.get("tool_calls")
        )
        recent_single_page_height = max_image_height * max(1, recent_round_count)
        recent_pdf, recent_pages = _render_segment(
            recent_msgs,
            f"compact_{count}_recent",
            image_width,
            recent_single_page_height,
            fit_to_content_height=True,
            msg_offset=head_end + split_point,
        )
    except Exception as e:
        logger.error("Visual: recent rendering failed: %s", e)
        return messages
    recent_b64 = None
    if recent_pages:
        if len(recent_pages) == 1:
            recent_b64 = recent_pages[0]
        else:
            logger.warning(
                "Visual: recent segment overflowed single-page render into %d pages; merging fallback.",
                len(recent_pages),
            )
            recent_b64 = _merge_images_vertical(recent_pages)
    if recent_b64 is not None:
        _save_merged_image(recent_b64, effective_save_dir, f"recent_{count}.png")

    # Render far history as larger pages, then downscale each page separately.
    # Far failure is non-fatal — we still emit recent-only compression.
    # history_scale=0 means skip far history entirely (no history image).
    history_b64_pages: List[str] = []
    history_pdf: bytes = b""
    if history_scale > 0:
        try:
            history_render_width = image_width
            history_render_height = history_image_height
            if history_scale < 1.0:
                history_render_width = max(1, math.ceil(image_width / history_scale))
                history_render_height = max(1, math.ceil(history_image_height / history_scale))
            history_pdf, history_pages = _render_segment(
                far_msgs,
                f"compact_{count}_history",
                history_render_width,
                history_render_height,
                msg_offset=head_end,
            )
            if history_pages:
                page_count = len(history_pages)
                width = max(3, len(str(page_count)))
                for page_idx, history_page in enumerate(history_pages, start=1):
                    history_b64 = history_page
                    if history_scale < 1.0:
                        history_b64 = _downscale_image_b64(history_page, scale=history_scale)
                    history_b64_pages.append(history_b64)
                    if page_count == 1:
                        filename = f"old_{count}.png"
                    else:
                        filename = f"old_{count}_{page_idx:0{width}d}.png"
                    _save_merged_image(history_b64, effective_save_dir, filename)
                logger.info(
                    "Visual: rendered %d old-history page(s) at %dx%d before downscale",
                    page_count,
                    history_render_width,
                    history_render_height,
                )
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

    if not recent_b64 and not history_b64_pages:
        logger.warning("Visual: no images generated.")
        return messages

    # Build multimodal content
    content_parts: List[Dict[str, Any]] = [
        {"type": "text", "text": VISUAL_CONTEXT_PROMPT},
    ]
    if history_b64_pages:
        content_parts.append({
            "type": "text",
            "text": f"[Older history — lower resolution, {len(history_b64_pages)} page(s)]",
        })
        for page_idx, history_b64 in enumerate(history_b64_pages, start=1):
            if len(history_b64_pages) > 1:
                content_parts.append({
                    "type": "text",
                    "text": f"[Older history page {page_idx}/{len(history_b64_pages)}]",
                })
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{history_b64}", "detail": "low"},
            })
    if recent_b64:
        if history_b64_pages:
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
