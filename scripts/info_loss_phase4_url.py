"""Retired URL evaluation. Use info_loss_phase4's byte-verified inline client.

Old manifests and paid-attempt records are historical data, never resumed here.
"""
import hashlib
import io
from PIL import Image
from compression_inline_only import removed


def pixel_sha(data):
    """Pure historical pixel identity helper; performs no IO or hosting."""
    with Image.open(io.BytesIO(data)) as image:
        rgba = image.convert('RGBA')
        return hashlib.sha256(str(rgba.size).encode() + b'\0' + rgba.tobytes()).hexdigest(), list(rgba.size)


main = removed

if __name__ == '__main__':
    main()
