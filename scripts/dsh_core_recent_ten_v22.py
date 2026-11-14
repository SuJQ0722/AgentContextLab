"""New-version DSH adapter; legacy DSH source and frozen campaigns stay unchanged."""
from core_recent_ten_transport_v22 import transform as _transform, install as _install

VERSION = 'dsh-core-page-caps-then-recent-ten-v22'


def transform(body, *, policy, **kwargs):
    return _transform(body, policy=policy, harness='dsh', **kwargs)


def install(out, *, policy, **kwargs):
    return _install(out, policy=policy, harness='dsh', **kwargs)
