"""Accept the user's exact returned DeepSeek model name without changing routes.

Existing V8 protocol and grades remain immutable. A separate protocol sidecar
binds this narrow validation extension, so either V8 or V9 watcher may resume
its own existing private output without invalidating historical grades.
"""
from pathlib import Path
from unittest.mock import patch

import judge_inline_retry5_v8 as v8

VERSION = 'judge-inline-model-alias-v9'
CANONICAL = 'deepseek-v4.1-flash-1017'
ACCEPTED_RETURNED_MODELS = (*v8.ROUTES, 'deepseek-v4-1-flash-261017', CANONICAL)
_original_prepare = v8.prepare


def prepare(root, out):
    cells, cfg = _original_prepare(root, out)
    v8.parent.immutable(Path(out) / 'model-alias-protocol.json', {
        'version': VERSION,
        'source_sha256': v8.parent.sha(__file__),
        'base_protocol_sha256': v8.parent.sha(Path(out) / 'protocol.json'),
        'accepted_returned_models': list(ACCEPTED_RETURNED_MODELS),
        'request_routes': list(v8.ROUTES),
        'historical_grades': 'Preserve unchanged; never automatically regrade or overwrite',
        'raw_returned_model_and_usage': 'Preserve unchanged',
    })
    return cells, cfg


def grade_bound(candidate, cfg, env):
    directory = Path(candidate['directory'])
    existing = directory / 'grade.json'
    if existing.exists():
        return v8.parent.read(existing)
    binding = candidate['binding']
    if v8.parent.sha(binding['result_path']) != binding['result_sha256']:
        raise ValueError('Prediction changed before judge')
    for path, digest in binding['gold_sources_sha256'].items():
        if v8.parent.sha(path) != digest:
            raise ValueError('Gold changed before judge')
    result = v8.parent.base.bc.grade(
        candidate, cfg, env, opener=v8.route_opener(directory))
    if result.get('status') == 'already_claimed':
        return result
    if result.get('status') == 'scored' and result.get('api_calls'):
        if result.get('finish_reason') != 'stop':
            result.update(status='incomplete_judge_response', score=None)
        elif result.get('returned_model') not in ACCEPTED_RETURNED_MODELS:
            result.update(status='judge_model_identity_unverified', score=None)
    attempts = list((directory / 'http-attempts').glob('attempt_*/started.json'))
    result.update(
        version=VERSION, api_calls=len(attempts), judge_http_attempts=len(attempts),
        model_alias_validator_sha256=v8.parent.sha(__file__),
        inherited_judge_protocol='Hermes answer-equivalence + numeric JSON score 0/1')
    v8.parent.atomic(existing, result)
    return result


def main():
    with patch.object(v8, 'prepare', prepare), patch.object(v8, 'grade_bound', grade_bound):
        v8.main()


if __name__ == '__main__':
    main()
