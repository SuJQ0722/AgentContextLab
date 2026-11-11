"""Retirement boundary for removed compressed-context image hosting.

Historical import paths stay importable for plan readers, but must never replay
an upload or substitute a hosted URL. Use inline_visual_transport_v1 for Hermes
and dsh_inline_transport_bridge_v1 for DSH. Information-loss evaluation already
has a byte-verified inline client in info_loss_phase4.
"""


class CompressionHostingRemoved(RuntimeError):
    pass


def removed(*args, **kwargs):
    raise CompressionHostingRemoved(
        'Compressed-context image hosting has been removed. Use inline data:image '
        'payloads; historical hosted configurations cannot be resumed.'
    )


class RemovedImageHost:
    """Import compatibility only: no credentials, cache reads, or network IO."""

    def __init__(self, *args, **kwargs):
        pass

    ensure = removed
    __call__ = removed
