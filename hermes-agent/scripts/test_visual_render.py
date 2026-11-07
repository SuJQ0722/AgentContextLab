"""Test visual rendering and verify the PDF->PNG visual-compression pipeline.

Produces 8 output folders under output/visual_render_test/:
  1. layout_1d_scale075       — 1d layout, history_scale=0.75
  2. layout_plain_scale075    — plain layout, history_scale=0.75
  3. layout_highlight_scale075 — highlight layout, history_scale=0.75
  4. highlight_scale0          — highlight, no history image
  5. highlight_scale025        — highlight, 4x downsample
  6. highlight_scale050        — highlight, 2x downsample
  7. highlight_scale0125       — highlight, 8x downsample
  8. highlight_scale100        — highlight, original (no downsample)
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.context_engine.visual.render import (
    _blocks_to_pdf_bytes,
    _pdf_bytes_to_image_b64_list,
    render_visual_compression,
)

OUTPUT_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "visual_render_test")

CONFIGS = [
    # Table 3: Layout ablation (fixed scale=0.75)
    {"name": "plain_no_header",     "layout": "plain_no_header",   "history_scale": 0.75},
    {"name": "plain",               "layout": "plain",             "history_scale": 0.75},
    {"name": "highlight",           "layout": "highlight",         "history_scale": 0.75},
    {"name": "highlight_no_wrap",   "layout": "highlight_no_wrap", "history_scale": 0.75},
    # Table 2: History downsample ablation (fixed layout=highlight)
    {"name": "scale_0_no_history",  "layout": "highlight", "history_scale": 0.0},
    {"name": "scale_0125_8x",       "layout": "highlight", "history_scale": 0.125},
    {"name": "scale_025_4x",        "layout": "highlight", "history_scale": 0.25},
    {"name": "scale_050_2x",        "layout": "highlight", "history_scale": 0.5},
    {"name": "scale_100_original",  "layout": "highlight", "history_scale": 1.0},
]


def _synthetic_messages():
    messages = [
        {"role": "system", "content": "You are a helpful research assistant."},
        {"role": "user", "content": "Find details about a thesis dedication and cite web evidence."},
    ]
    for i in range(8):
        call_id = f"call_{i}"
        messages.append({
            "role": "assistant",
            "content": f"I will search source {i}.",
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {
                    "name": "web_search",
                    "arguments": json.dumps({"query": f"example thesis dedication source {i}"}),
                },
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "content": (
                f"Result {i}: https://example.edu/theses/{i} contains title, author, "
                "dedication, and several long lines of evidence for wrapping. " * 4
            ),
        })
    messages.append({"role": "user", "content": "Return the final answer clearly."})
    return messages


def _load_messages(path):
    if not path:
        return _synthetic_messages(), "synthetic trajectory"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    messages = data.get("history") or data.get("messages")
    if not isinstance(messages, list):
        raise SystemExit(f"{path} does not contain a history/messages list")
    return messages, path


def _assert_pdf_pipeline(save_dir):
    """Fail fast if reportlab/pdf2image/poppler are unavailable.

    render_visual_compression intentionally falls back to PIL for production
    robustness. This smoke check is stricter: it exercises the exact PDF path
    so environment regressions do not pass unnoticed.
    """
    import shutil
    from PIL import Image, ImageStat

    missing = [exe for exe in ("pdfinfo", "pdftoppm") if shutil.which(exe) is None]
    if missing:
        raise RuntimeError(f"missing poppler executable(s): {', '.join(missing)}")

    blocks = [
        {
            "role": "user",
            "header": "USER",
            "body": "PDF pipeline smoke test with URL https://example.edu/a/b?c=d and CJK 中文.",
        },
        {
            "role": "assistant",
            "header": "ASSISTANT",
            "body": "This must render through reportlab and pdf2image, not the PIL fallback.",
        },
    ]
    pdf_bytes = _blocks_to_pdf_bytes(
        blocks,
        font_path=None,
        font_size=8,
        page_width=1024,
        max_image_height=4096,
        dpi=72,
        layout="highlight",
    )
    if not pdf_bytes.startswith(b"%PDF"):
        raise RuntimeError("reportlab did not return PDF bytes")

    images = _pdf_bytes_to_image_b64_list(
        pdf_bytes,
        dpi=72,
        save_dir=save_dir,
        save_prefix="_pipeline_smoke",
    )
    if not images:
        raise RuntimeError("pdf2image returned no images")

    png_path = os.path.join(save_dir, "_pipeline_smoke_001.png")
    if not os.path.isfile(png_path) or os.path.getsize(png_path) <= 0:
        raise RuntimeError("PDF pipeline did not write _pipeline_smoke_001.png")
    with Image.open(png_path) as img:
        extrema = ImageStat.Stat(img.convert("L")).extrema[0]
    if extrema[0] == extrema[1]:
        raise RuntimeError("_pipeline_smoke_001.png is blank")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", help="History/conv JSON to render. Defaults to a synthetic trajectory.")
    parser.add_argument("--output-base", default=OUTPUT_BASE, help="Directory for rendered visual outputs.")
    parser.add_argument("--allow-fallback", action="store_true", help="Skip strict PDF->PNG dependency smoke check.")
    args = parser.parse_args(argv)

    messages, source = _load_messages(args.trajectory)
    print(f"Loaded {len(messages)} messages from {source}")

    os.makedirs(args.output_base, exist_ok=True)
    if not args.allow_fallback:
        print("Checking reportlab/pdf2image/poppler pipeline...")
        _assert_pdf_pipeline(args.output_base)
        print("  PDF pipeline OK")

    for cfg in CONFIGS:
        name = cfg["name"]
        save_dir = os.path.join(args.output_base, name)
        os.makedirs(save_dir, exist_ok=True)

        print(f"\n{'='*60}")
        print(f"Rendering: {name} (layout={cfg['layout']}, history_scale={cfg['history_scale']})")
        print(f"Output dir: {save_dir}")

        result = render_visual_compression(
            messages,
            head_end=1,
            image_width=1024,
            font_size=8,
            max_image_height=4096,
            dpi=72,
            layout=cfg["layout"],
            history_scale=cfg["history_scale"],
            keep_rounds=1,
            recent_rounds=5,
            save_dir=save_dir,
            compact_count=0,
        )

        n_images = 0
        for m in result:
            content = m.get("content")
            if isinstance(content, list):
                n_images += sum(1 for p in content if isinstance(p, dict) and p.get("type") == "image_url")

        print(f"  Result: {len(result)} messages, {n_images} image(s)")
        pngs = [f for f in os.listdir(save_dir) if f.endswith(".png")]
        pdfs = [f for f in os.listdir(save_dir) if f.endswith(".pdf")]
        print(f"  Files: {len(pngs)} PNG, {len(pdfs)} PDF")
        for f in sorted(pngs + pdfs):
            fpath = os.path.join(save_dir, f)
            size_kb = os.path.getsize(fpath) / 1024
            print(f"    {f} ({size_kb:.1f} KB)")

    print(f"\n{'='*60}")
    print(f"All outputs saved to: {args.output_base}")


if __name__ == "__main__":
    main()
