"""Versioned DSH image transport configuration; does not promise provider acceptance.

Use only in new plans. These are the existing native source-admission ceilings,
not new rendering dimensions. Keep the provider aggregate payload guard so an
oversized request fails rather than silently resizing/offloading evidence.
"""
import json

IMAGE_PRESERVATION_VERSION = 'original-image-bytes-v2'
MAX_SOURCE_PIXELS = 64_000_000
MAX_SOURCE_DIMENSION = 65_535
MAX_SOURCE_BYTES = 50 * 1024 * 1024
MAX_REQUEST_BYTES = 20 * 1024 * 1024


def preservation_patches(env):
    """Return complete replacement config objects (Cordis does not deep-merge)."""
    provider = {
        'apiKeyEnv': 'TOKENHUB_API_KEY', 'api': 'openai-completions',
        'baseURL': env['TOKENHUB_BASE_URL'],
        'requestImagePixelBudget': MAX_SOURCE_PIXELS,
        'requestImageMaxBytes': MAX_SOURCE_BYTES,
        'maxRequestImageBytes': MAX_REQUEST_BYTES,
        'models': [{
            'id': env['ACL_MODEL'], 'input': json.loads(env['ACL_INPUT_MODALITIES']),
            'contextWindow': int(env['ACL_CONTEXT_WINDOW']),
            'maxTokens': int(env['ACL_MAX_OUTPUT_TOKENS']),
        }],
    }
    return [
        {'id': 'attachment-local', 'config': {
            'normalizedImageMaxPixels': MAX_SOURCE_PIXELS,
            'normalizedImageMaxDimension': MAX_SOURCE_DIMENSION,
            'normalizedImageMaxBytes': MAX_SOURCE_BYTES,
        }},
        {'id': 'llm-pi-ai', 'config': {'providers': {'tokenhub': provider}}},
    ]
