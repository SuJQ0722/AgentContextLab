"""Accept one exact returned-model alias without rewriting provider evidence."""
import argparse
import concurrent.futures
import fcntl
import json
from pathlib import Path
import re
import time
from unittest.mock import patch

import info_loss_inline_runtime_v9 as runtime
import info_loss_inline_retry_v8 as previous
from lab import ROOT

VERSION = 'info-loss-model-alias-v10'
ALIAS = 'deepseek-v4.1-flash-1017'
DEFAULT = ROOT / 'outputs/experiment6/model-alias-v10'
ORIGINAL_CLIENT = previous.Client


class Client(ORIGINAL_CLIENT):
    def call(self, key, prompt, images=(), purpose='evaluation'):
        result = super().call(key, prompt, images, purpose)
        if result.get('status') != 'model_identity_mismatch' or result.get('returned_model') != ALIAS:
            return result
        # The original parser has already required HTTP 200 and choices/message.
        # Never accept another alias or fabricate a successful provider response.
        if result.get('http_status') != 200:
            return result
        candidates = []
        for folder in (self.attempt / 'calls').glob('*'):
            if not folder.name.startswith(key + '_') or not (folder / 'response.json').exists():
                continue
            if previous.phase.read(folder / 'response.json') == result:
                started = previous.phase.read(folder / 'started.json')
                candidates.append((started['request_number'], folder, started))
        if not candidates:
            raise ValueError('Alias acceptance requires the exact physical response ledger')
        _, folder, started = max(candidates, key=lambda x: x[0])
        fingerprint = started.get('request_fingerprint', '')
        if not re.fullmatch('[a-f0-9]{64}', fingerprint):
            raise ValueError('Alias acceptance requires exact request fingerprint')
        raw = previous.phase.read(folder / 'raw-response.json')
        if raw.get('model') != ALIAS or raw.get('usage') != result.get('usage'):
            raise ValueError('Alias acceptance raw provider evidence mismatch')
        original_path = folder / 'response-before-alias.json'
        original_bytes = (folder / 'response.json').read_bytes()
        if original_path.exists() and original_path.read_bytes() != original_bytes:
            raise ValueError('Original alias response proof changed')
        if not original_path.exists(): original_path.write_bytes(original_bytes)
        previous.save(folder / 'model-alias-acceptance.json', {
            'version': VERSION, 'accepted_exact_alias': ALIAS,
            'original_status': result['status'], 'original_response_path': str(original_path),
            'original_response_sha256': previous.phase.sha(original_path),
            'raw_response_sha256': previous.phase.sha(folder / 'raw-response.json'),
            'returned_model_preserved': True, 'usage_preserved': True,
            'request_fingerprint': fingerprint, 'new_model_call': False})
        accepted = {**result, 'status': 'completed', 'model_alias_acceptance_version': VERSION,
                    'original_model_identity_status': result['status']}
        previous.save(folder / 'response.json', accepted)
        previous.save(self.out / 'completed-calls' / fingerprint, accepted)
        return accepted


def install_runtime():
    runtime.install_runtime()
    previous.Client = Client


def reuse_alias_responses(old, out):
    """Normalize only proven canonical false negatives into a fresh cache."""
    reused = []
    for start in sorted(old.glob('conditions/*/*/attempts/*/calls/*/started.json')):
        response, raw_path = start.parent/'response.json', start.parent/'raw-response.json'
        if not response.exists() or not raw_path.exists(): continue
        value, raw = previous.phase.read(response), previous.phase.read(raw_path)
        fingerprint = previous.phase.read(start).get('request_fingerprint', '')
        if (value.get('status') != 'model_identity_mismatch' or value.get('http_status') != 200
                or value.get('returned_model') != ALIAS or raw.get('model') != ALIAS
                or raw.get('usage') != value.get('usage') or not re.fullmatch('[a-f0-9]{64}', fingerprint)):
            continue
        choices = raw.get('choices')
        if not isinstance(choices, list) or not choices or not isinstance(choices[0].get('message'), dict): continue
        if (choices[0]['message'].get('content') or '') != value.get('content'): continue
        target = out/'completed-calls'/fingerprint
        if target.exists(): continue
        previous.save(target, {**value, 'status':'completed', 'model_alias_acceptance_version':VERSION,
            'original_model_identity_status':value['status'], 'reused_source':str(response), 'new_request':False})
        reused.append({'kind':'exact_canonical_alias_response', 'request_fingerprint':fingerprint,
            'source':str(response), 'source_sha256':previous.phase.sha(response),
            'request_proof':str(start), 'request_proof_sha256':previous.phase.sha(start),
            'raw_response':str(raw_path), 'raw_response_sha256':previous.phase.sha(raw_path),
            'target':str(target), 'target_sha256':previous.phase.sha(target)})
    return reused


