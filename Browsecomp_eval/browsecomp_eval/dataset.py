from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class DatasetItem:
    question_id: str
    question: str
    answer: str
    type: str
    source_line: int
    image: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunSpec:
    question_id: str
    run_id: str
    repeat_index: int
    item: DatasetItem


def safe_id(value: str) -> str:
    cleaned = _SAFE_ID_RE.sub("_", str(value).strip()).strip("._-")
    return cleaned or "unknown"


def _coerce_item(raw: dict, source_line: int) -> DatasetItem:
    missing = [key for key in ("question", "answer", "type") if key not in raw]
    if missing:
        raise ValueError(f"line {source_line}: missing required field(s): {', '.join(missing)}")

    question = str(raw["question"]).strip()
    if not question:
        raise ValueError(f"line {source_line}: question must not be empty")

    if "id" in raw and str(raw["id"]).strip():
        question_id = safe_id(str(raw["id"]))
    else:
        question_id = f"q_{source_line:03d}"

    return DatasetItem(
        question_id=question_id,
        question=question,
        answer=str(raw["answer"]),
        type=str(raw["type"]),
        source_line=source_line,
        image=_coerce_image(raw.get("image")),
    )


def _coerce_image(value: object) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ()
        if stripped.startswith("["):
            try:
                return _coerce_image(json.loads(stripped))
            except json.JSONDecodeError:
                pass
        return (stripped,)
    if isinstance(value, (list, tuple)):
        images: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                images.append(text)
        return tuple(images)
    text = str(value).strip()
    return (text,) if text else ()


def load_dataset(path: str | Path) -> List[DatasetItem]:
    data_path = Path(path)
    if not data_path.is_file():
        raise FileNotFoundError(f"data file not found: {data_path}")

    if data_path.suffix.lower() == ".json":
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"{data_path} must contain a JSON array")
        return [_coerce_item(row, idx) for idx, row in enumerate(payload, start=1)]

    items: list[DatasetItem] = []
    with data_path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            if not line.strip():
                continue
            raw = json.loads(line)
            if not isinstance(raw, dict):
                raise ValueError(f"line {idx}: each JSONL row must be an object")
            items.append(_coerce_item(raw, idx))
    return items


def expand_repeats(items: Iterable[DatasetItem], repeats: int) -> list[RunSpec]:
    if repeats < 1:
        raise ValueError("repeats must be >= 1")

    runs: list[RunSpec] = []
    for item in items:
        for repeat_index in range(1, repeats + 1):
            run_id = item.question_id
            runs.append(
                RunSpec(
                    question_id=item.question_id,
                    run_id=run_id,
                    repeat_index=repeat_index,
                    item=item,
                )
            )
    return runs
