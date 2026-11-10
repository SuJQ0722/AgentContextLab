"""Run only non-model hosting IO outside inherited model inference contexts."""
import contextvars


def OriginalHost(*args, **kwargs):
    from verified_hosted_images_v4 import VerifiedImageHost
    return VerifiedImageHost(*args, **kwargs)


class IsolatedVerifiedImageHost:
    def __init__(self, *args, **kwargs):
        self.host = OriginalHost(*args, **kwargs)

    def __call__(self, raw):
        return contextvars.Context().run(self.host, raw)
