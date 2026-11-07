#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROJECTS_ROOT = ROOT.parents[1]
DEFAULT_MM_INPUT = PROJECTS_ROOT / "MM-BrowseComp" / "data" / "MMBrowseComp_400.jsonl"
DEFAULT_BCV3_INPUT = ROOT / "data" / "bc_v3" / "data" / "train.jsonl"
BCV3_PASSPHRASE = "A_Visual_Vertical_Verifiable_Benchmark_for_Multimodal_Browsing_Agents"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
            rows.append(row)
    return rows


def _write_jsonl(rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _derive_repeating_key(password: str, length: int) -> bytes:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return digest * (length // len(digest)) + digest[: length % len(digest)]


def _decrypt_mmbc(ciphertext_b64: str, password: str) -> str:
    encrypted = base64.b64decode(ciphertext_b64)
    key = _derive_repeating_key(password, len(encrypted))
    return bytes(a ^ b for a, b in zip(encrypted, key)).decode("utf-8")


def _decrypt_bcv3(encrypted_json: str, key: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    enc = json.loads(encrypted_json)
    iv = base64.b64decode(enc["iv"])
    ciphertext = base64.b64decode(enc["ciphertext"])
    tag = base64.b64decode(enc["tag"])
    return AESGCM(key).decrypt(iv, ciphertext + tag, None).decode("utf-8")


def _json_loads_or_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def convert_mmbrowsecomp(input_path: Path) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for row in _read_jsonl(input_path):
        canary = str(row["canary"])
        images = [str(item) for item in row.get("images") or [] if str(item).strip()]
        checklist = [
            _decrypt_mmbc(str(item), canary)
            for item in row.get("checklist") or []
        ]
        converted.append(
            {
                "id": f"mmbc_{int(row['id']):03d}" if str(row.get("id", "")).isdigit() else f"mmbc_{row.get('id')}",
                "question": _decrypt_mmbc(str(row["question"]), canary),
                "answer": _decrypt_mmbc(str(row["answer"]), canary),
                "type": str(row.get("category") or "multimodal"),
                "image": images,
                "dataset": "mmbrowsecomp",
                "original_id": row.get("id"),
                "category": row.get("category", ""),
                "subtask": row.get("subtask", ""),
                "level": row.get("level", ""),
                "source": row.get("source", []),
                "checklist": checklist,
                "checklist_property": row.get("checklist_property", ""),
                "canary": canary,
            }
        )
    return converted


def convert_bcv3(input_path: Path) -> list[dict[str, Any]]:
    key = hashlib.sha256(BCV3_PASSPHRASE.encode("utf-8")).digest()
    repo_root = input_path.parents[1]
    converted: list[dict[str, Any]] = []
    for row in _read_jsonl(input_path):
        image_paths = _json_loads_or_value(row.get("image_paths") or "[]")
        if not isinstance(image_paths, list):
            image_paths = [row.get("image")] if row.get("image") else []
        images = [
            str((repo_root / str(item)).resolve())
            for item in image_paths
            if str(item).strip()
        ]
        category = str(row.get("category") or "")
        sub_category = str(row.get("sub_category") or "")
        metadata = _json_loads_or_value(row.get("metadata") or "{}")
        sub_goals = _json_loads_or_value(row.get("sub_goals") or "[]")
        converted.append(
            {
                "id": row.get("id"),
                "question": _decrypt_bcv3(str(row["encrypted_question"]), key),
                "answer": _decrypt_bcv3(str(row["encrypted_answer"]), key),
                "type": f"{category}/{sub_category}" if sub_category else category,
                "image": images,
                "dataset": "bc_v3",
                "category": category,
                "sub_category": sub_category,
                "metadata": metadata,
                "sub_goals": sub_goals,
            }
        )
    return converted


def write_dataset(rows: list[dict[str, Any]], output_dir: Path) -> None:
    _write_jsonl(rows, output_dir / "questions.jsonl")
    _write_jsonl(rows, output_dir / f"questions_{len(rows)}.jsonl")


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert visual BrowseComp-style benchmarks to Browsecomp_eval JSONL.")
    parser.add_argument("--mm-input", type=Path, default=DEFAULT_MM_INPUT)
    parser.add_argument("--bcv3-input", type=Path, default=DEFAULT_BCV3_INPUT)
    parser.add_argument("--mmbc-output-dir", type=Path, default=ROOT / "data" / "mmbrowsecomp")
    parser.add_argument("--bcv3-output-dir", type=Path, default=ROOT / "data" / "bc_v3")
    args = parser.parse_args()

    mmbc_rows = convert_mmbrowsecomp(args.mm_input)
    bcv3_rows = convert_bcv3(args.bcv3_input)

    write_dataset(mmbc_rows, args.mmbc_output_dir)
    write_dataset(bcv3_rows, args.bcv3_output_dir)

    print(f"wrote {len(mmbc_rows)} rows to {args.mmbc_output_dir}")
    print(f"wrote {len(bcv3_rows)} rows to {args.bcv3_output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
