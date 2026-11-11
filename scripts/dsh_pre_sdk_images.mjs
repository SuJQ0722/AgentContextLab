/** Apply the already approved last-ten policy before native image preparation.
 * Request-local projection only: journal/history and retained pixels stay intact.
 */
export function projectLastTenImages(messages){
 const occurrences=[];
 for(const [mi,message] of messages.entries())for(const [pi,part] of (message.content??[]).entries()){
  if(part.type==='image')occurrences.push({mi,pi,part});
 }
 const removed=occurrences.slice(0,Math.max(0,occurrences.length-10)),retained=occurrences.slice(-10);
 for(const {part} of retained){
  if(part.offloaded||!part.attachment?.attachmentId)throw Error('Retained visual evidence unavailable before SDK dispatch');
 }
 const drop=new Set(removed.map(x=>`${x.mi}:${x.pi}`));
 return {messages:removed.length?messages.map((message,mi)=>({...message,content:message.content?.filter((part,pi)=>!drop.has(`${mi}:${pi}`))})):messages,
  audit:{version:'dsh-pre-sdk-last-ten-v1',original_image_count:occurrences.length,retained_image_count:retained.length,
   removed:removed.map(({mi,pi,part})=>({message_index:mi,part_index:pi,attachment_id:part.attachment?.attachmentId??null})),
   history_mutated:false,pixels_reencoded:false}};
}
