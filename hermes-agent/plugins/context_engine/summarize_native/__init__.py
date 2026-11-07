"""Structured text summarization with original native images retained."""
from plugins.context_engine.native_images import NativeImagesMixin
from plugins.context_engine.summarize import SummarizeEngine


class SummarizeNativeEngine(NativeImagesMixin, SummarizeEngine):
    @property
    def name(self):
        return 'summarize_native'


def register(ctx):
    ctx.register_context_engine(SummarizeNativeEngine())
