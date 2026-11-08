"""Native/returned image coverage through the real PDF renderer, without APIs."""
import base64
import io
import json

import pytest
from PIL import Image

pytest.importorskip("reportlab")
fitz = pytest.importorskip("pymupdf")
from plugins.context_engine.visual import render


def png_url(color="red"):
    data = io.BytesIO()
    Image.new("RGB", (60, 50), color).save(data, format="PNG")
    return "data:image/png;base64," + base64.b64encode(data.getvalue()).decode()


def part(url, **kwargs):
    return {"type": "image_url", "image_url": {"url": url}, **kwargs}


def pdf(blocks, tmp_path, audit):
    return render._blocks_to_pdf_bytes(blocks, None, 10, 800, 2000, 72,
                                      image_cache_dir=str(tmp_path), image_audit=audit)


def test_inline_local_dedup_keeps_every_occurrence_and_cross_message_context(tmp_path):
    url = png_url()
    path = tmp_path / "source.png"
    path.write_bytes(base64.b64decode(url.split(",")[1]))
    messages = [{"role": "tool", "content": [part(str(path), source_occurrence="one"),
                   part(url, source_occurrence="two", source_attachment_id="native:1")]},
                {"role": "user", "content": [part(url, source_occurrence="three")]}]
    blocks = [render._format_message_block(m, msg_index=i) for i, m in enumerate(messages)]
    audit = []
    with fitz.open(stream=pdf(blocks, tmp_path, audit), filetype="pdf") as doc:
        assert len(doc[0].get_image_info()) == 2
    assert [item["source_occurrence"] for item in audit] == ["one", "two", "three"]
    assert [item["status"] for item in audit] == ["rendered", "duplicate_pixels", "rendered"]
    assert audit[1]["source_attachment_id"] == "native:1"


@pytest.mark.parametrize("envelope", ["blocks", "dict", "json", "text-block-json"])
def test_returned_crop_image_is_used_instead_of_parent(envelope):
    crop = png_url("blue")
    payload = {"_multimodal": True, "content": [{"type": "text", "text": "Crop result"}, part(crop)],
               "meta": {"tool": "image_crop", "source": "/parent.png"}}
    content = {"blocks": payload["content"], "dict": payload, "json": json.dumps(payload),
               "text-block-json": [{"type": "text", "text": json.dumps(payload)}]}[envelope]
    mapping = {"crop": ("image_crop", '{"image_path":"/parent.png"}')}
    assert render._extract_images_from_msg({"role": "tool", "tool_call_id": "crop", "content": content}, mapping) == [(crop, "image_crop")]
    assert render._extract_images_from_msg({"role": "assistant", "tool_calls": [{"id": "crop", "function": {
        "name": "image_crop", "arguments": '{"image_path":"/parent.png"}'}}], "content": ""}, mapping) == []


def test_search_returns_all_thumbnails_not_query_or_landing_pages(tmp_path):
    urls = [png_url(color) for color in ("red", "green", "blue", "yellow")]
    payload = {"tool": "image_search", "image_url": "https://example.org/query.png", "results": [
        {"thumbnail_url": url, "title": f"Result {i}", "link": f"https://example.org/page/{i}"}
        for i, url in enumerate(urls)]}
    block = render._format_message_block({"role": "tool", "content": json.dumps(payload)})
    assert [ref for ref, _ in block["images"]] == urls
    audit = []
    with fitz.open(stream=pdf([block], tmp_path, audit), filetype="pdf") as doc:
        assert sum(len(page.get_image_info()) for page in doc) == 4
    assert len(audit) == 4
    assert [item["result_index"] for item in audit] == list(range(4))


def test_native_image_and_full_pipe_table_in_same_message(tmp_path):
    table = "\n".join(["| key | value |", "|---|---|"] + [f"| key{i} | val{i} |" for i in range(35)])
    message = {"role": "tool", "content": [{"type": "text", "text": "Before table\n" + table + "\nAfter table"}, part(png_url())]}
    block = render._format_message_block(message)
    assert len(block["table_data"]) == 36
    assert "Before table" in block["body"] and "After table" in block["body"]
    audit = []
    with fitz.open(stream=pdf([block], tmp_path, audit), filetype="pdf") as doc:
        text = "\n".join(page.get_text() for page in doc)
        assert "key34" in text and "val34" in text
        assert sum(len(page.get_image_info()) for page in doc) == 1
    assert len(audit) == 1


@pytest.mark.parametrize("ref", ["data:image/png;base64,invalid!", "/missing/native-image.png"])
def test_unreadable_evidence_fails_instead_of_silently_disappearing(tmp_path, ref):
    messages = [{"role": "assistant", "tool_calls": [{"id": "read", "function": {"name": "read", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "read", "content": [part(ref)]}]
    with pytest.raises(render.VisualEvidenceError):
        render.render_visual_compression(messages, 0, keep_rounds=0, save_dir=str(tmp_path))


def test_pdf_failure_cannot_fall_back_to_text_with_native_evidence(tmp_path, monkeypatch):
    def failed(*args, **kwargs):
        raise RuntimeError("Rasterizer unavailable")
    monkeypatch.setattr(render, "_pdf_bytes_to_image_b64_list", failed)
    messages = [{"role": "assistant", "tool_calls": [{"id": "read", "function": {"name": "read", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "read", "content": [part(png_url())]}]
    with pytest.raises(render.VisualEvidenceError, match="rasterization"):
        render.render_visual_compression(messages, 0, keep_rounds=0, save_dir=str(tmp_path))
