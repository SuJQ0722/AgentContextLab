"""Explicit attempt-level deadline/retry contract; never retry an incorrect answer."""
VERSION = 'visual-inline-one-hour-retry5-v8'
TIMEOUT_SECONDS = 3600
MAX_TIMEOUT_RETRIES = 5
MAX_ATTEMPTS = 1 + MAX_TIMEOUT_RETRIES


def validate(spec, config):
    for row in (spec, config):
        if row.get('one_hour_retry_version') != VERSION:
            raise ValueError('Explicit one-hour retry version required')
        if type(row.get('timeout_seconds')) is not int or row['timeout_seconds'] != TIMEOUT_SECONDS:
            raise ValueError('Each native attempt must have a 3600-second deadline')
        if type(row.get('max_timeout_retries')) is not int or row['max_timeout_retries'] != MAX_TIMEOUT_RETRIES:
            raise ValueError('Exactly five additional timeout retries must be configured')
    if config.get('max_output_tokens') != 8192:
        raise ValueError('Output token budget must remain 8192')


def retry_decision(result, attempt_number, stopped=False):
    if type(attempt_number) is not int or not 1 <= attempt_number <= MAX_ATTEMPTS:
        raise ValueError('Attempt number outside retry contract')
    if stopped:
        return False, 'dispatch_stopped'
    if result.get('status') != 'timeout':
        return False, 'not_timeout'
    if result.get('native_cleanup_confirmed') is not True or result.get('unconfirmed_child_termination') != []:
        return False, 'cleanup_unconfirmed'
    if attempt_number >= MAX_ATTEMPTS:
        return False, 'timeout_retries_exhausted'
    return True, 'confirmed_timeout'
