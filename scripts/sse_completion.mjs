/** Incremental SSE framing, including arbitrary chunk and CRLF boundaries. */
export class SSECompletion {
 constructor(){this.pending=Buffer.alloc(0);this.skipLF=false;this.data=[];this.sawSSE=false;this.done=false;this.consumed=0;this.doneOffset=null;}
 feed(chunk){
  if(this.done)return;
  if(this.skipLF&&chunk.length){this.skipLF=false;if(chunk[0]===10){chunk=chunk.subarray(1);this.consumed++;}}
  this.pending=Buffer.concat([this.pending,chunk]);let offset=0;
  while(offset<this.pending.length){
   const lf=this.pending.indexOf(10,offset),cr=this.pending.indexOf(13,offset);
   const positions=[lf,cr].filter(x=>x>=0);if(!positions.length)break;
   const end=Math.min(...positions);
   if(this.pending[end]===13&&end+1===this.pending.length)this.skipLF=true;
   const width=this.pending[end]===13&&this.pending[end+1]===10?2:1;
   const line=this.pending.subarray(offset,end);offset=end+width;
   if(!line.length){
    if(this.data.join('\n')==='[DONE]'){this.done=true;this.doneOffset=this.consumed+offset;break;}
    this.data=[];
   }else if(line[0]===58){this.sawSSE=true;}
   else{
    const colon=line.indexOf(58),field=line.subarray(0,colon<0?line.length:colon).toString('ascii');
    let value=colon<0?Buffer.alloc(0):line.subarray(colon+1);if(value[0]===32)value=value.subarray(1);
    if(['data','event','id','retry'].includes(field))this.sawSSE=true;
    // DONE is ASCII: do not decode potentially split UTF-8 response text here.
    if(field==='data')this.data.push(value.equals(Buffer.from('[DONE]'))?'[DONE]':'<non-terminal>');
   }
  }
  this.consumed+=offset;this.pending=this.pending.subarray(offset);
 }
}
