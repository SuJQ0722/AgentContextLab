#!/usr/bin/env python3
"""Versioned native-vision route fix; frozen Hermes/BC workers remain untouched.

Records engine image pixels and checks actual SDK-bound messages after Hermes's
own routing. Never inserts images into the final SDK request to pass the audit.
"""
import base64,collections,hashlib,io,json,os,sys,time
from pathlib import Path
from lab import ROOT
import hermes_bc_worker as frozen

class VisionRouteError(BaseException):pass

def ledger(messages):
    from PIL import Image
    result=[]
    for mi,message in enumerate(messages or []):
        for pi,part in enumerate(message.get('content',[]) if isinstance(message.get('content'),list) else []):
            if not isinstance(part,dict) or part.get('type')!='image_url':continue
            obj=part['image_url'];obj={'url':obj} if isinstance(obj,str) else obj;url=obj.get('url','')
            if not url.startswith('data:image/'):raise VisionRouteError('Unfrozen non-inline image cannot be audited')
            raw=base64.b64decode(url.split(',',1)[1],validate=True)
            with Image.open(io.BytesIO(raw)) as im:
                pixel=hashlib.sha256(im.mode.encode()+str(im.size).encode()+im.tobytes()).hexdigest();size=list(im.size);mode=im.mode
            result.append({'message':mi,'part':pi,'payload_sha256':hashlib.sha256(raw).hexdigest(),
                'pixel_sha256':pixel,'dimensions':size,'mode':mode,'detail':obj.get('detail','auto'),'bytes':len(raw)})
    return result

def identity(item):return (item['pixel_sha256'],item['detail'])

