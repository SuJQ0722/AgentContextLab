from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import monitor_bc_v3_node as monitor


class NodeRoleTests(unittest.TestCase):
    def test_hot_policy_controller_is_counted_and_registered_as_core(self):
        script='run_bc_campaign_v3_capacity_ops.py'
        argv={11:b'python\0/project/scripts/run_bc_campaign_v3_capacity_ops.py\0--dispatch-role\0cloud\0',
              12:b'python\0/project/scripts/run_bc_trial_v3_capacity1.py\0',
              13:b'python\0/project/scripts/run_dsh_eval_v3_capacity1.py\0',
              14:b'node\0/native/dsh\0'}
        processes={pid:{'state':'S','group':'core_bc_v3'} for pid in argv}
        def process_snapshot():
            self.assertEqual(monitor.monitor_rebuttal.SCRIPT_GROUPS[script],'core_bc_v3')
            return processes
        def read_bytes(path):return argv[int(path.parent.name)]
        def readlink(path):return '/usr/bin/node' if int(path.parent.name)==14 else '/usr/bin/python'
        with patch.object(monitor.monitor_rebuttal,'process_snapshot',side_effect=process_snapshot),\
             patch.object(Path,'read_bytes',read_bytes),patch.object(monitor.os,'readlink',side_effect=readlink):
            census=monitor.process_census()
        self.assertEqual(census['core_v3_subtree_live'],4)
        self.assertEqual(census['core_v3_roles']['controller'],1)
        self.assertEqual(census['core_v3_roles']['trial'],1)
        self.assertEqual(census['core_v3_roles']['dsh_worker'],1)
        self.assertEqual(census['core_v3_node_runtime_live'],1)
        self.assertEqual(census['role_read_failures'],0)

    def test_shell_code_mention_does_not_count_as_controller_role(self):
        process={20:{'state':'S','group':'core_bc_v3'}}
        with patch.object(monitor.monitor_rebuttal,'process_snapshot',return_value=process),\
             patch.object(Path,'read_bytes',return_value=b'python\0-c\0print("run_bc_campaign_v3_capacity_ops.py")\0'),\
             patch.object(monitor.os,'readlink',return_value='/usr/bin/python'):
            census=monitor.process_census()
        self.assertEqual(census['core_v3_roles']['controller'],0)

    def test_routes1_native_entry_names_have_expected_roles(self):
        expected={'run_bc_campaign_v3_routes2_io3.py':'controller','run_bc_trial_v3_routes2_io3.py':'trial',
                  'run_dsh_eval_v3_routes2_io3.py':'dsh_worker','run_bc_campaign_v3_routes2.py':'controller','run_bc_trial_v3_routes2.py':'trial',
                  'run_bc_campaign_v3_routes1.py':'controller','run_bc_trial_v3_routes1.py':'trial',
                  'hermes_bc_worker_routes1.py':'hermes_worker','run_dsh_eval_v3_routes1.py':'dsh_worker'}
        for name,role in expected.items():self.assertEqual(monitor.ROLE_SCRIPTS.get(name),role)

if __name__=='__main__':unittest.main()
