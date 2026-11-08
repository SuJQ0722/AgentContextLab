"""Routes1 metadata sidecar; native calls.jsonl remains the sole usage authority."""
import hashlib
import json
import os
from pathlib import Path


def load_route_lineage(actual_route,config_path,spec_path=None):
    path=os.environ.get('ACL_ROUTE_LINEAGE_FILE')
    if not path:raise ValueError('Routes1 requires immutable route lineage')
    lineage=json.loads(Path(path).read_text())
    if lineage.get('actual_route')!=actual_route:raise ValueError('Runtime model disagrees with route lineage')
    checks=[('runtime_config',Path(config_path))]
    if spec_path is not None:checks.append(('runtime_spec',Path(spec_path)))
    for key,file in checks:
        if (Path(lineage.get(key+'_path','/missing')).resolve()!=file.resolve()
                or hashlib.sha256(file.read_bytes()).hexdigest()!=lineage.get(key+'_sha256')):
            raise ValueError('Routes1 runtime file identity mismatch: '+key)
    for file,expected in lineage.get('implementation_sha256',{}).items():
        # Route sources are relative to the orchestration root, never the task cwd.
        location=Path(__file__).resolve().parents[1]/file
        if hashlib.sha256(location.read_bytes()).hexdigest()!=expected:
            raise ValueError('Routes1 implementation changed before native dispatch')
    return lineage


def _presence(raw,paths):
    values=[]
    for path in paths:
        node=raw
        for part in path.split('.'):
            if not isinstance(node,dict) or part not in node:break
            node=node[part]
        else:values.append(node)
    known=bool(values) and all(isinstance(v,int) and not isinstance(v,bool) and v>=0 for v in values) and len(set(values))==1
    return bool(values),known


class RouteAttributionMixin:
    """Preserves inherited archive/write/install/guards. Sidecar is joined, not summed."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        path=os.environ.get('ACL_ROUTE_LINEAGE_FILE')
        self._route_lineage=json.loads(Path(path).read_text()) if path else {}
        self._route_calls={}

    def _emit_route(self,cid):
        state=self._route_calls[cid];call=state.get('call')
        if call is None:return
        models=sorted(state.get('models',set()));returned=models[0] if len(models)==1 else None
        raw=call.get('raw_provider_usage')
        present,known=_presence(raw,['prompt_tokens_details.cached_tokens','input_tokens_details.cached_tokens','prompt_cache_hit_tokens','cached_tokens'])
        logical=self._route_lineage.get('logical_model');route=state.get('actual_route') or call.get('model')
        state['revision']=state.get('revision',0)+1
        record={'version':'routes1-returned-model-v1','event':'final','call_id':cid,'revision':state['revision'],
            'actual_route':route,'assigned_route':self._route_lineage.get('actual_route'),'logical_model':logical,
            'returned_model':returned,'returned_models':models,'returned_model_presence':state.get('model_present',False),
            'returned_model_conflict':len(models)>1,'route_matches_assignment':route==self._route_lineage.get('actual_route'),
            'returned_model_exactly_matches_request_alias':None if returned is None or route is None else returned==route,
            'preflight_returned_model_observation':'deepseek-v4-1-flash-261017',
            'returned_model_matches_preflight_observation':None if returned is None else returned=='deepseek-v4-1-flash-261017',
            'backend_weights_equivalence_verified':None,
            'route_plan_sha256':self._route_lineage.get('route_plan_sha256'),'parent_plan_sha256':self._route_lineage.get('parent_plan_sha256'),
            'generation':self._route_lineage.get('runtime_route_version','routes1'),
            'purpose':call.get('purpose','unknown'),'started_at':call.get('started_at'),'ended_at':call.get('ended_at'),
            'cached_input_presence':present,'cache_value_known':known,
            'provider_prompt_known':_presence(raw,['prompt_tokens','input_tokens'])[1],
            'output_known':_presence(raw,['completion_tokens','output_tokens'])[1],
            'client_stream_seconds':call.get('client_stream_seconds'),'provider_internal_latency_seconds':None,
            'error_type':call.get('error_type'),'usage_authority':False,'usage_source':str(self.out/'calls.jsonl'),
            'usage_join_key':'call_id','revision_note':'Last revision per call_id supplies attribution only; never sum sidecar revisions or tokens.'}
        super().write('route-attribution.jsonl',record)

    def write(self,name,record):
        super().write(name,record)
        if name=='calls.jsonl' and record.get('call_id'):
            cid=record['call_id'];state=self._route_calls.setdefault(cid,{})
            state['call']=dict(record);self._emit_route(cid)

    def archive(self,record):
        super().archive(record)
        cid=record.get('call_id')
        if not cid:return
        state=self._route_calls.setdefault(cid,{})
        if record.get('type')=='request':state['actual_route']=record.get('model')
        value=record.get('response') if record.get('type')=='response' else record.get('chunk') if record.get('type')=='stream_chunk' else None
        if isinstance(value,dict) and 'model' in value:
            state['model_present']=True;model=value['model']
            if isinstance(model,str) and len(model)<=512 and '\n' not in model and '\r' not in model:
                models=state.setdefault('models',set());changed=model not in models;models.add(model)
                if changed and state.get('call') is not None:self._emit_route(cid)
