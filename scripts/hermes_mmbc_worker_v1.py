#!/usr/bin/env python3
"""MMBC native Hermes: same reviewed engines/tools, fixed original input image bytes."""
import hermes_bc_worker_v3 as native
from mmbc_input_images import stage_images


def main():
    original = native.stage_images
    native.stage_images = stage_images
    try:
        native.main()
    finally:
        native.stage_images = original


if __name__ == '__main__': main()
