#!/usr/bin/env python3
"""Offline image decoding/ledger audit. Never claims semantic losslessness or wire delivery."""
import hashlib,io,json,re,time
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
from PIL import Image
import zstandard
ROOT=Path(__file__).resolve().parents[1]

def inspect_image(path,expected=None):
    data=path.read_bytes();sha=hashlib.sha256(data).hexdigest()
    with Image.open(io.BytesIO(data)) as im:
        im.load();size=list(im.size);fmt=im.format;extrema=im.getextrema()
    ranges=extrema if isinstance(extrema[0],tuple) else [extrema]
    out={'path':str(path),'sha256':sha,'bytes':len(data),'dimensions':size,'format':fmt,'decoded':True,
         'nonuniform_pixels':any(b>a for a,b in ranges)}
    if expected:
        out.update(hash_matches=sha==expected['attachmentId'].split(':')[1],dimensions_match=size==[expected['width'],expected['height']],
                   bytes_match=len(data)==expected['bytes'],original_dimensions=expected.get('originalDimensions'),
                   transformed=bool(expected.get('originalDimensions')))
    return out


def normalize_span(events,seqs):
    ix={e.get('seq'):e for e in events};messages=[];unknown=[]
    for seq in seqs:
        if seq not in ix:raise ValueError('shadowed sequence missing')
        e=ix[seq];m=e['data'].get('message',e['data'])
        if m.get('role')=='system' or m.get('source',{}).get('kind')=='compact-checkpoint':continue
        blocks=[]
        for b in m.get('content',[]):
            if b['type'] in ('text','reasoning'):blocks.append({'type':'text','text':b['text']})
            elif b['type']=='image':blocks.append({'type':'text','text':'[Native image '+b['attachment']['attachmentId']+']'})
            elif b['type'] not in ['tool-call','tool-removal']:unknown.append(b['type'])
        messages.append({'role':m['role'],'content':blocks})
    return messages,unknown


