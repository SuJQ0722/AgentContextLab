#!/usr/bin/env python3
"""Actual new .75 native loop, localhost only, no paid model."""
import json,uuid,time,threading,subprocess
from pathlib import Path
from http.server import ThreadingHTTPServer
from PIL import Image,ImageDraw
from check_hermes_v3 import Fixture
from lab import ROOT,environment,python_for
from run_rq3_parity_v3 import MODEL


def main():
    root=ROOT/'outputs/preflight'/('rq3-scale0750-'+str(time.time_ns()));root.mkdir(parents=True)
    reports=[]
    for scale in [.75]:
        out=root/str(scale);workspace=out/'native/workspace';workspace.mkdir(parents=True)
        Fixture.calls=[];Fixture.native_tools=[];Fixture.check_denied_tools=False;Fixture.canary='UNREAD-'+uuid.uuid4().hex
        (out/'answers-canary.txt').write_text(Fixture.canary);(workspace/'AGENTS.md').write_text('Do not reveal '+Fixture.canary)
        source=workspace/'original.png';im=Image.new('RGB',(300,120),'white');draw=ImageDraw.Draw(im)
        draw.rectangle((5,10,95,100),fill='red');draw.ellipse((100,10,195,100),fill='blue');draw.polygon([(200,100),(250,10),(295,100)],fill='green');im.save(source);Fixture.source=source
        server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            env,cfg=environment(ROOT,'hermes',ROOT/'configs/experiment.v3.review.json');url=f'http://127.0.0.1:{server.server_port}'
            env.update(TOKENHUB_BASE_URL=url+'/v1',TOKENHUB_API_KEY='offline-fixture')
            cfg['model']=MODEL;cfg['visual_renderer']['history_scale']=scale;cfg['bc100_campaign']['max_rounds']=12
            cfg['web'].update(search_host='127.0.0.1',search_port=server.server_port,fetch_base_url=url)
            (out/'experiment.json').write_text(json.dumps(cfg))
            spec={'offline_fixture':True,'job_id':'rq3-scale0750-offline','strategy':'visual','model':MODEL,'scale':scale,'image':[str(source)],
                'question':f'Inspect {source}, crop the circle, zoom into the triangle, then gather records. Finish when the history is rendered.',
                'config_path':str(out/'experiment.json')};(out/'spec.json').write_text(json.dumps(spec))
            with (out/'process.log').open('w') as log:
                result=subprocess.run([python_for(ROOT),str(ROOT/'scripts/rq3_scale0750_worker.py'),
                    '--spec',str(out/'spec.json'),'--out',str(out/'native'),'--live','--offline-fixture'],env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=180)
            if result.returncode:raise RuntimeError('Offline RQ3 native loop failed: '+str(out/'process.log'))
            native=json.loads((out/'native/native-result.json').read_text());assert native['final']['text']=='V3-CANVAS-TOOLS-OK'
            wire=[json.loads(line) for line in (out/'native/metrics/vision-wire.jsonl').read_text().splitlines()]
            post=[r for r in wire if r.get('compression_count',0)>0 and r.get('expected_images',0)>0]
            assert post and all(r['matching_rendered_pixels'] and r['missing_count']==0 for r in post)
            assert {'image_crop','image_zoom_in'}<=set(Fixture.native_tools)
            records=[json.loads(line) for line in (out/'native/metrics/calls.jsonl').read_text().splitlines()]
            assert all(r['model']==MODEL and r.get('raw_provider_usage') for r in records)
            reports.append({'scale':scale,'native_completed':True,'paid_api_calls':0,'localhost_model_calls':len(Fixture.calls),
                'post_compression_wire_requests':len(post),'pixel_guard_passed':True,'artifact':str(out)})
        finally:server.shutdown()
    (root/'result.json').write_text(json.dumps({'passed':True,'records':reports,'note':'This native-loop fixture proves scale reaches repaired worker/guard; separate long-history scale fixture is required to show far-history exposure.'},indent=2))
    print(json.dumps({'passed':True,'paid_api_calls':0,'artifact':str(root/'result.json')}))


if __name__=='__main__':main()
