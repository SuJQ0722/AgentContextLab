/** Independent routes1 transport boundary; no image bytes, order or detail edits. */
import {readFileSync,appendFileSync,mkdirSync} from 'node:fs';
import {dirname,join} from 'node:path';
export class RouteBindingError extends Error{constructor(reason){super(reason);this.name='RouteBindingError';this.network_request_sent=false;}}
export function guardedFetch(original,{actualRoute,baseUrl,ledgerPath}){
 const endpoint=baseUrl.replace(/\/$/,'')+'/chat/completions';
 return async function(input,init){
  const url=new URL(typeof input==='string'||input instanceof URL?input:input.url);
  const inference=/(?:\/chat\/completions|\/responses|\/messages|\/completions|\/generate|\/chat)$/.test(url.pathname.replace(/\/$/,''));
  if(!inference)return original.call(this,input,init);
  const method=(init?.method??(input instanceof Request?input.method:'GET')).toUpperCase();
  let raw=init?.body;if(raw===undefined&&input instanceof Request)raw=await input.clone().text();
  let body;try{body=JSON.parse(typeof raw==='string'?raw:Buffer.isBuffer(raw)?raw.toString():'');}catch{}
  const reason=url.toString().replace(/\/$/,'')!==endpoint?'inference_endpoint_mismatch':
    method!=='POST'?'inference_method_mismatch':body?.model!==actualRoute?'inference_model_mismatch':null;
  if(ledgerPath){mkdirSync(dirname(ledgerPath),{recursive:true});appendFileSync(ledgerPath,JSON.stringify({
   version:'routes1-request-binding-v1',timestamp:new Date().toISOString(),actual_route:actualRoute,
   request_path:url.pathname,route_verified:!reason,network_request_sent:!reason,guard_error:reason})+'\n',{mode:0o600});}
  if(reason)throw new RouteBindingError(reason);
  return original.call(this,input,init);
 };
}
if(process.env.ACL_ROUTE_LINEAGE_FILE){
 const lineage=JSON.parse(readFileSync(process.env.ACL_ROUTE_LINEAGE_FILE,'utf8'));
 if(typeof lineage.actual_route!=='string'||!process.env.TOKENHUB_BASE_URL)throw new RouteBindingError('missing_route_binding');
 globalThis.fetch=guardedFetch(globalThis.fetch,{actualRoute:lineage.actual_route,baseUrl:process.env.TOKENHUB_BASE_URL,
  ledgerPath:process.env.ACL_IMAGE_WIRE_AUDIT_DIR?join(process.env.ACL_IMAGE_WIRE_AUDIT_DIR,'route-guard.jsonl'):null});
}
