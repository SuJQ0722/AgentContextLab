#!/usr/bin/env python3
"""Zero-model, zero-upload, uncached hosted-image identity check per cloud node."""
import argparse,hashlib,json,os,socket,time,uuid
from pathlib import Path
from verified_hosted_images_v4 import VerifiedImageHost
from lab import ROOT
FIXTURE=ROOT/'outputs/preflight/visual-hosted-transport-v4/image-check'
FIXTURE_SHA256='1b8d623e02afbe773470cb7632ec324c9716f14d671aa1df5097fd6ac0e6d2fe'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def check(root,fixture=FIXTURE):
 fixture=Path(fixture)
 if sha((fixture/'manifest.json').read_bytes())!=FIXTURE_SHA256:raise ValueError('Fixture manifest binding changed')
 manifest=json.loads((fixture/'manifest.json').read_text())
 source=fixture/manifest['source_file'];receipt=fixture/manifest['receipt_file']
 if source.parent!=fixture or receipt.parent!=fixture:raise ValueError('Fixture path must remain within fixture directory')
 raw=source.read_bytes();saved=receipt.read_bytes()
 if sha(raw)!=manifest['source_sha256']or sha(saved)!=manifest['receipt_sha256']:raise ValueError('Fixture hash mismatch')
 record=json.loads(saved)
 if record.get('source_sha256')!=sha(raw)or not record.get('url'):raise ValueError('Existing receipt required; upload prohibited')
 cache=Path(root)/'runtime/image-preflight'/socket.gethostname()/uuid.uuid4().hex
 (cache/'sources').mkdir(parents=True);(cache/'hosted').mkdir()
 (cache/'hosted'/(sha(raw)+'.upload.json')).write_bytes(saved)
 result={'version':'hosted-image-preflight-v4','at':time.time(),'hostname':socket.gethostname(),'fixture_sha256':sha((fixture/'manifest.json').read_bytes()),'source_sha256':sha(raw),'model_calls':0,'upload_calls':0,'cache':str(cache),'passed':False}
 try:
  from unittest.mock import patch
  import requests
  with patch.object(requests.sessions.Session,'request',side_effect=RuntimeError('Upload prohibited in image preflight')):
   value=VerifiedImageHost(cache,dict(os.environ)).ensure(raw)
  result.update(passed=value['byte_identical']is True and value['pixel_identical']is True,byte_identical=value['byte_identical'],pixel_identical=value['pixel_identical'],verification_attempts=value['verification_attempts'],verification_route=value['verification_route'])
 except Exception as exc:
  result['error_type']=type(exc).__name__
 finally:
  (cache/'preflight.json').write_text(json.dumps(result,indent=2)+'\n')
 if not result['passed']:raise RuntimeError('Hosted image network readiness failed; no dispatch permitted')
 return result

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);a=p.parse_args();print(json.dumps(check(a.root)))
if __name__=='__main__':main()
