import assert from 'node:assert/strict';
import {guardedFetch,ROUTES} from '../scripts/dsh_wire_v24.mjs';
const endpoint='http://127.0.0.1/chat/completions';
for (const succeed of [false,true]) {
 let sends=0,term=0;const rows=[];
 const f=guardedFetch({original:async()=>{sends++;return new Response(succeed&&sends===3?'{}':'error',{status:succeed&&sends===3?200:503});}, transform:async body=>({wire:body,ledger:{}}),endpoint,emit:r=>rows.push(r),terminate:()=>{term++;throw Error('STOP');},sleep:async()=>{throw Error('No cycle wait allowed');}});
 let success=false;try {const r=await f(endpoint,{method:'POST',body:JSON.stringify({model:ROUTES[0],messages:[]})});success=r.ok;}catch(e){assert.equal(e.message,'STOP');}
 assert.equal(sends,3);assert.equal(success,succeed);assert.equal(term,succeed?0:1);
}
console.log('PASS: DSH hard limit 3 sends; success on third accepted; no retry backoff loop.');
