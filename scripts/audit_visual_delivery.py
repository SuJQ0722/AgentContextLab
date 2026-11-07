#!/usr/bin/env python3
"""Read archived SDK requests; classify routing without changing original results."""
import gzip,json,collections
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]

def read(path):
    if not path.exists():return []
    lines=path.read_text().splitlines();result=[]
    for i,l in enumerate(lines):
        try:result.append(json.loads(l))
        except ValueError:
            if i!=len(lines)-1:raise
    return result

def stamp(value):return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()

def inspect(a,campaign):
    metrics=a/'native/metrics';comp=read(metrics/'compression.jsonl');render=read(metrics/'render.jsonl');result_path=a/'result.json'
    result=json.loads(result_path.read_text()) if result_path.exists() else {}
    rec={'campaign':campaign,'attempt':str(a),'original_status':result.get('status','running_or_unknown'),
      'compression_events':len(comp),'render_events':len(render),'post_sdk_requests':0,'requests_with_image_parts':0,
      'requests_zero_image_parts':0,'requests_zero_image_with_caption_error':0,'requests_zero_image_with_caption_replacement':0,
      'requests_with_images_and_caption_error':0,'unmatched_request_call_ids':0,'examples':[]}
    if not comp and not render:rec['classification']='no_logged_render_or_compression';return rec
    times=[stamp(r['timestamp']) for r in (comp or render) if r.get('timestamp')]
    if not times:rec['classification']='event_time_unknown';return rec
    first=min(times);rec['first_event_unix']=first
    starts={r['call_id']:r for r in read(metrics/'call-starts.jsonl')}
    for r in read(metrics/'calls.jsonl'):starts.setdefault(r['call_id'],r)
    path=metrics/'requests-responses.jsonl.gz';rec['request_archive']=str(path)
    if not path.exists():rec['classification']='request_archive_missing';return rec
    try:
        with gzip.open(path,'rt') as f:
            for line in f:
                if '"type": "request"' not in line and '"type":"request"' not in line:continue
                r=json.loads(line)
                if r.get('type')!='request':continue
                start=starts.get(r.get('call_id'))
                if not start:rec['unmatched_request_call_ids']+=1;continue
                if start.get('purpose')!='agent' or stamp(start['started_at'])<first:continue
                images=0;text=[]
                for m in r.get('messages') or []:
                    content=m.get('content')
                    if isinstance(content,str):text.append(content)
                    elif isinstance(content,list):
                        for block in content:
                            if isinstance(block,dict):
                                images+=block.get('type') in ('image_url','input_image','image')
                                if block.get('type')=='text':text.append(block.get('text',''))
                body='\n'.join(text);error='image could not be analyzed' in body;replacement='The user attached an image' in body
                rec['post_sdk_requests']+=1;rec['requests_with_image_parts']+=images>0;rec['requests_zero_image_parts']+=images==0
                rec['requests_zero_image_with_caption_error']+=images==0 and error;rec['requests_zero_image_with_caption_replacement']+=images==0 and replacement
                rec['requests_with_images_and_caption_error']+=images>0 and error
                if len(rec['examples'])<3 or (images>0 and not any(e['image_parts']>0 for e in rec['examples'])):
                    rec['examples'].append({'call_id':r['call_id'],'started_at':start['started_at'],'image_parts':images,'caption_error':error,'caption_replacement':replacement})
    except (EOFError,OSError,json.JSONDecodeError) as e:rec['archive_read_error']=type(e).__name__
    if not rec['post_sdk_requests']:rec['classification']='no_post_event_request_observed'
    elif rec['requests_zero_image_with_caption_replacement'] and not rec['requests_with_image_parts']:rec['classification']='caption_replacement_zero_image_confirmed'
    elif rec['requests_with_images_and_caption_error'] or (rec['requests_with_image_parts'] and rec['requests_zero_image_with_caption_replacement']):rec['classification']='mixed_image_and_caption_routing'
    elif rec['requests_with_image_parts']:rec['classification']='image_parts_observed_not_full_payload_validation'
    else:rec['classification']='post_requests_zero_image_no_caption_marker_unknown'
    return rec


def main():
    records=[]
    for campaign,root in [('core',ROOT/'outputs/campaigns/bc100-r3-all-strategies/jobs/hermes/visual'),('rq3',ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3/jobs/hermes')]:
        pattern='*/attempts/attempt_*' if campaign=='core' else '*/*/attempts/attempt_*'
        for a in sorted(root.glob(pattern)):records.append(inspect(a,campaign))
    summary={}
    for group in ['core','rq3']:
        rows=[r for r in records if r['campaign']==group];compressed=[r for r in rows if r['compression_events'] or r['render_events']]
        summary[group]={'observed_attempts':len(rows),'attempts_with_render_or_compression':len(compressed),
         'classifications':dict(collections.Counter(r['classification'] for r in rows)),
         'post_requests':sum(r['post_sdk_requests'] for r in compressed),
         'zero_image_caption_error_requests':sum(r['requests_zero_image_with_caption_error'] for r in compressed),
         'zero_image_caption_replacement_requests':sum(r['requests_zero_image_with_caption_replacement'] for r in compressed),
         'post_requests_with_images':sum(r['requests_with_image_parts'] for r in compressed)}
    out=ROOT/'outputs/visual-integrity-audit';out.mkdir(exist_ok=True)
    data={'as_of':datetime.now(timezone.utc).isoformat(),'summary':summary,'records':records,
     'limitations':['This classifies existing SDK request archives, not rerun results or benchmark correctness.',
       'No-compression attempts are kept separate and are not invalidated by this image-routing audit.',
       'Zero image plus explicit caption replacement proves a different representation was sent; error text additionally proves caption failed.',
       'DSH HTTP payload coverage is not provided by this script. RQ3 external core1x is audited under core only; no duplicate counting.',
       'Active logs may advance after snapshot. Missing post-event requests do not prove success or failure.']}
    (out/'delivery-classification.json').write_text(json.dumps(data,indent=2));print(json.dumps({'as_of':data['as_of'],'summary':summary},indent=2))
if __name__=='__main__':main()
