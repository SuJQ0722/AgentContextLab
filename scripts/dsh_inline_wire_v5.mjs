/** One-hour worker binding for the audited four-route inline transport. */
import {appendFileSync,mkdirSync} from 'node:fs';
import {dirname} from 'node:path';
const ledger=process.env.ACL_INLINE_DSH_LEDGER;
delete process.env.ACL_INLINE_DSH_LEDGER;
let runtime;
try{runtime=await import('./dsh_hosted_wire_v4.mjs');}
finally{if(ledger!==undefined)process.env.ACL_INLINE_DSH_LEDGER=ledger;}
export const ROUTES=runtime.ROUTES;
export const guardedFetch=options=>runtime.guardedFetch({deadlineMs:3600000,...options});
if(ledger){
 const seconds=Number(process.env.ACL_INLINE_DSH_TIMEOUT_SECONDS);
 if(seconds!==3600)throw Error('Explicit 3600-second DSH attempt deadline required');
 mkdirSync(dirname(ledger),{recursive:true});
 const emit=row=>appendFileSync(ledger,JSON.stringify({version:'dsh-inline-wire-one-hour-v3',at_unix:Date.now()/1000,latency_kind:'client_transport_not_provider',...row})+'\n');
 const endpoint=process.env.TOKENHUB_BASE_URL.replace(/\/$/,'')+'/chat/completions';
 globalThis.fetch=guardedFetch({original:globalThis.fetch,transform:runtime.pythonBridge(process.env.ACL_BOUNDED_PYTHON,process.env.ACL_BOUNDED_CANVAS_ROOT),endpoint,emit,workerKey:process.env.ACL_INLINE_DSH_JOB_ID});
}
