#!/usr/bin/env python3
"""Pixel-equivalent, bounded-memory conversion of trusted generated RQ3 PDFs.

No DPI, typography, layout, image detail or scale changes. Normal documents use
Hermes's original converter. Large pages are rasterized one at a time, with the
same Poppler defaults and exact grayscale crop predicate computed in stripes.
"""
import base64
from contextlib import contextmanager
import functools
import gc
import io
import math
import os
import re
import tempfile
import threading

MAX_PAGE_PIXELS=500_000_000
LARGE_PAGE_PIXELS=100_000_000
STRIPE_ROWS=1024
_LIMIT_LOCK=threading.RLock()
IMPLEMENTATION={'name':'rq3-pdf-bounded-memory-v1','max_page_pixels':MAX_PAGE_PIXELS,
    'large_page_threshold':LARGE_PAGE_PIXELS,'stripe_rows':STRIPE_ROWS,
    'normal_path':'Unmodified original Hermes converter',
    'large_path':'Poppler same DPI, one page per call, disk PPM, exact stripe grayscale crop; PNG optimize=True',
    'crop_predicate':'abs(gray-bg_median)>5; exact integer equivalent abs(2*gray-2*bg_median)>10',
    'scale_layout_dpi_unchanged':True,'pillow_limit_restored':True,'trusted_generated_pdfs_only':True}


def page_pixels(pdf_bytes,dpi=72):
    from pdf2image import pdfinfo_from_bytes
    if not isinstance(dpi,(int,float)) or not math.isfinite(dpi) or dpi<=0:raise ValueError('Invalid DPI')
    info=pdfinfo_from_bytes(pdf_bytes);pages=info['Pages']
    if not isinstance(pages,int) or pages<1:raise ValueError('Invalid PDF page count')
    details=pdfinfo_from_bytes(pdf_bytes,first_page=1,last_page=pages)
    result=[]
    for page in range(1,pages+1):
        value=next((v for k,v in details.items() if re.fullmatch(r'Page\s+'+str(page)+r' size',k)),None)
        if value is None and pages==1:value=details.get('Page size')
        match=re.match(r'^([\d.eE+-]+) x ([\d.eE+-]+) pts',str(value))
        if not match:raise ValueError('Missing per-page PDF geometry')
        width,height=[float(x) for x in match.groups()]
        if not all(math.isfinite(x) and x>0 for x in (width,height)):raise ValueError('Invalid PDF geometry')
        pixels=math.ceil(width*dpi/72)*math.ceil(height*dpi/72)
        if pixels>MAX_PAGE_PIXELS:raise ValueError(f'Trusted PDF page {page} exceeds {MAX_PAGE_PIXELS} pixel cap')
        result.append(pixels)
    return result


@contextmanager
def trusted_pillow_limit():
    from PIL import Image
    # Pillow uses a global variable: serialize these trusted conversion scopes.
    with _LIMIT_LOCK:
        previous=Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS=MAX_PAGE_PIXELS
        try:yield
        finally:Image.MAX_IMAGE_PIXELS=previous


def stripe_crop_box(img,stripe_rows=STRIPE_ROWS):
    """Exactly reproduce Hermes np.float64 grayscale crop, without full arrays."""
    import numpy as np
    if stripe_rows<1:raise ValueError('stripe_rows must be positive')
    corner=img.crop((0,0,min(2,img.width),min(2,img.height)))
    try:
        corner_gray=corner.convert('L')
        try:bg2=int(2*np.median(np.asarray(corner_gray)))
        finally:corner_gray.close()
    finally:corner.close()
    left=img.width;right=-1;top=img.height;bottom=-1
    for y in range(0,img.height,stripe_rows):
        stripe=img.crop((0,y,img.width,min(img.height,y+stripe_rows)))
        try:
            gray=stripe.convert('L')
            try:
                values=np.asarray(gray,dtype=np.int16)
                values*=2;values-=bg2;np.abs(values,out=values)
                mask=values>10
                cols=np.flatnonzero(mask.any(axis=0));rows=np.flatnonzero(mask.any(axis=1))
                if cols.size and rows.size:
                    left=min(left,int(cols[0]));right=max(right,int(cols[-1]))
                    top=min(top,y+int(rows[0]));bottom=max(bottom,y+int(rows[-1]))
                del values,mask,cols,rows
            finally:gray.close()
        finally:stripe.close()
    if right<0:return None
    return max(0,left-1),max(0,top-1),min(img.width,right+2),min(img.height,bottom+2)


def convert_pdf_bounded(pdf_bytes,dpi=72,save_dir=None,save_prefix='page',_validated_pixels=None):
    from pdf2image import convert_from_bytes
    counts=page_pixels(pdf_bytes,dpi) if _validated_pixels is None else _validated_pixels
    result=[]
    with trusted_pillow_limit(), tempfile.TemporaryDirectory(prefix='rq3-pdf-') as folder:
        for page in range(1,len(counts)+1):
            # Disk output avoids a second full-page PPM byte buffer in stdout.
            images=convert_from_bytes(pdf_bytes,dpi=dpi,first_page=page,last_page=page,output_folder=folder)
            if len(images)!=1:raise RuntimeError('Unexpected Poppler page count')
            img=images[0];filename=getattr(img,'filename',None)
            try:
                if img.width*img.height>MAX_PAGE_PIXELS:raise ValueError('Raster exceeds validated pixel cap')
                box=stripe_crop_box(img)
                if box:
                    cropped=img.crop(box);img.close();img=cropped
                with io.BytesIO() as buffer:
                    img.save(buffer,format='PNG',optimize=True)
                    result.append(base64.b64encode(buffer.getvalue()).decode('ascii'))
                if save_dir:
                    os.makedirs(save_dir,exist_ok=True);img.save(os.path.join(save_dir,f'{save_prefix}_{page:03d}.png'),'PNG')
            finally:
                img.close();images.clear()
                if filename and os.path.exists(filename):os.unlink(filename)
            gc.collect()
    return result


def install(render_module=None):
    """Install only in this worker process; return explicit implementation metadata."""
    if render_module is None:
        from plugins.context_engine.visual import render as render_module
    original=render_module._pdf_bytes_to_image_b64_list
    if getattr(original,'_rq3_bounded_converter',False):return dict(IMPLEMENTATION)
    @functools.wraps(original)
    def convert(pdf_bytes,dpi=72,save_dir=None,save_prefix='page'):
        counts=page_pixels(pdf_bytes,dpi)
        if max(counts)<=LARGE_PAGE_PIXELS:
            return original(pdf_bytes,dpi=dpi,save_dir=save_dir,save_prefix=save_prefix)
        return convert_pdf_bounded(pdf_bytes,dpi=dpi,save_dir=save_dir,save_prefix=save_prefix,_validated_pixels=counts)
    convert._rq3_bounded_converter=True
    render_module._pdf_bytes_to_image_b64_list=convert
    return dict(IMPLEMENTATION)