class VisionRecorder(frozen.Recorder):
    def __init__(self,out):
        super().__init__(out);self.expected=[];self.compressions=0;self.post_image_calls=0;self.wire_model_calls=0
    def install(self):
        super().install()
        from openai.resources.chat.completions import Completions,AsyncCompletions
        from agent import auxiliary_client
        original=Completions.create
        spec=json.loads(Path(sys.argv[sys.argv.index('--spec')+1]).read_text());model=spec['model']
        def blocked(*args,**kwargs):
            self.invalid=True;self.write('vision-route.jsonl',{'event':'blocked_auxiliary','reason':'caption/auxiliary inference forbidden'})
            raise VisionRouteError('Auxiliary/caption inference forbidden')
        async def async_blocked(*args,**kwargs):return blocked()
        auxiliary_client.async_call_llm=async_blocked
        auxiliary_client.call_llm=blocked
        AsyncCompletions.create=async_blocked
        def observed(client,*args,**kwargs):
            if kwargs.get('model')!=model:blocked()
            if spec.get('probe_require_compression') and not self.expected:raise VisionRouteError('Probe must compress before any model request')
            if spec.get('probe_max_calls') and self.post_image_calls>=spec['probe_max_calls']:raise VisionRouteError('Bounded probe call cap reached')
            actual=ledger(kwargs.get('messages'))
            required=collections.Counter(identity(x) for x in self.expected)
            present=collections.Counter(identity(x) for x in actual)
            missing=required-present
            record={'event':'actual_sdk_request','model':kwargs.get('model'),'compression_count':self.compressions,
                'images':actual,'expected_images':len(self.expected),'missing_count':sum(missing.values()),
                'matching_rendered_pixels':bool(self.expected and not missing),'request_unchanged_by_audit':True}
            self.write('vision-route.jsonl',record)
            if missing:
                self.invalid=True;raise VisionRouteError('Hermes routed away or altered rendered image pixels before SDK call')
            if self.expected:self.post_image_calls+=1
            return original(client,*args,**kwargs)
        Completions.create=observed
        import httpx
        send=httpx.Client.send
        def wire(client,request,*args,**kwargs):
            path=request.url.path
            if path.endswith('/responses'):
                blocked()
            if path.endswith('/chat/completions'):
                if spec.get('probe_max_calls') and self.wire_model_calls>=spec['probe_max_calls']:raise VisionRouteError('HTTP probe cap reached')
                self.wire_model_calls+=1
                body=json.loads(request.content);actual=ledger(body.get('messages'))
                missing=collections.Counter(identity(x) for x in self.expected)-collections.Counter(identity(x) for x in actual)
                self.write('vision-wire.jsonl',{'event':'final_http_payload','model':body.get('model'),
                    'compression_count':self.compressions,'images':actual,'expected_images':len(self.expected),
                    'missing_count':sum(missing.values()),'matching_rendered_pixels':bool(self.expected and not missing)})
                if body.get('model')!=model or missing:
                    self.invalid=True;raise VisionRouteError('Final HTTP model/image ledger mismatch')
            return send(client,request,*args,**kwargs)
        httpx.Client.send=wire
    def instrument_engine(self,engine):
        super().instrument_engine(engine);original=engine.compress
        def compress(*args,**kwargs):
            before=engine.compression_count;result=original(*args,**kwargs)
            if engine.compression_count>before:
                expected=ledger(result)
                if not expected:self.invalid=True;raise VisionRouteError('Visual compression produced no auditable images')
                self.expected=expected;self.compressions=engine.compression_count
                self.archive({'type':'compression_source_history','compression_count':self.compressions,'messages':getattr(engine,'_full_history',[])})
                self.write('vision-route.jsonl',{'event':'engine_compressed_messages','compression_count':self.compressions,
                    'images':expected,'source':'actual native engine.compress return, before normal Hermes routing'})
                directory=Path(engine._save_dir) if getattr(engine,'_save_dir',None) else None
                sources=[]
                if directory and directory.exists():
                    from PIL import Image
                    for path in directory.glob('*.png'):
                        try:
                            with Image.open(path) as im:
                                pixel=hashlib.sha256(im.mode.encode()+str(im.size).encode()+im.tobytes()).hexdigest()
                            if pixel in {x['pixel_sha256'] for x in expected}:sources.append({'path':str(path),'pixel_sha256':pixel})
                        except (OSError,ValueError):continue
                self.write('vision-render-sources.jsonl',{'compression_count':self.compressions,'matching_png_sources':sources})
            return result
        engine.compress=compress
        spec=json.loads(Path(sys.argv[sys.argv.index('--spec')+1]).read_text())
        if spec.get('probe_history_path'):
            from run_agent import AIAgent
            original_run=AIAgent.run_conversation
            def with_history(agent,*a,**kw):
                history=json.loads(Path(spec['probe_history_path']).read_text())
                compressed=agent.context_compressor.compress(history,current_tokens=spec.get('probe_source_prompt_tokens',0))
                if spec.get('probe_canvas_only'):
                    compressed=[m for m in compressed if isinstance(m.get('content'),list) and any(p.get('type')=='image_url' for p in m['content'] if isinstance(p,dict))]
                kw['conversation_history']=compressed
                return original_run(agent,*a,**kw)
            AIAgent.run_conversation=with_history


def main():
    # Alter only this new worker's config creation, before normal agent loading.
    original_dump=frozen.yaml.safe_dump
    def native_config(data,*args,**kwargs):
        if isinstance(data,dict) and 'model' in data and 'compression' in data:
            data['model']['supports_vision']=True
            data.setdefault('agent',{})['image_input_mode']='native'
            data['auxiliary']={'vision':{'provider':'custom','model':data['model']['default'],'base_url':data['model']['base_url']}}
        return original_dump(data,*args,**kwargs)
    frozen.yaml.safe_dump=native_config;frozen.Recorder=VisionRecorder
    if '--rq3-pdf' in sys.argv:
        sys.argv.remove('--rq3-pdf');sys.path.insert(0,str(ROOT/'hermes-agent'))
        from rq3_pdf_renderer import install
        metadata=install()
        out=Path(sys.argv[sys.argv.index('--out')+1]);out.mkdir(parents=True,exist_ok=True)
        (out/'rq3-native-vision-adapter.json').write_text(json.dumps(metadata,indent=2))
    frozen.main()

if __name__=='__main__':main()
