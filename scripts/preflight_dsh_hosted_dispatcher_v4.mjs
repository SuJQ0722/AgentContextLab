/** Zero-credential gateway preflight with the actual CLI proxy dispatcher. */
import {installProxyFromEnvironment} from '../deepseekHarness/packages/util/http-proxy/lib/index.js';
import {guardedFetch,safeError,ROUTES} from './dsh_hosted_wire_v4.mjs';
const base=process.env.TOKENHUB_BASE_URL;
if(!base)throw Error('TOKENHUB_BASE_URL required');
const dispose=await installProxyFromEnvironment(new Map(Object.entries(process.env).map(([key,value])=>[key,{value}])),()=>{});
const endpoint=base.replace(/\/$/,'')+'/chat/completions';
const rows=[];
try{
 const transport=guardedFetch({original:globalThis.fetch,endpoint,emit:row=>rows.push(row),
  transform:async body=>({wire:body,ledger:{image_count:0,preflight:true}}),timeoutMs:15000,unauthenticatedPreflight:true,
  terminate:()=>{throw Error('Preflight terminal failure');}});
 // No Authorization or API key header is supplied. The gateway must reject the
 // unauthenticated request before invoking a model; success is never accepted.
 const response=await transport(endpoint,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({model:ROUTES[0],preflight:'零模型'})});
 await response.text();
 const passed=response.status===401||response.status===403;
 console.log(JSON.stringify({passed,http_status:response.status,authorization_sent:false,model_calls:0,
  dispatcher:'actual_dsh_cli_proxy_installation',content_length_policy:'native_fetch_streams_without_manual_content_length',
  events:rows.map(row=>({event:row.event,...(row.cause_codes?{cause_codes:row.cause_codes}: {})}))}));
 if(!passed)process.exitCode=1;
}catch(error){
 console.log(JSON.stringify({passed:false,authorization_sent:false,model_calls:0,...safeError(error)}));
 process.exitCode=1;
}finally{await dispose();}
