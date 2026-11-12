"""V9 repair + retry3 + metadata-only pre-route failure diagnostics."""
from unittest.mock import patch
from lab import ROOT
import dsh_retry3_worker_v10 as previous
import run_dsh_eval_v3 as native


def main():
    original=native.command
    def command(root,harness,prompt,env):
        argv=original(root,harness,prompt,env)
        env['NODE_OPTIONS']=env.get('NODE_OPTIONS','')+' --import '+str(ROOT/'scripts/dsh_fetch_diagnostics_v11.mjs')
        return argv
    with patch.object(native,'command',command):previous.main()

if __name__=='__main__':main()
