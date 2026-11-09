#!/usr/bin/env python3
"""Vanilla MMBC: same Hermes loop and pixels, omit evidence only in rendered history."""
import hermes_bc_worker_v3 as native
from mmbc_input_images import stage_images
from mmbc_vanilla_renderer import install


def main():
    original_stage, original_configure = native.stage_images, native.configure_engine

    def configure(engine, strategy, config):
        if strategy != 'visual' or config.get('strategy_config', {}).get('text_only') is not True:
            raise ValueError('Vanilla requires explicit visual text-only policy')
        original_configure(engine, strategy, config)
        if engine._text_only is not True:
            raise ValueError('Native engine did not apply text-only rendering')
        from plugins.context_engine.visual import render
        install(render)

    native.stage_images, native.configure_engine = stage_images, configure
    try:
        native.main()
    finally:
        native.stage_images, native.configure_engine = original_stage, original_configure


if __name__ == '__main__': main()
