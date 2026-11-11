"""Independent controlled continuation with exact frozen input-byte reuse."""
from unittest.mock import patch
import capture_multimodal_prefix_v5 as capture
import controlled_visual_inline_worker_v4 as parent
from controlled_frozen_input_reuse_v1 import stage


def main():
    original = capture.load_images
    with patch.object(capture, 'load_images', lambda row, out: stage(row, out, original)):
        parent.main()


if __name__ == '__main__': main()
