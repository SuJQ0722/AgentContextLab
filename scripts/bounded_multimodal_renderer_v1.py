"""Process-local bounded pages over Hermes's existing multimodal PDF layout.

No merged recent strip, no enlarged far-history canvas, and no text/PIL fallback.
Each far page is scaled once after layout; each recent page stays at native size.
"""
import base64
import functools
import hashlib
import io
import json
import math
import os
from pathlib import Path

VERSION = 'bounded-multimodal-pages-v1'


def _png_info(value):
    from PIL import Image
    raw = base64.b64decode(value, validate=True)
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        if image.format != 'PNG':
            raise ValueError('Renderer must emit PNG, never an implicit JPEG conversion')
        rgba = image.convert('RGBA')
        dims = list(rgba.size)
        pixel = hashlib.sha256(json.dumps(dims).encode() + rgba.tobytes()).hexdigest()
    return raw, {'sha256': hashlib.sha256(raw).hexdigest(), 'pixel_sha256': pixel,
                 'dimensions': dims, 'bytes': len(raw)}


def _pdf_geometry(data, dpi, cap):
    import pymupdf
    with pymupdf.open(stream=data, filetype='pdf') as document:
        dimensions = [[math.ceil(page.rect.width * dpi / 72), math.ceil(page.rect.height * dpi / 72)]
                      for page in document]
    if not dimensions or any(min(d) < 1 or max(d) > cap for d in dimensions):
        raise ValueError('PDF page exceeds the bounded raster geometry; refusing rasterization')
    return dimensions


