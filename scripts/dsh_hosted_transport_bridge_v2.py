"""Persistent worker-local JSON-lines bridge; credentials never enter stdout."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import sys
from hermes_bounded_rq3_worker_v1 import registered_pages
from verified_canvas_registry_cache import VerifiedCanvasRegistryCache
from verified_hosted_images_v4 import transform, VerifiedImageHost

def main():
    p=argparse.ArgumentParser();p.add_argument('--canvas-root',type=Path,required=True);p.add_argument('--cache-root',type=Path,required=True)
    a=p.parse_args();output=sys.stdout
    registry=VerifiedCanvasRegistryCache(a.canvas_root,lambda root:registered_pages(root,.75))
    host=VerifiedImageHost(a.cache_root,os.environ)
    for line in sys.stdin:
        try:
            request=json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                wire,ledger=transform(request['body'].encode(),rendered_registry=registry,host=host)
            result={'id':request['id'],'ok':True,'wire':wire.decode(),'ledger':ledger}
        except Exception as error:
            result={'id':locals().get('request',{}).get('id'),'ok':False,'error_type':type(error).__name__}
        output.write(json.dumps(result,separators=(',',':'))+'\n');output.flush()

if __name__=='__main__':main()
