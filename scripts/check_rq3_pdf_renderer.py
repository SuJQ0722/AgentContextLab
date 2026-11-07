#!/usr/bin/env python3
"""No-API check: original and bounded converters produce equal PNG pixels."""
import base64,io,json,subprocess,sys,time
from pathlib import Path
from lab import ROOT,environment,python_for

def main():
    if '--worker' not in sys.argv:
        env,_=environment(ROOT,'hermes');raise SystemExit(subprocess.call([python_for(ROOT),__file__,'--worker'],env=env))
    sys.path.insert(0,str(ROOT/'hermes-agent'))
    from plugins.context_engine.visual import render
    from rq3_pdf_renderer import convert_pdf_bounded,install,IMPLEMENTATION
    from reportlab.pdfgen.canvas import Canvas
    from PIL import Image
    import numpy as np
    out=ROOT/'outputs/preflight'/f'rq3-pixel-equivalence-{time.time_ns()}';out.mkdir(parents=True)
    buffer=io.BytesIO();canvas=Canvas(buffer,pagesize=(250,400))
    for page in range(2):
        canvas.setFillColorRGB(1,1,1);canvas.rect(0,0,250,400,fill=1,stroke=0)
        canvas.setFillColorRGB(0,0,0);canvas.drawString(12,350-page*17,'Cedar XR-123 exact quantity 5.5')
        canvas.setFillColorRGB(.3,.4,.5);canvas.rect(20,150,111,63,fill=1,stroke=0);canvas.showPage()
    canvas.save();pdf=buffer.getvalue()
    original=render._pdf_bytes_to_image_b64_list(pdf,save_dir=str(out/'original'))
    bounded=convert_pdf_bounded(pdf,save_dir=str(out/'bounded'))
    assert len(original)==len(bounded)==2
    for a,b in zip(original,bounded):
        with Image.open(io.BytesIO(base64.b64decode(a))) as ia,Image.open(io.BytesIO(base64.b64decode(b))) as ib:
            assert ia.size==ib.size and ia.mode==ib.mode and np.array_equal(np.asarray(ia),np.asarray(ib))
    install(render);assert render._pdf_bytes_to_image_b64_list(pdf)==original
    result={'passed':True,'paid_calls':0,'page_count':2,'pixels_equal':True,'base64_png_bytes_equal':original==bounded,
            'normal_path_unchanged':True,'implementation':IMPLEMENTATION}
    (out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps({'passed':True,'paid_calls':0,'result':str(out/'result.json')}))
if __name__=='__main__':main()
