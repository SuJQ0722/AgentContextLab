"""Keep native image payloads byte-for-byte through text-only compression."""
from copy import deepcopy
import hashlib
import json

IMAGE_TYPES = frozenset({'image_url', 'input_image', 'image'})


def image_key(part):
    return hashlib.sha256(json.dumps(part, sort_keys=True).encode()).hexdigest()


def split_native_images(messages):
    """Detach image blocks before a text compressor can caption or strip them."""
    text_messages = deepcopy(messages)
    images = {}
    for index, message in enumerate(text_messages):
        content = message.get('content')
        if not isinstance(content, list):
            continue
        text = []
        for part in content:
            if isinstance(part, dict) and part.get('type') in IMAGE_TYPES:
                key = image_key(part)
                images.setdefault(key, part)
                text.append({'type': 'text', 'text': f'[Native image {key}; source message {index}]'})
            else:
                text.append(part)
        message['content'] = text
    return text_messages, images


def restore_native_images(messages, images):
    """Attach the same unique images to a surviving user message, never assistant."""
    if not images:
        return messages
    result = deepcopy(messages)
    user = next((m for m in result if m.get('role') == 'user'), None)
    if user is None:
        raise ValueError('Native image retention requires a surviving user task')
    content = user.get('content') or ''
    parts = list(content) if isinstance(content, list) else [{'type': 'text', 'text': content}]
    for key, image in images.items():
        parts.extend([{'type': 'text', 'text': f'[Retained native image {key}]'}, image])
    user['content'] = parts
    return result


class NativeImagesMixin:
    """Retain evidence without sending image bytes to the text summarizer."""

    def compress(self, messages, current_tokens=None, focus_topic=None):
        text, images = split_native_images(messages)
        before = self.compression_count
        compressed = super().compress(text, current_tokens, focus_topic)
        if self.compression_count == before:
            return messages
        self.retained_native_image_ids = list(images)
        return restore_native_images(compressed, images)
