#!/usr/bin/env python3
"""Offline five-policy parity and two-compression subprocess restart fixture."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def turns(start, count):
    result = []
    for index in range(start, start + count):
        result += [{'role': 'assistant', 'content': f'Step {index}', '_dsh_original_id': f'a{index}',
                    'tool_calls': [{'id': f'c{index}', 'type': 'function', 'function': {'name': 'web_search', 'arguments': '{}'}}]},
                   {'role': 'tool', 'tool_call_id': f'c{index}', '_dsh_original_id': f't{index}',
                    'content': (f'Confirmed fixture evidence {index}. ' * 40)}]
    return result


def worker(out):
    from shared_context_policy import STRATEGIES, apply_policy, make_engine, policy_config, digest
    from lab import environment
    env, _ = environment(ROOT, 'hermes')
    out.mkdir(parents=True, exist_ok=False)
    fixture_cfg = {'model': 'offline-fixture', 'context_window': 65536, 'pilot': {'compression_trigger_tokens': 32768},
                   'visual_renderer': {'font_size': 16, 'history_scale': 1},
                   'shared_policy': {'strategy_configs': {'summarize': {'protect_last_n': 3, 'summary_target_ratio': .1}}}}
    results = []
    def external(req):
        process = subprocess.run([sys.executable, str(ROOT / 'scripts/shared_context_policy.py')],
                                 input=json.dumps(req), text=True, capture_output=True, env=env, check=True)
        return json.loads(process.stdout)
    for strategy in STRATEGIES:
        directory = out / strategy; directory.mkdir()
        cfg = policy_config(strategy, fixture_cfg, directory / 'canvas')
        engine = make_engine(strategy, cfg)
        current = [{'role': 'system', 'content': 'Fixture instructions', '_dsh_original_id': 'sys'},
                   {'role': 'user', 'content': 'Retain evidence from every fixture round.', '_dsh_original_id': 'task'}] + turns(0, 12)
        state = None
        for phase in (1, 2):
            if phase == 2:
                current = current + turns(20, 10)
            usage = {'prompt_tokens': 40000, 'completion_tokens': 7}
            req = {'strategy': strategy, 'messages': copy.deepcopy(current), 'config': cfg,
                   'state': state, 'provider_usage': usage}
            result = external(req)
            summary_text = f'Offline checkpoint {phase}: preserve task, completed facts and open followups.'
            captured = []
            def fixture_summary(**kwargs):
                captured.append(kwargs)
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=summary_text))])
            if strategy == 'none':
                expected = current
            else:
                engine.update_from_response(usage)
                from agent import auxiliary_client
                with patch.object(auxiliary_client, 'call_llm', fixture_summary):
                    expected = engine.compress(copy.deepcopy(current), current_tokens=40000)
            if result['status'] == 'awaiting_summary':
                assert captured and captured[0]['messages'] == result['pending_call']['messages']
                assert captured[0]['max_tokens'] == result['pending_call']['max_tokens']
                req['state'] = result['state']
                req['summary_response'] = {'request_sha256': result['pending_call']['request_sha256'],
                                           'content': summary_text, 'usage': None, 'call_id': f'offline-{phase}'}
                result = external(req)
            assert result['messages'] == expected, (strategy, phase, 'transformed messages differ')
            if strategy == 'visual':
                assert result['state']['engine']['_full_history'] == engine._full_history
                assert result['state']['engine']['_compression_stats'] == engine._compression_stats
                assert result['timings']['renderer_calls'] == 1
                assert 0 < result['timings']['renderer_seconds'] <= result['timings']['engine_seconds'] <= result['timings']['policy_total_seconds']
            if strategy == 'summarize':
                assert result['state']['engine']['_previous_summary'] == engine._previous_summary
                if phase == 2 and captured:
                    assert 'Offline checkpoint 1' in captured[0]['messages'][0]['content']
            assert result.get('compression_count', 0) == (engine.compression_count if engine else 0)
            (directory / f'phase-{phase}.json').write_text(json.dumps(result, indent=2))
            results.append({'strategy': strategy, 'phase': phase, 'subprocess_restart': True,
                            'direct_hermes_messages_identical': True, 'output_messages_sha256': digest(expected),
                            'compression_count': result.get('compression_count', 0),
                            'summary_prompt_identical': bool(captured) if strategy == 'summarize' else None,
                            'local_timings': result['timings'],
                            'visual_full_history_messages': len(engine._full_history) if strategy == 'visual' else None})
            current = result['messages']; state = result['state']
    report = {'passed': True, 'paid_calls': 0, 'network_calls': 0, 'conditions': results,
              'scope': 'Direct Hermes engine versus new Python process on each step; not a DSH native surface persistence test.'}
    (out / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'passed': True, 'paid_calls': 0, 'conditions': len(results), 'artifact': str(out / 'result.json')}))


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--out', required=True, type=Path); parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        worker(args.out.resolve())
    else:
        from lab import environment, python_for
        env, _ = environment(ROOT, 'hermes'); env['HERMES_HOME'] = str(args.out.resolve().parent / '.shared-policy-home')
        subprocess.run([python_for(ROOT), str(Path(__file__).resolve()), '--worker', '--out', str(args.out.resolve())],
                       cwd=ROOT, env=env, check=True)


if __name__ == '__main__':
    main()
