"""One paginated history, last seven pages, last two at native resolution.

All source PDF pages are archived; only selected pages are rasterized/encoded.
No model, upload, or summary calls. Original head/tail messages stay unchanged.
"""
import base64
import functools
import hashlib
import io
import json
from unittest.mock import patch
from pathlib import Path

VERSION = 'page-window-seven-v1'
MAX_PIXELS = 1280 * 2048


def settings(config=None):
    config = config or {}
    value = config.get('visual_page_window')
    if value is None:
        value = json.loads((Path(__file__).resolve().parents[1] / 'configs/experiment.json').read_text()).get('visual_page_window')
    return value


def validate(config):
    if config.get('version') != VERSION or config.get('width') not in (1024, 1152, 1280) or config.get('height') != 2048:
        raise ValueError('Unsupported explicit seven-page geometry')
    if config.get('table_font_size',16) not in (16,18) or not .5 <= config.get('table_max_width_fraction',.98) <= .98:
        raise ValueError('Invalid readable table font/width settings')
    if config.get('pages') != 7 or config.get('recent_pages') != 2 or config.get('history_scale') != .75:
        raise ValueError('Expected seven pages, last two native, earlier pages .75x')


def sha(raw): return hashlib.sha256(raw).hexdigest()


def write(path, raw):
    if path.exists():
        if path.read_bytes() != raw: raise ValueError('Immutable page artifact differs')
    else:
        with path.open('xb') as f: f.write(raw)


def render_history(render, messages, head_end, *, config, keep_rounds=1,
                   save_dir=None, compact_count=0, stats=None, text_only=False,
                   font_path=None, **unused):
    import pymupdf
    from PIL import Image
    validate(config)
    starts = [i for i, m in enumerate(messages) if m.get('role') == 'assistant' and m.get('tool_calls')]
    if len(starts) <= keep_rounds: return messages
    boundary = starts[-keep_rounds] if keep_rounds else len(messages)
    selected = messages[head_end:boundary]
    if not selected: return messages
    if text_only and not getattr(render, '_mmbc_vanilla_installed', False):
        raise ValueError('Vanilla table-text preservation adapter required')
    directory = Path(save_dir); directory.mkdir(parents=True, exist_ok=True)
    tool_map = render._build_tool_name_map(messages)
    blocks = [render._format_message_block(m, layout='highlight', tool_name_map=tool_map, msg_index=head_end+i) for i,m in enumerate(selected)]
    audit = []
    original_table = render._render_table_flowable
    def sized_table(data, font_name, font_size, frame_width):
        # Native helper adds 2pt. Keep the requested table size independent of body.
        return original_table(data, font_name, config.get('table_font_size',16)-2,
                              frame_width * config.get('table_max_width_fraction',.98)/.98)
    with patch.object(render, '_render_table_flowable', sized_table):
        pdf = render._blocks_to_pdf_bytes(blocks, font_path, 16, config['width'], config['height'], 72,
                  layout='highlight', fit_to_content_height=False, text_only=text_only,
                  image_cache_dir=str(directory), image_audit=audit)
    expected_images = sum(len(render._image_candidates(m, tool_map)) for m in selected)
    if not text_only and (len(audit) != expected_images or any(a.get('status') not in ('rendered','duplicate_pixels') for a in audit)):
        raise ValueError('Full source PDF image coverage incomplete')
    count = compact_count + 1
    pdf_path = directory / f'compact_{count}_window_source.pdf'; write(pdf_path, pdf)
    pages = []
    with pymupdf.open(stream=pdf, filetype='pdf') as document:
        total = len(document)
        first = max(0, total - 7)
        for index in range(first, total):
            page = document[index]
            if page.rect.width > config['width'] + .01 or page.rect.height > 2048.01:
                raise ValueError('PDF page exceeded geometry')
            raw = page.get_pixmap(dpi=72, alpha=False).tobytes('png')
            recent = index >= max(first, total-2)
            scale = 1. if recent else .75
            with Image.open(io.BytesIO(raw)) as source:
                source.load(); raw_dimensions = list(source.size)
                final = source.copy() if recent else source.resize(tuple(max(1,int(d*scale)) for d in source.size), Image.Resampling.LANCZOS)
                buf=io.BytesIO(); final.save(buf,format='WEBP',lossless=True,quality=80,method=4,exact=True); encoded=buf.getvalue()
                with Image.open(io.BytesIO(encoded)) as decoded:
                    if decoded.convert('RGBA').tobytes() != final.convert('RGBA').tobytes(): raise ValueError('WebP pixel mismatch')
                dimensions=list(final.size)
            raw_path=directory/f'compact_{count}_window_{index+1:03}.png';write(raw_path,raw)
            path=raw_path.with_suffix('.webp');write(path,encoded)
            pages.append({'source_page':index+1,'segment':'recent' if recent else 'history','scale':scale,
                          'raw_path':str(raw_path),'raw_sha256':sha(raw),'raw_dimensions':raw_dimensions,
                          'path':str(path),'sha256':sha(encoded),'dimensions':dimensions,'bytes':len(encoded)})
    manifest={'version':VERSION,'settings':dict(config),'source_pdf':str(pdf_path),'source_pdf_sha256':sha(pdf),
              'source_page_count':total,'omitted_prefix_pages':first,'pages':pages,'source_images':audit,
              'selection':'paginate_once_then_last_seven_last_two_recent','text_only':text_only,
              'rendered_source_coverage_is_not_selected_page_coverage':True}
    manifest_path=directory/f'compact_{count}_window_manifest.json';write(manifest_path,(json.dumps(manifest,indent=2)+'\n').encode())
    content=[{'type':'text','text':render.VISUAL_CONTEXT_PROMPT}]
    for segment in ('history','recent'):
        segment_pages=[p for p in pages if p['segment']==segment]
        for i,page in enumerate(segment_pages,1):
            content.extend([{'type':'text','text':f"[{segment.capitalize()} page {i}/{len(segment_pages)} — linear scale {page['scale']:g}, high detail]"},
                            {'type':'image_url','image_url':{'url':'data:image/webp;base64,'+base64.b64encode(Path(page['path']).read_bytes()).decode(),'detail':'high'}}])
    if stats is not None:
        stats.update(renderer_version=VERSION,page_window_manifest=str(manifest_path),image_count=len(pages),
                     messages_rendered=len(selected),source_page_count=total,omitted_prefix_pages=first,
                     image_tokens_estimate=sum(render._estimate_vlm_image_tokens(*p['dimensions']) for p in pages),
                     image_token_estimate_definition='Geometry heuristic; not provider usage',
                     source_image_input_occurrences=sum(len(render._image_candidates(m,tool_map)) for m in selected),
                     rendered_source_images=sum(a.get('status')=='rendered' for a in audit),
                     source_image_coverage_verified=False,selected_page_coverage_unknown=True,
                     transport_image_bytes=sum(p['bytes'] for p in pages))
    return list(messages[:head_end])+[{'role':'user','content':content}]+list(messages[boundary:])


