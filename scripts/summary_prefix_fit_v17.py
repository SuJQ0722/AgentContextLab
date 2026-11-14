"""Measured summary prefix fitting at the actual source-VERA target.

No fixed16k ceiling; context compatibility is checked by the frozen v17 plan.
"""
import math
from summary_prefix_fit_v14 import boundaries, digest
VERSION = "summary-prefix-fit-v17-source-target"

def fit_prefix(summary, target, native_tokens, full_tokens, measure, max_measurements=10):
    """Return a measured prefix or an explicit failure; mutate no native parts.

    ``measure(prefix)`` must measure the identical full request template/native
    images and persist its own request/usage ledger before returning an integer.
    Search assumes approximately monotonic tokens only for candidate selection;
    acceptance always uses an actual measured count, never interpolation.
    """
    lower, upper = math.ceil(target * .98), math.floor(target * 1.02)
    if not all(type(n) is int and n > 0 for n in (target, native_tokens, full_tokens)):
        raise ValueError('Known positive provider measurements required')
    base = {'version': VERSION, 'source_sha256': digest(summary), 'lower': lower,
            'upper': upper, 'target': target, 'measurements': [], 'new_generation': False}
    if native_tokens > upper:
        return dict(base, status='native_over_budget')
    if lower <= full_tokens <= upper:
        return dict(base, status='matched', summary=summary, provider_prompt_tokens=full_tokens)
    if full_tokens < lower:
        return dict(base, status='undershoot_requires_separate_generation')
    cuts = boundaries(summary)
    lo, hi = 1, len(cuts) - 2  # known empty/full measurements are reused
    for _ in range(max_measurements):
        if lo > hi:
            break
        mid = (lo + hi) // 2
        candidate = summary[:cuts[mid]]
        count = measure(candidate)
        if type(count) is not int or count <= 0:
            return dict(base, status='unknown_usage_stop')
        base['measurements'].append({'characters': cuts[mid], 'sha256': digest(candidate),
                                     'provider_prompt_tokens': count})
        if lower <= count <= upper:
            return dict(base, status='matched', summary=candidate, provider_prompt_tokens=count)
        if count < lower:
            lo = mid + 1
        else:
            hi = mid - 1
    return dict(base, status='no_measured_match')

