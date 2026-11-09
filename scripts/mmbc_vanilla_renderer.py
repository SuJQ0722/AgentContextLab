"""Process-local text-only rendering ablation; retains original textual table cells."""
import functools
import threading

VERSION = 'mmbc-vanilla-text-history-v1'


def install(render):
    if getattr(render, '_mmbc_vanilla_installed', False):
        return
    formatter = render._format_message_block
    original = render.render_visual_compression
    lock = threading.RLock()

    @functools.wraps(formatter)
    def text_block(*args, **kwargs):
        # The legacy text_only path first strips table cells into a flowable,
        # then drops that flowable. Disable that extraction, retaining the
        # existing textual representation; do not invent a caption or OCR.
        with lock:
            detect = render._detect_table
            render._detect_table = lambda value: None
            try:
                result = formatter(*args, **kwargs)
            finally:
                render._detect_table = detect
        if result.get('table_data') is not None:
            raise RuntimeError('Vanilla must retain tables as original text')
        return result

    @functools.wraps(original)
    def render_text(*args, **kwargs):
        if kwargs.get('text_only') is not True:
            raise ValueError('Vanilla ablation requires explicit text_only=True')
        result = original(*args, **kwargs)
        stats = kwargs.get('stats')
        if stats is not None:
            if stats.get('rendered_source_images', 0) != 0:
                raise RuntimeError('Source image was rendered in vanilla condition')
            stats.update(ablation_version=VERSION,
                         visual_evidence_intentionally_omitted=True,
                         omitted_source_image_occurrences=stats.get('source_image_input_occurrences'),
                         table_representation='Original text retained; no structured table flowable',
                         generated_captions=False)
        return result

    render._format_message_block = text_block
    render.render_visual_compression = render_text
    render._mmbc_vanilla_installed = True
