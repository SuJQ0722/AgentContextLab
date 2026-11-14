"""Opt-in MMBC route guard; preserve the frozen transport and its telemetry.

V3 rotation does not consume max_failed_sends. Bound physical HTTP sends per
logical request here, below rotation and above the explicit proxy transport.
TerminalTransportFailure bypasses SDK and Hermes retry multiplication. This is
cost/wait containment, not evidence of improved task completion.
"""
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import threading
import time
from unittest.mock import patch

import httpx
import visual_transport_runtime_v4 as proxy_runtime
from visual_transport_runtime_v3 import install as frozen_routes
from visual_transport_runtime_v3 import TerminalTransportFailure

VERSION = 'mmbc-bounded-route-runtime-v1'


def install(policy, out, *, approved_base_url, max_http_attempts=3, **kwargs):
    # Stop before a complete four-route cycle: frozen inter-cycle backoff cannot
    # consume the remainder of a task after this budget has been exhausted.
    if type(max_http_attempts) is not int or not 1 <= max_http_attempts <= 3:
        raise ValueError('Explicit per-request HTTP attempt limit must be 1..3')
    if policy.get('max_failed_sends') != max_http_attempts:
        raise ValueError('Configured max_failed_sends must match the effective request limit')
    if getattr(httpx.Client._send_single_request, '_mmbc_bounded_routes_v1', False):
        raise RuntimeError('Fresh MMBC worker required')
    endpoint = httpx.URL(approved_base_url.rstrip('/') + '/chat/completions')
    path = Path(out)/'mmbc-request-budget-v1.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    state = ContextVar('mmbc_logical_request_budget', default=None)
    lock = threading.Lock()

    def emit(row):
        with lock, path.open('a') as stream:
            stream.write(json.dumps({'version': VERSION, 'at_unix': time.time(), **row})+'\n')

    def bounded_routes(transport_policy, route_out, **route_kwargs):
        proxied = httpx.Client._send_single_request

        def limited_send(client, request):
            if request.url != endpoint:
                return proxied(client, request)
            current = state.get()
            if current is None:
                raise TerminalTransportFailure('mmbc_request_budget_missing_scope')
            if current['sends'] >= max_http_attempts:
                emit({'event': 'request_budget_exhausted', 'logical_body_sha256': current['sha256'],
                      'http_sends': current['sends'], 'max_http_attempts': max_http_attempts,
                      'client_seconds': time.monotonic()-current['start'],
                      'network_send_authorized': False, 'usage_known': False,
                      'classification': 'transport_failure_not_task_incorrect'})
                raise TerminalTransportFailure('mmbc_logical_request_http_attempt_budget')
            current['sends'] += 1
            emit({'event': 'http_send_authorized', 'logical_body_sha256': current['sha256'],
                  'http_send_number': current['sends'], 'max_http_attempts': max_http_attempts,
                  'routed_body_sha256': hashlib.sha256(request.content).hexdigest()})
            return proxied(client, request)

        httpx.Client._send_single_request = limited_send
        try:
            handle = frozen_routes(transport_policy, route_out, **route_kwargs)
        except BaseException:
            httpx.Client._send_single_request = proxied
            raise
        rotated = httpx.Client._send_single_request

        def logical_send(client, request):
            if request.url != endpoint:
                return rotated(client, request)
            current = {'start': time.monotonic(), 'sends': 0,
                       'sha256': hashlib.sha256(request.content).hexdigest()}
            token = state.set(current)
            try:
                return rotated(client, request)
            finally:
                emit({'event': 'logical_request_finished', 'logical_body_sha256': current['sha256'],
                      'http_sends': current['sends'], 'client_seconds': time.monotonic()-current['start']})
                state.reset(token)

        logical_send._mmbc_bounded_routes_v1 = True
        httpx.Client._send_single_request = logical_send
        return handle

    with patch.object(proxy_runtime, 'install_routes', bounded_routes):
        handle = proxy_runtime.install(policy, out, approved_base_url=approved_base_url, **kwargs)
    emit({'event': 'request_budget_configuration', 'max_http_attempts': max_http_attempts,
          'http_wall_seconds': policy['stream_seconds'], 'model_or_image_payload_modified': False,
          'provider_internal_latency_measured': False})
    return {**handle, 'version': VERSION, 'inherited_proxy_version': proxy_runtime.VERSION,
            'max_http_attempts_per_logical_request': max_http_attempts, 'request_budget_ledger': str(path)}
