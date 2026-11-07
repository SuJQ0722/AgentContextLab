"""Sliding tool-result window with original native images retained."""
from plugins.context_engine.native_images import NativeImagesMixin
from plugins.context_engine.sliding_window import SlidingWindowEngine


class SlidingWindowNativeEngine(NativeImagesMixin, SlidingWindowEngine):
    @property
    def name(self):
        return 'sliding_window_native'


def register(ctx):
    ctx.register_context_engine(SlidingWindowNativeEngine())