def install(render, config):
    validate(config)
    old=getattr(render,'_page_window_renderer_v1',None)
    if old is not None:
        if old != config: raise ValueError('Page-window configuration changed in process')
        return
    @functools.wraps(render.render_visual_compression)
    def wrapped(messages, head_end, **kwargs):
        return render_history(render,messages,head_end,config=config,**kwargs)
    render.render_visual_compression=wrapped
    render._page_window_renderer_v1=dict(config)


def registered_pages(directory):
    from PIL import Image
    directory=Path(directory).resolve(); result=set()
    def artifact(path,digest):
        path=Path(path).resolve()
        if not path.is_relative_to(directory): raise ValueError('Artifact outside canvas directory')
        raw=path.read_bytes()
        if sha(raw)!=digest: raise ValueError('Page-window artifact hash mismatch')
        return raw
    for path in directory.glob('compact_*_window_manifest.json'):
        m=json.loads(path.read_text());validate(m['settings'])
        if m['version']!=VERSION:raise ValueError('Unknown page window')
        artifact(m['source_pdf'],m['source_pdf_sha256'])
        total=m['source_page_count']; first=max(0,total-7)
        if m['omitted_prefix_pages']!=first or [p['source_page'] for p in m['pages']]!=list(range(first+1,total+1)):
            raise ValueError('Page-window selection mismatch')
        for p in m['pages']:
            recent=p['source_page']>max(first,total-2);scale=1. if recent else .75
            if p['segment']!=('recent' if recent else 'history') or p['scale']!=scale:raise ValueError('Page age/scale mismatch')
            raw=artifact(p['raw_path'],p['raw_sha256']);encoded=artifact(p['path'],p['sha256'])
            with Image.open(io.BytesIO(raw)) as source, Image.open(io.BytesIO(encoded)) as image:
                source.load();image.load()
                if source.size!=(m['settings']['width'],2048) or source.size!=tuple(p['raw_dimensions']): raise ValueError('Raw geometry differs')
                expected=source.copy() if recent else source.resize(tuple(int(d*scale) for d in source.size),Image.Resampling.LANCZOS)
                if image.format!='WEBP' or list(image.size)!=p['dimensions'] or image.convert('RGBA').tobytes()!=expected.convert('RGBA').tobytes() or len(encoded)!=p['bytes']:
                    raise ValueError('Selected page pixel/size mismatch')
            result.add(p['sha256'])
    return result
