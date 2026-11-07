#!/usr/bin/env python3
"""Reuse the existing isolated trial supervisor, routing only its Hermes child.

No changes to the core supervisor or native agent loop. This separate process
injects the RQ3 rasterizer adapter at the child executable boundary.
"""
import subprocess
from lab import ROOT
import run_bc_trial


def main():
    original=subprocess.Popen
    def launch(args,*positional,**kwargs):
        if isinstance(args,list) and len(args)>1 and args[1]==str(ROOT/'scripts/hermes_bc_worker.py'):
            args=list(args);args[1]=str(ROOT/'scripts/rq3_hermes_worker.py')
        return original(args,*positional,**kwargs)
    subprocess.Popen=launch
    try:run_bc_trial.main()
    finally:subprocess.Popen=original


if __name__=='__main__':main()
