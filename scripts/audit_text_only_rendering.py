#!/usr/bin/env python3
"""Offline audit of actual Hermes formatter and PDF renderer. No model/network calls."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    source=ROOT/'hermes-agent/plugins/context_engine/visual/render.py'
    spec=importlib.util.spec_from_file_location('audited_renderer',source)
    render=importlib.util.module_from_spec(spec);spec.loader.exec_module(render)
    import pymupdf as fitz
    out=ROOT/'outputs/experiment3/text-only-audit';out.mkdir(parents=True,exist_ok=True)
    # File extension and tool name intentionally satisfy the production table-detection path.
    message={'role':'tool','tool_name':'execute_code','tool_call_id':'t1',
        'content':'| item | amount |\n| --- | --- |\n| AUDIT_FACT_Q | 731942 |'}
    block=render._format_message_block(message,tool_name_map={'t1':('execute_code','read_csv("audit.csv")')})
    observed={}
    for text_only in (False,True):
        pdf=render._blocks_to_pdf_bytes([block],font_path=None,font_size=16,page_width=1600,
            max_image_height=2400,dpi=150,text_only=text_only)
        tag='text-only' if text_only else 'visual'
        (out/f'{tag}.pdf').write_bytes(pdf)
        with fitz.open(stream=pdf,filetype='pdf') as document:
            text='\n'.join(page.get_text() for page in document)
        observed[tag]={'pdf_text':text,'fact_retained':'731942' in text}
    result={'source':str(source.relative_to(ROOT)),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'input':message,'formatted_block':block,'observed':observed,
        'table_loss_reproduced':observed['visual']['fact_retained'] and not observed['text-only']['fact_retained'],
        'scope':'Current source snapshot only; does not prove historical campaign behavior.'}
    (out/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
