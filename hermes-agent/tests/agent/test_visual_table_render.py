"""Exercise table wrapping through real PDF layout, including page breaks."""
import pytest

pytest.importorskip("reportlab")
fitz = pytest.importorskip("pymupdf")

from plugins.context_engine.visual.render import _blocks_to_pdf_bytes


def block(body, **kwargs):
    return dict(role="tool", header="terminal", body=body, **kwargs)


def render(blocks, height=1600, fit=False):
    data = _blocks_to_pdf_bytes(
        blocks, None, 9, 800, height, 100, fit_to_content_height=fit,
    )
    return fitz.open(stream=data, filetype="pdf")


def table_block(body="Table output.", rows=4):
    return block(body, table_data=[["name", "value"]] + [
        [f"row{i}", str(i)] for i in range(rows)
    ], table_source="terminal")


@pytest.mark.parametrize("separate_blocks", [False, True])
def test_text_recovers_full_width_below_table(separate_blocks):
    sentence = "alpha beta gamma delta epsilon "
    if separate_blocks:
        blocks = [table_block()] + [block(sentence * 10) for _ in range(20)]
    else:
        blocks = [table_block(sentence * 200)]
    with render(blocks, fit=True) as doc:
        words = doc[0].get_text("words")
        cells = [w for w in words if w[4].startswith("row")]
        bottom = max(w[3] for w in cells)
        left = min(w[0] for w in cells)
        prose = [w for w in words if w[4] == "alpha"]
        assert any(w[3] < bottom and w[2] < left for w in prose)
        assert any(w[1] > bottom and w[2] > left for w in prose)
        assert sum(w[4] == "alpha" for p in doc for w in p.get_text("words")) == 200
        assert doc[-1].rect.height - max(w[3] for w in doc[-1].get_text("words")) < 60


def test_long_wrapped_text_splits_across_pages_without_loss():
    with render([table_block("alpha beta gamma delta " * 400)], height=500) as doc:
        assert len(doc) > 1
        words = [w for p in doc for w in p.get_text("words")]
        assert sum(w[4] == "alpha" for w in words) == 400
        assert sum(w[4] == "row3" for w in words) == 1
        assert max(w[2] for w in doc[1].get_text("words")) > doc[1].rect.width * .85


@pytest.mark.parametrize("cols, rows, height", [(8, 4, 1600), (2, 14, 300)])
def test_wide_or_tall_table_remains_in_frame_and_can_split(cols, rows, height):
    data = [[f"col{c}" for c in range(cols)]] + [
        [f"v{r}x{c}" for c in range(cols)] for r in range(rows)
    ]
    with render([block("start", table_data=data, table_source="terminal"),
                 block("aftertable")], height=height) as doc:
        words = [w for p in doc for w in p.get_text("words")]
        for row in data:
            for value in row:
                assert sum(w[4] == value for w in words) == 1
        assert sum(w[4] == "aftertable" for w in words) == 1
        for p in doc:
            assert all(0 <= w[0] < w[2] <= p.rect.width for w in p.get_text("words"))


def test_table_after_image_gets_its_own_wrap(tmp_path):
    from PIL import Image

    path = tmp_path / "image.png"
    Image.new("RGB", (100, 80), "blue").save(path)
    with render([block("imagebody", images=[(str(path), "browser")]),
                 table_block("alpha beta gamma delta " * 120)], fit=True) as doc:
        words = [w for p in doc for w in p.get_text("words")]
        assert sum(w[4] == "alpha" for w in words) == 120
        assert sum(w[4] == "row3" for w in words) == 1
        bottom = max(w[3] for w in words if w[4].startswith("row"))
        assert any(w[4] == "alpha" and w[1] > bottom
                   and w[2] > doc[0].rect.width * .85 for w in words)
