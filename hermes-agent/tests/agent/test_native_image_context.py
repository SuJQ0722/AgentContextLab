"""Native image retention through real engine discovery and compression."""
from copy import deepcopy
import pytest
from plugins.context_engine import load_context_engine
from plugins.context_engine.native_images import split_native_images


@pytest.mark.parametrize('name', ['summarize_native', 'sliding_window_native'])
def test_images_survive_text_compression_and_repeat(name, monkeypatch):
    engine = load_context_engine(name)
    assert engine.name == name
    engine.configure({'strategy_config': {'window_size': 1, 'protect_first_n': 1,
                                         'protect_last_n': 2}})
    image = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,ORIGINAL', 'detail': 'high'}}
    messages = [{'role': 'system', 'content': 'fixed instructions'},
                {'role': 'user', 'content': 'original task'}]
    for i in range(40):
        messages.extend([
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': str(i), 'type': 'function',
                'function': {'name': 'lookup', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': str(i), 'content': 'evidence ' * 600},
        ])
        if i == 3:
            messages.append({'role': 'user', 'content': [image]})
    original = deepcopy(messages)
    if name == 'summarize_native':
        def summary(turns, focus):
            assert not split_native_images(turns)[1]
            return 'A compact factual summary.'
        monkeypatch.setattr(engine, '_generate_summary', summary)
    result = engine.compress(messages, 40000)
    assert engine.compression_count == 1
    assert list(split_native_images(result)[1].values()) == [image]
    assert messages == original
    again = engine.compress(result, 40000)
    assert list(split_native_images(again)[1].values()) == [image]
    assert all(not split_native_images([m])[1] for m in again if m['role'] == 'assistant')


def test_noop_preserves_message_identity():
    engine = load_context_engine('sliding_window_native')
    messages = [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'https://example.invalid/image.png'}}]}]
    assert engine.compress(messages) is messages
