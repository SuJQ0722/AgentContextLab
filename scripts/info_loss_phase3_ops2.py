#!/usr/bin/env python3
"""Future operational entry with a stop gate before every new call; no protocol change."""
import argparse
from pathlib import Path
import info_loss_phase3_ops as ops

class QualityHold(BaseException):pass

def check_hold(root):
    for name in ('quality-hold.json','STOP','STOP.json'):
        if (root/name).exists():raise QualityHold('Explicit hold exists: '+name)

class StopAwareClient(ops.study.Client):
    def call(self,*args,**kwargs):
        check_hold(self.out)
        return super().call(*args,**kwargs)

def main():
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--output',type=Path,default=ops.study.DEFAULT_OUT);args,_=parser.parse_known_args()
    check_hold(args.output.resolve())
    original=ops.study.Client;ops.study.Client=StopAwareClient
    try:ops.main()
    finally:ops.study.Client=original
if __name__=='__main__':main()
