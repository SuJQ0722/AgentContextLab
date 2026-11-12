#!/usr/bin/env python3
"""DSH IPC entry applying exactly the new bounded Hermes visual implementation."""
import hashlib
import os,json
from pathlib import Path
import sys
import shared_context_policy as shared

PROTOCOL='bc-bounded-pages-v1'
SOURCES=('shared_context_bounded_bc_v1.py','rq3_bounded_renderer_v2.py','bounded_lossless_transport_v1.py','page_window_renderer_v1.py')
_original_configure=shared.configure_engine
_original_hashes=shared.implementation_hashes
_original_apply=shared.apply_policy
_last_render_stats={}

def configure(engine,strategy,config):
    if strategy!='visual' or config.get('strategy_config',{}).get('bounded_bc_protocol')!=PROTOCOL:
        raise ValueError('Explicit bounded BC visual policy required')
    settings=config.get('strategy_config',{})
    required={'history_scale':.75,'font_size':16,'image_width':1024,'max_image_height':2048,
              'history_max_image_height':2048,'keep_rounds':1,'recent_rounds':5,'text_only':False}
    if any(settings.get(k)!=v for k,v in required.items()):raise ValueError('Bounded BC policy differs')
    _original_configure(engine,strategy,config)
    from plugins.context_engine.visual import render
    from rq3_bounded_renderer_v2 import install
    from bounded_lossless_transport_v1 import install as encode
    window=json.loads(os.environ.get('ACL_PAGE_WINDOW_RENDERER','null'))
    if window:
        from page_window_renderer_v1 import install as window_install
        window_install(render,window)
    else: install(render)
    if not window and not getattr(render,'_bounded_lossless_transport_v1',False):encode(render)
    if not getattr(render,'_bounded_bc_stats_capture_v1',False):
        original=render.render_visual_compression
        def capture(*args,**kwargs):
            result=original(*args,**kwargs)
            _last_render_stats.clear();_last_render_stats.update(kwargs.get('stats') or {})
            return result
        render.render_visual_compression=capture
        render._bounded_bc_stats_capture_v1=True

def hashes(strategy):
    result=_original_hashes(strategy)
    result.update({'scripts/'+n:hashlib.sha256((shared.ROOT/'scripts'/n).read_bytes()).hexdigest() for n in SOURCES})
    return result

def apply_policy(request):
    _last_render_stats.clear()
    result=_original_apply(request)
    if result.get('compression_triggered') and _last_render_stats:
        result.setdefault('render_stats',{}).update(_last_render_stats)
    return result

def install():
    shared.configure_engine=configure
    shared.implementation_hashes=hashes
    shared.apply_policy=apply_policy

if __name__=='__main__':
    install();shared.main()
