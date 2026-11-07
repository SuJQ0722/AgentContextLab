#!/usr/bin/env python3
"""Archive raw renderer images before native attachment normalization; no render changes."""
import base64,hashlib,io,json,os,sys,time
from pathlib import Path
from PIL import Image
from render_dsh_history import render

def main():
 payload=json.load(sys.stdin);out=Path(os.environ['ACL_RAW_CANVAS_AUDIT_DIR'])/str(time.time_ns());out.mkdir(parents=True)
 (out/'input.json').write_text(json.dumps(payload,ensure_ascii=False))
 result=render(payload);rows=[]
 for i,url in enumerate(result['images']):
  raw=base64.b64decode(url.split(',',1)[1]);p=out/f'canvas-{i+1}.png';p.write_bytes(raw)
  with Image.open(io.BytesIO(raw)) as im:width,height=im.size
  rows.append({'index':i,'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'width':width,'height':height})
 (out/'manifest.json').write_text(json.dumps({'renderer':'unchanged render_dsh_history.render','images':rows,'stats':result.get('stats')},indent=2))
 print(json.dumps(result))
if __name__=='__main__':main()
