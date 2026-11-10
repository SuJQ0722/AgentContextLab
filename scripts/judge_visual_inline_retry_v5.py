"""Private V5 grading with HTTP-route attempt accounting; same scoring protocol."""
from pathlib import Path
from unittest.mock import patch
import judge_visual_hosted_retry_v1 as parent
from lab import ROOT
from visual_inline_route_accounting_v5 import resources

VERSION='judge-visual-inline-retry-v5'
DEFAULT=ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v5'
OUT=ROOT/'outputs/grading/visual-inline-failure-retry-v5'
_original_prepare=parent.prepare
_original_immutable=parent.immutable

def prepare(root,out):
    def immutable(path,value):
        if Path(path).name=='protocol.json':
            value['resource_accounting_version']='visual-inline-route-accounting-v5'
            value['sources_sha256'].update({name:parent.sha(ROOT/'scripts'/name)for name in
                ('judge_visual_inline_retry_v5.py','visual_inline_route_accounting_v5.py')})
        return _original_immutable(path,value)
    with patch.object(parent,'immutable',immutable):return _original_prepare(root,out)

def main():
    with patch.object(parent,'resources',resources),patch.object(parent,'prepare',prepare),\
         patch.object(parent,'VERSION',VERSION),patch.object(parent,'DEFAULT',DEFAULT),patch.object(parent,'OUT',OUT):
        parent.main()
if __name__=='__main__':main()
