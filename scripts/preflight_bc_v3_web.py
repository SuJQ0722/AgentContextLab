#!/usr/bin/env python3
"""Fresh host-specific BC v3 web readiness through actual Hermes handlers; no LLM."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import time
import uuid
from urllib.parse import urlsplit

from lab import ROOT, environment, python_for
from local_web import configure_web


def sha(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def endpoint(url):
    """Do not serialize userinfo, query parameters, or fragments."""
    parts = urlsplit(url)
    host = parts.hostname or ''
    if ':' in host:
        host = '[' + host + ']'
    return parts.scheme + '://' + host + (':' + str(parts.port) if parts.port else '') + parts.path


def evidence_summary(value, kind):
    payloads = []
    for part in value.get('content', []):
        if part.get('type') == 'text':
            try:
                payloads.append(json.loads(part['text']))
            except (ValueError, KeyError):
                pass
    if kind == 'search':
        rows = [p for p in payloads if p.get('success') is True]
        count = sum(len(p.get('data', {}).get('web', [])) for p in rows)
        return {'usable_evidence': count > 0, 'search_results': count}
    rows = [r for p in payloads for r in p.get('results', [])]
    usable = bool(rows) and all(isinstance(r.get('content'), str) and r['content'].strip()
                                and not r.get('error') for r in rows)
    return {'usable_evidence': bool(usable), 'fetch_results': len(rows),
            'content_characters': sum(len(r.get('content') or '') for r in rows)}


def run_check(kind, artifact, env, timeout):
    workspace = artifact / kind
    request = {'tool': 'web_search' if kind == 'search' else 'web_extract',
               'call_id': 'readiness-' + kind + '-' + uuid.uuid4().hex,
               'arguments': {'query': 'Example Domain IANA', 'limit': 2} if kind == 'search'
               else {'urls': ['https://example.com'], 'char_limit': 2000}}
    started = time.time()
    report = {'started_at_unix': started, 'handler': 'plugins.local_web._handle_search' if kind == 'search'
              else 'plugins.local_web._handle_extract', 'passed': False}
    try:
        process = subprocess.run([python_for(ROOT), str(ROOT / 'scripts/hermes_tool_bridge.py'),
                                  '--workspace', str(workspace)], input=json.dumps(request),
                                 env=env, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
        report['bridge_exit_code'] = process.returncode
        if process.returncode == 0:
            value = json.loads(process.stdout)
            report.update(evidence_summary(value, kind))
            report['handler_seconds'] = value.get('handler_seconds')
        else:
            report['error_type'] = 'BridgeProcessFailed'  # stderr may contain credentials.
    except Exception as error:
        report['error_type'] = type(error).__name__
    report['finished_at_unix'] = time.time()
    report['process_wall_seconds'] = report['finished_at_unix'] - started
    records = []
    metrics = workspace / 'metrics/web.jsonl'
    if metrics.exists():
        for line in metrics.read_text().splitlines():
            try:
                record = json.loads(line)
                # Explicit allowlist: no transport URLs, headers, or response text.
                records.append({k: record.get(k) for k in ('kind', 'proxy_http_status', 'http_success',
                    'cache_header', 'cache_layer', 'fetch_backend', 'primary_cache_header',
                    'client_http_seconds', 'origin_http_status', 'error_type')})
            except (ValueError, TypeError):
                report['metrics_parse_error'] = True
    relevant = [r for r in records if r['kind'] == kind]
    report.update(http_records=records,
                  cache_observed_requests=sum(r['cache_header'] is not None for r in relevant),
                  explicit_cache_hits=sum(str(r['cache_header']).lower() == 'true' for r in relevant))
    report['passed'] = bool(report.get('usable_evidence') and relevant
                            and all(r['http_success'] for r in relevant)
                            and not report.get('error_type') and not report.get('metrics_parse_error'))
    return kind, report


def preflight(root, config, timeout=120):
    root, config = Path(root).resolve(), Path(config).resolve()
    raw = config.read_bytes()
    cfg = json.loads(raw)
    if cfg.get('execution_version') != 'hermes-parity-v3':
        raise ValueError('Expected separately versioned BC v3 configuration')
    hostname = socket.gethostname()
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if not all(re.fullmatch(r'[A-Za-z0-9_.-]+', v) for v in (hostname, boot)):
        raise ValueError('Unsafe host identity')
    artifact = ROOT / 'outputs/preflight' / ('bc-v3-web-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    artifact.mkdir(parents=True)
    report = {'version': 'bc-v3-real-web-readiness-v1', 'hostname': hostname, 'boot_id': boot,
              'config_sha256': sha(raw), 'config_path': str(config), 'source': str(artifact / 'result.json'),
              'passed': False, 'paid_model_calls': 0, 'checks': {},
              'timing_note': 'Fresh actual handler calls. HTTP client, handler and process wall times are distinct; none measures model provider API latency.'}
    try:
        env, _ = environment(ROOT, 'hermes', config)
        metadata = configure_web(ROOT, env, config)
        settings = json.loads(env['ACL_WEB_SECRETS'])
        if settings['fetch'].get('extract_mode', '').lower() != 'text':
            raise ValueError('Real web readiness requires text extraction; no model-backed Reader mode')
        web = cfg['web']
        expected_search = 'http://' + str(web['search_host']) + ':' + str(web['search_port']) + '/search'
        expected_fetch = web['fetch_base_url'].rstrip('/') + '/fetch'
        if metadata['search_endpoint'] != expected_search or metadata['fetch_endpoint'] != expected_fetch:
            raise ValueError('Resolved web endpoint differs from reviewed configuration')
        report['endpoints'] = {k: endpoint(metadata[k + '_endpoint']) for k in ('search', 'fetch')}
        with ThreadPoolExecutor(max_workers=2) as pool:
            report['checks'] = dict(pool.map(lambda kind: run_check(kind, artifact, env, timeout), ('search', 'fetch')))
        report['config_unchanged_during_checks'] = sha(config.read_bytes()) == sha(raw)
        report['passed'] = report['config_unchanged_during_checks'] and all(c['passed'] for c in report['checks'].values())
    except Exception as error:
        report['error_type'] = type(error).__name__
    # This timestamp is produced only after these new subprocess calls (or an
    # explicit failed check); old evidence is never re-dated or imported.
    report['checked_at_unix'] = time.time()
    report['checked_at_utc'] = datetime.now(timezone.utc).isoformat()
    report['implementation_sha256'] = {name: sha((ROOT / name).read_bytes()) for name in (
        'scripts/preflight_bc_v3_web.py', 'scripts/hermes_tool_bridge.py', 'scripts/local_web.py')}
    destination = root / 'web-readiness' / (hostname + '-' + boot + '.json')
    report['host_readiness_path'] = str(destination)
    atomic(artifact / 'result.json', report)
    atomic(destination, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--config', type=Path, help='Defaults to ROOT/experiment.json')
    parser.add_argument('--timeout', type=float, default=120)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 300:
        parser.error('timeout must be between 1 and 300 seconds')
    report = preflight(args.root, args.config or args.root / 'experiment.json', args.timeout)
    print(json.dumps({k: report[k] for k in ('passed', 'hostname', 'checked_at_utc', 'source', 'host_readiness_path')}))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
