import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import tarfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from bootstrap_bc_v3_node import clean_environment,compare_runtime,commands
from cloud_python_stage import validate_members


class CloudBootstrapTests(unittest.TestCase):
    def test_provisioning_credentials_are_not_inherited(self):
        original={'HOME':'/root','PATH':'/bin','LANG':'C.UTF-8','SCO_ACCESS_KEY':'secret',
                  'AWS_SECRET_ACCESS_KEY':'secret','AK':'secret','SSH_AUTH_SOCK':'secret',
                  'TOKENHUB_API_KEY':'environment-override','IMAGE_UPLOAD_API_KEY':'override'}
        result=clean_environment(original)
        self.assertEqual(result['HOME'],'/root')
        for key in ['SCO_ACCESS_KEY','AWS_SECRET_ACCESS_KEY','AK','SSH_AUTH_SOCK','TOKENHUB_API_KEY','IMAGE_UPLOAD_API_KEY']:
            self.assertNotIn(key,result)
        self.assertEqual(original['SCO_ACCESS_KEY'],'secret')
        self.assertEqual(result['OMP_NUM_THREADS'],'1')

    def test_runtime_font_changes_fail_instead_of_silent_layout_change(self):
        baseline={'node_version':'v24.11.0','node_sha256':'n','poppler_sha256':{},'reader_source_sha256':'r',
                  'reader':{'python_version':'3.10.19','packages':{}},
                  'hermes':{'python_version':'3.11.15','packages':{},'font_sha256':'font'}}
        compare_runtime(baseline,baseline)
        changed=copy.deepcopy(baseline);changed['hermes']['font_sha256']='different'
        with self.assertRaisesRegex(RuntimeError,'font_sha256'):compare_runtime(changed,baseline)

    def test_controller_is_one_core_cell_32_pending_only_slots(self):
        args=SimpleNamespace(reader_python='/reader/python',root=Path('/afs/new-root'),harness='dsh',strategy='visual')
        command=commands(args)['controller']
        self.assertEqual(command[command.index('--harness')+1],'dsh')
        self.assertEqual(command[command.index('--strategy')+1],'visual')
        self.assertEqual(command[command.index('--concurrency')+1],'32')
        self.assertIn('--resume',command);self.assertIn('--live',command)

    def test_all_dsh_strategies_preserve_accumulated_native_images(self):
        for strategy in ['none', 'summarize', 'sliding_window', 'discard', 'visual']:
            args=SimpleNamespace(reader_python='/reader/python',root=Path('/afs/new-root'),harness='dsh',strategy=strategy,controller_concurrency=4)
            command=commands(args)['controller']
            self.assertEqual(Path(command[1]).name,'run_bc_campaign_v3_capacity1.py')
            self.assertEqual(command[command.index('--concurrency')+1],'4')
        args.harness='hermes';args.strategy='none'
        self.assertEqual(Path(commands(args)['controller'][1]).name,'run_bc_campaign_v3_io2.py')

    def test_python_archive_rejects_path_and_symlink_escape(self):
        file=tarfile.TarInfo('runtime/bin/python');validate_members([file],'runtime')
        with self.assertRaises(ValueError):validate_members([tarfile.TarInfo('../outside')],'runtime')
        link=tarfile.TarInfo('runtime/bin/escape');link.type=tarfile.SYMTYPE;link.linkname='../../../etc/passwd'
        with self.assertRaises(ValueError):validate_members([link],'runtime')


if __name__=='__main__':unittest.main()
