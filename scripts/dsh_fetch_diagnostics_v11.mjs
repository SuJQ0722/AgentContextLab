/** Metadata-only outer fetch diagnostics; never log URL, body, headers or error messages. */
import {appendFileSync} from 'node:fs';
export function diagnoseFetch(original, endpoint, emit, now=Date.now) {
 return async function(input, init) {
  const url=typeof input==='string'?input:input instanceof URL?input.href:input.url;
  if(url!==endpoint)return original.call(this,input,init);
  const started=now();emit({event:'outer_model_fetch_enter'});
  try{return await original.call(this,input,init);}
  catch(error){
   const codes=[];let current=error;
   for(let i=0;current&&i<5;i++,current=current.cause){if(typeof current.code==='string'&&/^[A-Z0-9_]{1,64}$/.test(current.code))codes.push(current.code);}
   const message=typeof error?.message==='string'?error.message:'';
   const category=message.startsWith('Inline preparation ')?'inline_preparation_failure':message==='Inline request exceeds 32MiB'?'total_body_limit':message==='Uninspectable body'?'unsupported_body_type':'unclassified_fetch_failure';
   emit({event:'outer_model_fetch_error',error_type:/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(error?.name||'')?error.name:'Error',cause_codes:[...new Set(codes)],error_category:category,client_seconds:(now()-started)/1000,provider_acceptance_unknown:true});
   throw error;
  }
 };
}
const ledger=process.env.ACL_INLINE_DSH_LEDGER;
if(ledger){
 const emit=row=>appendFileSync(ledger+'.outer-v11.jsonl',JSON.stringify({version:'dsh-outer-fetch-diagnostics-v11',at_unix:Date.now()/1000,...row})+'\n');
 emit({event:'diagnostics_installed',body_and_headers_logged:false});
 globalThis.fetch=diagnoseFetch(globalThis.fetch,process.env.TOKENHUB_BASE_URL.replace(/\/$/,'')+'/chat/completions',emit);
}
