#!/usr/bin/env python3
"""Versioned JSON adapter over the actual Hermes context engines. Never calls APIs.

Summary generation uses a transactional two-phase exchange: expose the exact
Hermes auxiliary request, then replay with the instrumented host's response.
"""
import copy
from contextlib import contextmanager, ExitStack
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = 'hermes-shared-context-v1'
STRATEGIES = ('none', 'discard', 'sliding_window', 'summarize', 'visual')
STATE_FIELDS = ('last_prompt_tokens', 'last_completion_tokens', 'compression_count',
                '_previous_summary', '_full_history', '_compression_stats', 'max_compressions')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def context_config(strategy, lab_config, save_dir):
    """Identical context settings for new Hermes and DSH execution paths."""
    if strategy not in STRATEGIES:
        raise ValueError('Unsupported shared strategy')
    defaults = {
        'none': {}, 'discard': {'keep_rounds': 0}, 'sliding_window': {'window_size': 5},
        'summarize': {'protect_first_n': 3, 'protect_last_n': 20, 'summary_target_ratio': .20},
        'visual': {'font_size': lab_config['visual_renderer']['font_size'],
                   'history_scale': lab_config['visual_renderer']['history_scale'],
                   'keep_rounds': 1, 'recent_rounds': 5, 'save_dir': str(save_dir)},
    }
    settings = {**defaults[strategy], **lab_config.get('shared_policy', {}).get('strategy_configs', {}).get(strategy, {})}
    if strategy == 'visual':
        settings['save_dir'] = str(save_dir)
    return {'engine': 'compressor' if strategy == 'none' else strategy, 'strategy_config': settings}


def policy_config(strategy, lab_config, save_dir):
    return {'model': lab_config['model'], 'context_length': lab_config['context_window'],
            'provider': 'custom', 'api_mode': 'chat_completions',
            'threshold_tokens': lab_config['pilot']['compression_trigger_tokens'],
            'max_compressions': lab_config.get('shared_policy', {}).get('max_compressions'),
            'strategy_config': context_config(strategy, lab_config, save_dir)['strategy_config']}


@contextmanager
def explicit_configuration():
    removed = {key: value for key, value in os.environ.items()
               if key.startswith('HERMES_VISUAL_') or key == 'HERMES_DISCARD_KEEP_ROUNDS'}
    for key in removed:
        os.environ.pop(key)
    try:
        yield
    finally:
        os.environ.update(removed)


def configure_engine(engine, strategy, config):
    """Configure an existing Hermes engine without changing its runtime credentials."""
    if strategy == 'none':
        return
    if engine.name != strategy:
        raise ValueError('Engine implementation does not match shared strategy')
    with explicit_configuration():
        engine.configure({'strategy_config': config.get('strategy_config', {})})
    threshold = config.get('threshold_tokens', 32768)
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold <= 0:
        raise ValueError('Positive integer provider-token threshold required')
    engine.threshold_tokens = threshold
    if hasattr(engine, 'max_compressions'):
        limit = config.get('max_compressions')
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 0):
            raise ValueError('max_compressions must be a nonnegative integer or null')
        engine.max_compressions = limit
    if strategy == 'visual':
        from rq3_pdf_renderer import install
        engine._shared_pdf_adapter = install()


def implementation_hashes(strategy):
    paths = ['hermes-agent/agent/context_engine.py', 'scripts/shared_context_policy.py']
    if strategy != 'none':
        paths.append(f'hermes-agent/plugins/context_engine/{strategy}/__init__.py')
    if strategy == 'visual':
        paths.extend(['hermes-agent/plugins/context_engine/visual/render.py', 'scripts/rq3_pdf_renderer.py'])
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}


def make_engine(strategy, config):
    if strategy == 'none':
        return None
    if str(ROOT / 'hermes-agent') not in sys.path:
        sys.path.insert(0, str(ROOT / 'hermes-agent'))
    from importlib import import_module
    names = {'discard': 'DiscardEngine', 'sliding_window': 'SlidingWindowEngine',
             'summarize': 'SummarizeEngine', 'visual': 'VisualEngine'}
    cls = getattr(import_module(f'plugins.context_engine.{strategy}'), names[strategy])
    engine = cls()
    engine.update_model(model=config.get('model', ''), context_length=config.get('context_length', 200000),
                        provider=config.get('provider', 'custom'), api_mode=config.get('api_mode', 'chat_completions'))
    configure_engine(engine, strategy, config)
    return engine