def main():
    root=ROOT/'outputs/campaigns/bc100-r3-all-strategies/jobs';out=ROOT/'outputs/visual-integrity-audit';out.mkdir(exist_ok=True)
    records=[];issues=[];native_count=0;seen=set()
    for job in sorted((root/'dsh/visual').glob('*')):
        for a in sorted((job/'attempts').glob('attempt_*')):
            for rp in a.rglob('metrics/render.jsonl'):
                rendered=[json.loads(l) for l in rp.read_text().splitlines()];native=rp.parents[2]
                if not rendered:continue
                sid=rendered[0]['session_id'];trace=next((native/'dsh-home/sessions').glob('*/'+sid+'/session.v4.jsonl.zstd'))
                try:
                    with trace.open('rb') as stream:events=[json.loads(l) for l in zstandard.ZstdDecompressor().stream_reader(stream).read().splitlines()]
                except (ValueError,zstandard.ZstdError) as e:issues.append({'path':str(trace),'error':'live_or_incomplete_trace','detail':type(e).__name__});continue
                summaries=[e for e in events if e['type']=='compaction/summary'];accumulated=[]
                if len(summaries)!=len(rendered):issues.append({'job':job.name,'kind':'render_summary_count_mismatch','renders':len(rendered),'summaries':len(summaries)})
                for i,(r,s) in enumerate(zip(rendered,summaries)):
                    new,unknown=normalize_span(events,s['data'].get('shadowedSeqs',[]));accumulated.extend(new)
                    chars=sum(len(str(m['content'])) for m in accumulated);ids=r.get('native_image_ids',[]);native_count+=len(ids)
                    attachments=[b['attachment'] for b in s['data']['summary'] if b['type']=='image'];images=[]
                    for attachment in attachments:
                        sha=attachment['attachmentId'].split(':')[1];path=native/'dsh-home/attachments/v1/objects'/sha[:2]/sha
                        try:info=inspect_image(path,attachment);images.append(info);seen.add(str(path))
                        except (OSError,ValueError) as e:images.append({'path':str(path),'decoded':False,'error':str(e)})
                    rec={'harness':'dsh','job':job.name,'attempt':a.name,'compression_index':i+1,'render_log':str(rp),'trace':str(trace),
                         'compaction_id':s['data']['compactionId'],'render_image_count':r['stats']['image_count'],'native_evidence_ids':ids,
                         'attachment_count':len(attachments),'expected_attachment_count':r['stats']['image_count']+len(ids),
                         'page_ledger_complete':len(attachments)==r['stats']['image_count']+len(ids),
                         'render_messages':r['stats']['messages_rendered'],'reconstructed_messages':len(accumulated),
                         'render_text_chars':r['stats']['text_chars'],'reconstructed_text_chars':chars,
                         'exact_span_counter_match':len(accumulated)==r['stats']['messages_rendered'] and chars==r['stats']['text_chars'],
                         'unknown_content_types':sorted(set(unknown)),'images':images}
                    records.append(rec)
    for job in sorted((root/'hermes/visual').glob('*')):
        for a in sorted((job/'attempts').glob('attempt_*')):
            rp=a/'native/metrics/render.jsonl'
            if not rp.exists():continue
            rendered=[json.loads(l) for l in rp.read_text().splitlines()];directory=a/'native/context_images'
            for i,r in enumerate(rendered):
                n=i+1;paths=sorted(p for p in directory.glob('*.png') if re.fullmatch(r'(old|recent)_'+str(n)+r'(?:_\d+)?\.png',p.name));images=[]
                for path in paths:
                    try:images.append(inspect_image(path));seen.add(str(path))
                    except (OSError,ValueError) as e:images.append({'path':str(path),'decoded':False,'error':str(e)})
                records.append({'harness':'hermes','job':job.name,'attempt':a.name,'compression_index':n,'render_log':str(rp),
                     'render_image_count':r['stats']['image_count'],'saved_canvas_count':len(paths),
                     'page_ledger_complete':len(paths)==r['stats']['image_count'],'render_messages':r['stats']['messages_rendered'],
                     'render_text_chars':r['stats']['text_chars'],'exact_span_counter_match':None,
                     'span_validation':'Original persistent history accumulator is not separately saved; image artifacts alone cannot establish full content coverage.',
                     'images':images})
    totals={}
    for h in ['dsh','hermes']:
        rs=[r for r in records if r['harness']==h];ims=[i for r in rs for i in r['images']]
        totals[h]={'jobs':len(set(r['job'] for r in rs)),'compression_events':len(rs),'image_references':len(ims),
         'decode_failures':sum(not i['decoded'] for i in ims),'blank_uniform_images':sum(i.get('nonuniform_pixels') is False for i in ims),
         'page_ledger_mismatches':sum(not r['page_ledger_complete'] for r in rs),
         'expected_hash_checks':sum('hash_matches' in i for i in ims),'metadata_dimension_checks':sum('dimensions_match' in i for i in ims),'hash_mismatches':sum(i.get('hash_matches') is False for i in ims),'dimension_mismatches':sum(i.get('dimensions_match') is False for i in ims),
         'size_mismatches':sum(i.get('bytes_match') is False for i in ims),'transformed_attachments':sum(bool(i.get('transformed')) for i in ims),
         'span_counter_matches':sum(r.get('exact_span_counter_match') is True for r in rs),
         'span_counter_mismatches':sum(r.get('exact_span_counter_match') is False for r in rs),
         'span_counter_unknown':sum(r.get('exact_span_counter_match') is None for r in rs)}
    result={'as_of':datetime.now(timezone.utc).isoformat(),'summary':totals,'native_evidence_occurrences_dsh':native_count,
      'unique_image_files':len(seen),'records':records,'issues':issues,
      'limitations':['Artifact integrity is not semantic losslessness or model legibility.','A complete page ledger checks image count, not whether content within a page was clipped.',
       'DSH transformed JPEG attachments can change size and pixels after original rendering.','Hermes core wire routing is independently invalidated; good PNGs do not prove image delivery.',
       'BC input is text-only; absence of native evidence in DSH means this campaign cannot test preservation of retrieval/crop/zoom images.']}
    (out/'audit.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:result[k] for k in ['as_of','summary','native_evidence_occurrences_dsh','unique_image_files','issues']},indent=2))
if __name__=='__main__':main()
