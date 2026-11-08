"""Shared original-download provenance for both repaired harness entrypoints."""
import json
from pathlib import Path


def write_origin_map(row, staged, path):
    sources = row.get('image') or []
    if isinstance(sources, str):
        sources = [sources]
    if len(sources) != len(staged):
        raise ValueError('Image source ledger differs from admitted images')
    images = []
    for source, record in zip(sources, staged):
        if source.startswith(('https://', 'http://')):
            images.append({'path': record['path'], 'sha256': record['sha256'],
                           'origin_url': source, 'kind': 'native_original', 'transformed': False})
    Path(path).write_text(json.dumps({'images': images}, indent=2))
    return str(Path(path).resolve())


def install_hermes_origin_resolver():
    """Reuse the identical DSH bridge argument resolver before the Hermes handler."""
    from hermes_tool_bridge import resolve_origin_arguments
    from tools.registry import registry
    entry = registry.get_entry('image_search')
    if entry is None:
        raise RuntimeError('Hermes image_search must be registered before installing provenance')
    original = entry.handler
    def resolved(arguments, **kwargs):
        arguments, _ = resolve_origin_arguments(arguments)
        return original(arguments, **kwargs)
    entry.handler = resolved