def export_state(engine, strategy, config, hashes):
    fields = {key: copy.deepcopy(getattr(engine, key)) for key in STATE_FIELDS if engine is not None and hasattr(engine, key)}
    cooldown = getattr(engine, '_summary_failure_cooldown_until', 0) if engine is not None else 0
    remaining = max(0, cooldown - time.monotonic())
    return {'protocol': PROTOCOL, 'strategy': strategy, 'policy_config_sha256': digest(config),
            'implementation_sha256': hashes, 'engine': fields,
            'summary_cooldown_until_unix': time.time() + remaining if remaining > 0 else 0}


def restore_state(engine, state, strategy, config, hashes):
    if not state:
        return
    if (state.get('protocol') != PROTOCOL or state.get('strategy') != strategy
            or state.get('policy_config_sha256') != digest(config)
            or state.get('implementation_sha256') != hashes):
        raise ValueError('State protocol, strategy, configuration or implementation changed; new lineage required')
    fields = state.get('engine', {})
    if set(fields) - set(STATE_FIELDS):
        raise ValueError('Unknown engine state fields')
    if engine is not None:
        for key, value in fields.items():
            setattr(engine, key, copy.deepcopy(value))
        if hasattr(engine, '_summary_failure_cooldown_until'):
            deadline = state.get('summary_cooldown_until_unix', 0)
            engine._summary_failure_cooldown_until = time.monotonic() + max(0, deadline - time.time()) if deadline else 0


class AwaitingSummary(BaseException):
    def __init__(self, pending):
        self.pending = pending


class SummaryResponseMismatch(BaseException):
    pass