def _write(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('Refusing to overwrite a different rendered page/source artifact')
    else:
        with path.open('xb') as stream:
            stream.write(raw)


def render_visual_compression(render, messages, head_end, image_width=1024, font_size=16,
                              max_image_height=2048, history_max_image_height=None,
                              font_path=None, dpi=72, layout='highlight', history_scale=.75,
                              keep_rounds=1, recent_rounds=5, save_dir=None, compact_count=0,
                              stats=None, text_only=False, *, max_page_side=2048,
                              far_detail='high', recent_detail='high'):
    """Same selection policy, bounded PDF pages, explicit .75 far-page default.

    Production uses1024x2048,16pt/72dpi. Incoming historical height settings are
    capped at2048 before layout, never squeezed into that size after rasterization.
    Native protected messages are returned unchanged. Zero-scale deletion is not
    part of this full-evidence renderer and requires a different explicit policy.
    """
    integers = (head_end, image_width, font_size, max_image_height, keep_rounds, recent_rounds, compact_count, max_page_side)
    if any(isinstance(x, bool) or not isinstance(x, int) for x in integers):
        raise ValueError('Integer geometry and round boundaries required')
    if not 512 <= max_page_side <= 2048 or not 128 <= image_width <= max_page_side or font_size < 1:
        raise ValueError('Invalid bounded page/font configuration')
    if not 0 <= head_end <= len(messages) or min(keep_rounds, recent_rounds, compact_count) < 0:
        raise ValueError('Invalid history selection bounds')
    if layout not in ('highlight', 'plain', 'plain_no_header'):
        raise ValueError('Unbounded highlight_no_wrap and unknown layouts are forbidden')
    if not isinstance(dpi, (int, float)) or isinstance(dpi, bool) or not math.isfinite(dpi) or dpi <= 0:
        raise ValueError('Invalid DPI')
    if isinstance(history_scale, bool) or not isinstance(history_scale, (int, float)) or not math.isfinite(history_scale) or not 0 < history_scale <= 1:
        raise ValueError('Far-history scale must be in(0,1]; no implicit deletion')
    if far_detail != 'high' or recent_detail != 'high':
        raise ValueError('This explicit readable-page variant requires high detail for both segments')
    if text_only and not getattr(render, '_mmbc_vanilla_installed', False):
        raise ValueError('Text-only rendering requires the explicit original-table-text retention adapter')
    history_height = history_max_image_height if history_max_image_height is not None else max_image_height
    if isinstance(history_height, bool) or not isinstance(history_height, int) or min(max_image_height, history_height) < 128:
        raise ValueError('Invalid requested page height')
    heights = {'recent': min(max_image_height, max_page_side), 'history': min(history_height, max_page_side)}
    round_starts = [i for i, m in enumerate(messages) if m.get('role') == 'assistant' and m.get('tool_calls')]
    if len(round_starts) <= keep_rounds:
        return messages
    boundary = round_starts[-keep_rounds] if keep_rounds else len(messages)
    selected = messages[head_end:boundary]
    if not selected:
        return messages
    starts = [i - head_end for i in round_starts if head_end <= i < boundary]
    split = len(selected) if recent_rounds == 0 else 0 if len(starts) <= recent_rounds else starts[-recent_rounds]
    segments = [('history', selected[:split], head_end, history_scale),
                ('recent', selected[split:], head_end + split, 1.0)]
    tool_map = render._build_tool_name_map(messages)
    expected_images = sum(len(render._image_candidates(m, tool_map)) for m in selected)
    audit, output_pages, source_pdfs = [], [], []
    table_count = table_cells = 0
    count = compact_count + 1
    directory = Path(save_dir or os.getcwd())
    directory.mkdir(parents=True, exist_ok=True)
    for segment, selected_messages, offset, scale in segments:
        if not selected_messages:
            continue
        blocks = [render._format_message_block(m, layout=layout, tool_name_map=tool_map, msg_index=offset + i)
                  for i, m in enumerate(selected_messages)]
        table_count += sum(bool(b.get('table_data')) for b in blocks)
        table_cells += sum(sum(len(row) for row in b.get('table_data') or []) for b in blocks)
        if text_only and any(b.get('table_data') for b in blocks):
            raise ValueError('Vanilla formatter must keep original table text before omitting visuals')
        # Any layout failure propagates. In particular, never emit recent-only
        # history after a far-history failure, or replace an image with a caption.
        pdf = render._blocks_to_pdf_bytes(blocks, font_path, font_size, image_width, heights[segment], dpi,
                    layout=layout, fit_to_content_height=False, text_only=text_only,
                    image_cache_dir=str(directory), image_audit=audit)
        geometry = _pdf_geometry(pdf, dpi, max_page_side)
        pdf_path = directory / f'compact_{count}_{segment}.pdf'
        _write(pdf_path, pdf)
        source_pdfs.append({'segment': segment, 'path': str(pdf_path),
                            'sha256': hashlib.sha256(pdf).hexdigest(), 'page_dimensions': geometry})
        pages = render._pdf_bytes_to_image_b64_list(pdf, dpi=dpi, save_dir=None)
        if len(pages) != len(geometry):
            raise ValueError('Rasterized page count differs from the complete PDF')
        for index, page in enumerate(pages, 1):
            raw, raw_info = _png_info(page)
            if max(raw_info['dimensions']) > max_page_side or raw_info['dimensions'][0] > image_width or raw_info['dimensions'][1] > heights[segment]:
                raise ValueError('Raw raster page violates geometry; no implicit shrink-to-fit')
            raw_path = directory / f'compact_{count}_{segment}_raw_{index:03}.png'
            _write(raw_path, raw)
            final_b64 = render._downscale_image_b64(page, scale) if scale < 1 else page
            final_raw, final_info = _png_info(final_b64)
            expected_dimensions = [max(1, int(d * scale)) for d in raw_info['dimensions']]
            if final_info['dimensions'] != expected_dimensions or max(final_info['dimensions']) > max_page_side:
                raise ValueError('Rendered page normalization differs from its declared single scale')
            final_path = directory / f'compact_{count}_{segment}_{index:03}.png'
            _write(final_path, final_raw)
            output_pages.append({'segment': segment, 'page_index': index, 'segment_pages': len(pages),
                                 'source_message_start': offset, 'source_message_end_exclusive': offset + len(selected_messages),
                                 'raw_path': str(raw_path), 'raw': raw_info, 'path': str(final_path),
                                 'output': final_info, 'scale': scale, 'detail': 'high',
                                 'base64_length': len(final_b64), '_base64': final_b64})
    if not output_pages:
        raise ValueError('Nonempty selected history produced no rendered pages')
    audit.sort(key=lambda item: (item.get('message_index', -1), item['message_image_index']))
    covered = len(audit) == expected_images and all(i.get('status') in ('rendered', 'duplicate_pixels') for i in audit)
    if not text_only and not covered:
        raise ValueError('Source image occurrence coverage incomplete; refuse compressed result')
    if text_only and audit:
        raise ValueError('Text-only ablation unexpectedly rendered source visual evidence')
    content = [{'type': 'text', 'text': render.VISUAL_CONTEXT_PROMPT}]
    for page in output_pages:
        content.append({'type': 'text', 'text': f"[{page['segment'].capitalize()} page {page['page_index']}/{page['segment_pages']} — linear scale {page['scale']:g}, high detail]"})
        content.append({'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + page['_base64'], 'detail': 'high'}})
    page_records = [{k: v for k, v in p.items() if k != '_base64'} for p in output_pages]
    record = {'version': VERSION, 'compression_index': count, 'pages': page_records, 'source_pdfs': source_pdfs,
              'selection': {'head_end': head_end, 'compact_boundary': boundary, 'far_recent_split': head_end + split,
                            'keep_rounds': keep_rounds, 'recent_rounds': recent_rounds},
              'layout': {'width': image_width, 'requested_recent_height': max_image_height,
                         'requested_history_height': history_height, 'applied_heights': heights,
                         'max_page_side': max_page_side, 'font_size': font_size, 'dpi': dpi,
                         'style': layout, 'far_scale': history_scale, 'recent_scale': 1.0,
                         'far_pre_enlargement': False, 'vertical_merge': False,
                         'fit_to_content_height': False, 'detail': {'far': far_detail, 'recent': recent_detail}},
              'output_total_png_bytes': sum(p['output']['bytes'] for p in page_records),
              'output_total_base64_chars': sum(p['base64_length'] for p in page_records),
              'output_image_count': len(page_records), 'source_images': audit,
              'source_image_input_occurrences': expected_images,
              'source_image_coverage_verified': covered if not text_only else False,
              'visual_evidence_intentionally_omitted': bool(text_only),
              'structured_tables_submitted': table_count, 'table_cells_submitted': table_cells,
              'table_layout_completed': True, 'generated_captions': False}
    manifest_path = directory / f'compact_{count}_bounded_manifest.json'
    _write(manifest_path, (json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode())
    if stats is not None:
        text_chars = sum(len(str(m.get('content', ''))) for m in selected)
        stats.update(renderer_version=VERSION, source_images=audit, text_chars=text_chars,
                     text_tokens_estimate=(text_chars + 3) // 4, messages_rendered=len(selected),
                     source_image_input_occurrences=expected_images, source_image_occurrences=len(audit),
                     rendered_source_images=sum(i['status'] == 'rendered' for i in audit),
                     deduplicated_source_occurrences=sum(i['status'] == 'duplicate_pixels' for i in audit),
                     source_image_coverage_verified=record['source_image_coverage_verified'],
                     image_count=len(page_records), image_tokens_estimate=sum(render._estimate_vlm_image_tokens(*p['output']['dimensions']) for p in page_records),
                     image_token_estimate_definition='Inherited geometry estimate; not measured provider usage',
                     bounded_page_manifest=str(manifest_path), bounded_pages=page_records,
                     output_total_png_bytes=record['output_total_png_bytes'],
                     output_total_base64_chars=record['output_total_base64_chars'],
                     structured_tables_submitted=table_count, table_cells_submitted=table_cells,
                     visual_evidence_intentionally_omitted=bool(text_only),
                     omitted_source_image_occurrences=expected_images if text_only else 0,
                     generated_captions=False, bounded_layout=record['layout'])
    return list(messages[:head_end]) + [{'role': 'user', 'content': content}] + list(messages[boundary:])


def install(render, *, max_page_side=2048, far_detail='high', recent_detail='high'):
    """Replace only this interpreter's module entry; no files/upstream are edited."""
    settings = {'version': VERSION, 'max_page_side': max_page_side, 'far_detail': far_detail, 'recent_detail': recent_detail}
    installed = getattr(render, '_bounded_multimodal_renderer_v1', None)
    if installed is not None:
        if installed != settings:
            raise ValueError('Renderer already installed with different geometry/detail settings')
        return settings
    if getattr(render, '_mmbc_vanilla_installed', False):
        raise ValueError('Install bounded pagination before the vanilla table-retention adapter')
    if not isinstance(max_page_side, int) or isinstance(max_page_side, bool) or not 512 <= max_page_side <= 2048 or far_detail != 'high' or recent_detail != 'high':
        raise ValueError('Invalid explicit bounded renderer installation')
    original = render.render_visual_compression
    @functools.wraps(original)
    def bounded(*args, **kwargs):
        return render_visual_compression(render, *args, **kwargs, max_page_side=max_page_side,
                                         far_detail=far_detail, recent_detail=recent_detail)
    render.render_visual_compression = bounded
    render._bounded_multimodal_renderer_v1 = settings
    return settings
