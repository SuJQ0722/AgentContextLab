"""Explicit image-capacity repair; this local ceiling is not a provider guarantee."""
import hashlib
from pathlib import Path
from dsh_image_preservation import preservation_patches as original_patches

IMAGE_PRESERVATION_VERSION = 'original-image-bytes-capacity1'
MAX_REQUEST_BYTES = 64 * 1024 * 1024
RUNTIME_FILES = (
    'scripts/dsh_image_preservation_capacity1.py',
    'scripts/run_dsh_eval_v3_capacity1.py',
    'scripts/dsh_wire_image_guard_capacity1.mjs',
    'scripts/run_bc_trial_v3_capacity1.py',
    'scripts/run_bc_campaign_v3_capacity1.py',
)
DEPENDENCIES = (
    'scripts/dsh_image_preservation.py', 'scripts/run_dsh_eval_v3.py',
    'scripts/dsh_wire_image_guard.mjs', 'scripts/dsh_wire_expectations.mjs',
    'scripts/run_bc_trial_v3.py', 'scripts/run_bc_trial_v3_io.py',
    'scripts/run_bc_trial_v3_io2.py', 'scripts/run_bc_campaign_v3.py',
    'scripts/run_bc_campaign_v3_io2.py',
)


def preservation_patches(env):
    patches = original_patches(env)
    provider = next(p for p in patches if p['id'] == 'llm-pi-ai')['config']['providers']['tokenhub']
    provider['maxRequestImageBytes'] = MAX_REQUEST_BYTES
    # The shipped base bundle's instance ID differs from the package/plugin name.
    patches.append({'id': 'image-offload', 'disabled': True})
    return patches


def runtime_record():
    root = Path(__file__).resolve().parents[1]
    return {
        'runtime_version': IMAGE_PRESERVATION_VERSION,
        'implementation_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in RUNTIME_FILES},
        'parent_dependency_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in DEPENDENCIES},
        'transport_diff': {
            'maxRequestImageBytes': {'before': 20 * 1024 * 1024, 'after': MAX_REQUEST_BYTES, 'unit': 'base64 image payload bytes'},
            'compaction-image-offload': {'instance_id': 'image-offload', 'before': 'enabled', 'after': 'disabled'},
            'guard_audit': 'Inspect retained images before detail validation; count/order/hash/detail rejection unchanged',
        },
        'provider_acceptance': 'Unknown beyond previously observed requests; 64 MiB is a local ceiling only',
        'unchanged': ['model', 'tools', 'context policy', 'compression trigger', 'rendering',
                      'source image admission limits', 'image bytes', 'image detail', 'cohort', 'repeats'],
        'compatibility': 'For the same input history and image payload <=20 MiB, successful model-visible request bytes/details are unchanged. This does not assert identical stochastic trajectories or timings. Over-limit trajectories use a changed transport policy and must retain this lineage.',
        'analysis_policy': 'Report prior offload/guard failures and their incurred costs separately; report repair/maintenance period costs separately. Never overwrite or automatically retry old claimed attempts.',
    }