def apply_policy(request):
    """Apply one transactional policy decision to full OpenAI-format messages."""
    started = time.perf_counter()
    timings = {'engine_seconds': 0.0, 'renderer_seconds': 0.0, 'renderer_calls': 0,
               'definition': 'Local wall time only; renderer is nested inside engine; excludes host model API and subprocess IPC.'}
    def finish(response):
        timings['policy_total_seconds'] = time.perf_counter() - started
        response['timings'] = dict(timings)
        return response
    strategy = request['strategy']
    if strategy not in STRATEGIES:
        raise ValueError('Unsupported shared strategy')
    config = copy.deepcopy(request['config'])
    if set(config) - {'model', 'context_length', 'provider', 'api_mode', 'threshold_tokens', 'strategy_config', 'max_compressions'}:
        raise ValueError('Unsupported policy config fields; credentials do not belong in this interface')
    messages = copy.deepcopy(request['messages'])
    if not isinstance(messages, list) or any(not isinstance(m, dict) or m.get('role') not in ('system', 'developer', 'user', 'assistant', 'tool') for m in messages):
        raise ValueError('Expected full OpenAI-role message sequence')
    operation = request.get('operation', 'apply')
    if operation not in ('apply', 'check'):
        raise ValueError('Unknown policy operation')
    hashes = implementation_hashes(strategy)
    engine = make_engine(strategy, config)
    restore_state(engine, request.get('state'), strategy, config, hashes)
    state_before = export_state(engine, strategy, config, hashes)
    response = {'protocol': PROTOCOL, 'strategy': strategy, 'messages': messages,
                'state': state_before, 'input_messages_sha256': digest(messages), 'auxiliary_calls': [],
                'changed': False, 'compression_triggered': False, 'status': 'unchanged'}
    if strategy == 'visual':
        response['pdf_adapter'] = engine._shared_pdf_adapter
    if strategy == 'none':
        response['reason'] = 'compression_disabled'
        return finish(response)
    usage = request.get('provider_usage')
    prompt_tokens = usage.get('prompt_tokens') if isinstance(usage, dict) else None
    if (not isinstance(prompt_tokens, int) or isinstance(prompt_tokens, bool) or prompt_tokens < 0):
        response.update(status='awaiting_usage', reason='measured_provider_prompt_tokens_missing')
        return finish(response)
    completion = usage.get('completion_tokens')
    if completion is not None and (not isinstance(completion, int) or isinstance(completion, bool) or completion < 0):
        raise ValueError('Invalid measured completion token count')
    engine.update_from_response({'prompt_tokens': prompt_tokens, 'completion_tokens': completion or 0})
    should_compress = engine.should_compress()
    response['compression_triggered'] = should_compress
    response['threshold_tokens'] = engine.threshold_tokens
    response['provider_usage'] = copy.deepcopy(usage)
    if not should_compress or operation == 'check':
        response.update(state=export_state(engine, strategy, config, hashes),
                        reason='threshold_reached' if should_compress else 'below_threshold')
        return finish(response)
    before_count = engine.compression_count
    pending_transaction = digest({'messages': messages, 'state': state_before, 'config': config,
                                  'strategy': strategy, 'provider_usage': usage, 'implementation': hashes,
                                  'focus_topic': request.get('focus_topic')})
    consumed_summary = False

    def summary_call(**kwargs):
        nonlocal consumed_summary
        runtime = kwargs.get('main_runtime') or {}
        pending = {'task': kwargs['task'], 'messages': kwargs['messages'], 'max_tokens': kwargs['max_tokens'],
                   'model': runtime.get('model', config.get('model', '')),
                   'provider': runtime.get('provider', config.get('provider', 'custom')),
                   'api_mode': runtime.get('api_mode', config.get('api_mode', 'chat_completions')),
                   'transaction_sha256': pending_transaction}
        pending['request_sha256'] = digest(pending)
        supplied = request.get('summary_response')
        if supplied is None:
            raise AwaitingSummary(pending)
        if supplied.get('request_sha256') != pending['request_sha256'] or consumed_summary:
            raise SummaryResponseMismatch('Summary response does not match this exact pending transaction')
        consumed_summary = True
        response['auxiliary_calls'].append({'request_sha256': pending['request_sha256'],
                                            'usage': supplied.get('usage'), 'error': supplied.get('error'),
                                            'host_call_id': supplied.get('call_id'), 'instrumentation': 'host_reported'})
        if supplied.get('error'):
            raise RuntimeError('Instrumented host reported summary failure')
        content = supplied.get('content')
        if not isinstance(content, str):
            raise SummaryResponseMismatch('Summary response content must be a string or explicit error')
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    try:
        # Importing the auxiliary module does not make requests. Every invocation
        # is replaced before the actual SummarizeEngine can use it.
        from agent import auxiliary_client
        with ExitStack() as stack:
            stack.enter_context(patch.object(auxiliary_client, 'call_llm', summary_call))
            if strategy == 'visual':
                from plugins.context_engine.visual import render
                actual_render = render.render_visual_compression
                def timed_render(*args, **kwargs):
                    render_started = time.perf_counter()
                    timings['renderer_calls'] += 1
                    try:
                        return actual_render(*args, **kwargs)
                    finally:
                        timings['renderer_seconds'] += time.perf_counter() - render_started
                stack.enter_context(patch.object(render, 'render_visual_compression', timed_render))
            engine_started = time.perf_counter()
            try:
                transformed = engine.compress(copy.deepcopy(messages), current_tokens=prompt_tokens,
                                              focus_topic=request.get('focus_topic'))
            finally:
                timings['engine_seconds'] += time.perf_counter() - engine_started
        if request.get('summary_response') is not None and not consumed_summary:
            raise ValueError('Supplied summary response was not consumed; original transaction is stale')
    except AwaitingSummary as pending:
        response.update(status='awaiting_summary', pending_call=pending.pending,
                        reason='host_must_execute_and_account_for_exact_auxiliary_request')
        # No pruned messages or partial engine state are committed.
        return finish(response)
    except SummaryResponseMismatch as exc:
        error = ValueError(str(exc))
        error.policy_timings = finish({})['timings']
        raise error from exc
    except Exception as exc:
        exc.policy_timings = finish({})['timings']
        raise
    response.update(messages=transformed, changed=transformed != messages,
                    state=export_state(engine, strategy, config, hashes),
                    status='compressed' if engine.compression_count > before_count else 'unchanged',
                    reason='engine_applied' if engine.compression_count > before_count else 'engine_no_eligible_span',
                    compression_count=engine.compression_count)
    if strategy == 'visual' and engine._compression_stats['per_compression']:
        response['render_stats'] = engine._compression_stats['per_compression'][-1]
    return finish(response)


def main():
    request = json.load(sys.stdin)
    try:
        response = apply_policy(request)
    except Exception as exc:
        print(json.dumps({'protocol': PROTOCOL, 'status': 'error', 'error_type': type(exc).__name__,
                          'error': str(exc), 'timings': getattr(exc, 'policy_timings', None)}, ensure_ascii=False))
        raise SystemExit(1)
    print(json.dumps(response, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