def prepare(out, old, stop_proof):
    out, old, stop_proof = (Path(p).resolve() for p in (out, old, stop_proof))
    if out == old or out.is_relative_to(old) or old.is_relative_to(out):
        raise ValueError('Independent V10 output generation required')
    proof = previous.phase.read(stop_proof)
    if proof.get('state') != 'SUSPENDED' or proof.get('ready_replicas') != 0 or not proof.get('uid'):
        raise ValueError('V9 CCI must be confirmed suspended with zero replicas')
    prior = previous.phase.read(old / 'manifest.json')
    runtime.verify(old, prior)
    if prior.get('version') != runtime.VERSION:
        raise ValueError('Expected frozen V9 predecessor')
    manifest = previous.prepare(out, Path(prior['parent_manifest']).parent)
    reused = runtime.reuse_successes(old, out, prior, manifest)
    reused.extend(reuse_alias_responses(old, out))
    manifest.update(version=VERSION, previous_generation=str(old), previous_manifest_sha256=previous.phase.sha(old/'manifest.json'),
        old_stop_proof=str(stop_proof), old_stop_proof_sha256=previous.phase.sha(stop_proof), reused_successes=reused,
        runtime_repair={**prior['runtime_repair'], 'additional_exact_returned_model_alias': ALIAS},
        model_alias_policy={'additional_exact_alias': ALIAS, 'raw_returned_model_preserved': True, 'raw_usage_preserved': True})
    manifest['implementation_sha256'].update({'scripts/info_loss_inline_runtime_v9.py': previous.phase.sha(runtime.__file__),
                                            'scripts/info_loss_model_alias_v10.py': previous.phase.sha(__file__)})
    previous.save(out/'manifest.json', manifest)
    (out/'manifest.sha256').write_text(previous.phase.sha(out/'manifest.json')+'\n')
    return manifest


def verify(out, manifest):
    with patch.object(runtime, 'VERSION', VERSION):
        runtime.verify(out, manifest)
    for item in manifest['reused_successes']:
        if 'raw_response' in item and previous.phase.sha(item['raw_response']) != item['raw_response_sha256']:
            raise ValueError('Raw canonical alias reuse proof changed')
    if manifest.get('model_alias_policy') != {'additional_exact_alias': ALIAS, 'raw_returned_model_preserved': True, 'raw_usage_preserved': True}:
        raise ValueError('Exact returned-model alias policy required')
    if any(manifest.get(k) != v for k, v in {'concurrency': 16, 'attempt_timeout_seconds': 3600,
            'max_timeout_retries': 5, 'max_attempts': 6, 'max_images': 10}.items()):
        raise ValueError('Original execution contract must remain unchanged')


def condition(args):
    install_runtime()
    return previous.run_condition(args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT)
    parser.add_argument('--previous', type=Path, default=runtime.DEFAULT)
    parser.add_argument('--stop-proof', type=Path)
    parser.add_argument('--prepare', action='store_true'); parser.add_argument('--resume', action='store_true'); parser.add_argument('--live', action='store_true')
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    install_runtime()
    with (out/'run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.prepare:
            if not args.stop_proof: parser.error('--prepare requires --stop-proof')
            manifest = prepare(out, args.previous, args.stop_proof)
        else: manifest = previous.phase.read(out/'manifest.json')
        verify(out, manifest)
        if not args.live:
            print(json.dumps({'paid_calls': 0, 'version': VERSION, 'cases': len(manifest['cases']),
                'conditions': len(manifest['cases'])*len(manifest['methods']), 'concurrency': 16,
                'additional_exact_returned_model_alias': ALIAS, 'reused_successes': len(manifest['reused_successes'])}))
            return
        if not args.resume: parser.error('--live requires --resume')
        rows = []
        with concurrent.futures.ProcessPoolExecutor(max_workers=16, initializer=install_runtime) as pool:
            futures = [pool.submit(condition, (str(out), case['id'], method)) for case in manifest['cases'] for method in manifest['methods']]
            for future in concurrent.futures.as_completed(futures):
                result = future.result(); rows.append(result); previous.save(out/'condition-results.json', rows)
                responses = list(out.glob('conditions/*/*/attempts/*/calls/*/response.json'))
                starts = list(out.glob('conditions/*/*/attempts/*/calls/*/started.json'))
                usage = previous.summarize_usage([previous.phase.read(p) for p in responses], len(starts))
                usage.update(scope='V10 new attempts only; historical reused calls remain in previous generation', previous_generation=manifest['previous_generation'])
                previous.save(out/'usage-summary.json', usage)
                previous.save(out/'live-status.json', {'at': time.time(), 'version': VERSION,
                    'conditions_finished': len(rows), 'conditions_total': len(futures),
                    'statuses': {status: sum(r['status']==status for r in rows) for status in ('completed', 'timeout', 'blocked', 'failed')},
                    'calls_started': len(starts), 'calls_returned': len(responses)})


if __name__ == '__main__':
    main()
