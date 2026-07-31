"""FinSearchComp judge — uses per-question judge_system_prompt + judge_prompt_template."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any


def parse_args():
    p = argparse.ArgumentParser(description="Judge FinSearchComp predictions")
    p.add_argument("--pred-root", required=True, help="Root dir containing conv/ with prediction JSONs")
    p.add_argument("--data-path", required=True, help="Path to finsearchcomp questions.jsonl")
    p.add_argument("--judge-model", default="gpt-5-mini")
    p.add_argument("--judge-base-url", default="https://tokenhub.sensetime.com/v1")
    p.add_argument("--judge-api-key", default=None)
    p.add_argument("--num-workers", type=int, default=10)
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--timeout-seconds", type=float, default=60)
    p.add_argument("--max-tokens", type=int, default=2048)
    p.add_argument("--force", action="store_true")
    p.add_argument("--include-failed", action="store_true")
    return p.parse_args()


def load_questions(data_path: str) -> dict[str, dict]:
    qs = {}
    with open(data_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            qid = item.get("id") or item.get("question_id") or item.get("prompt_id", "")
            qs[qid] = item
    return qs


def load_predictions(conv_dir: Path) -> list[dict]:
    records = []
    if not conv_dir.is_dir():
        return records
    for path in sorted(conv_dir.rglob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(raw, dict):
            continue
        qid = str(raw.get("question_id", path.stem))
        pred = str(raw.get("model_response") or raw.get("prediction") or raw.get("final_answer") or "")
        records.append({
            "path": str(path),
            "question_id": qid,
            "run_id": str(raw.get("run_id", qid)),
            "repeat_index": raw.get("repeat_index"),
            "pred": pred,
            "status": str(raw.get("status", "unknown")),
            "type": str(raw.get("type", "")),
            "raw": raw,
        })
    return records


def build_judge_messages(question_data: dict, pred: str) -> list[dict]:
    system_prompt = question_data.get("judge_system_prompt", "")
    template = question_data.get("judge_prompt_template", "")

    fill = {
        "prompt": question_data.get("question", question_data.get("prompt", "")),
        "response_reference": question_data.get("answer", question_data.get("response_reference", "")),
        "response": pred,
    }
    gt = question_data.get("ground_truth")
    if gt is not None:
        fill["ground_truth"] = gt if isinstance(gt, str) else json.dumps(gt, ensure_ascii=False)

    user_content = template.format(**fill) if template else (
        f"Question: {fill['prompt']}\nAnswer: {fill['response_reference']}\nPrediction: {pred}"
    )

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_content})
    return messages


def extract_score(text: str) -> float | None:
    m = re.search(r'\{\s*"answer_score"\s*:\s*(\d+)\s*\}', text)
    if m:
        return 1.0 if int(m.group(1)) == 1 else 0.0
    m = re.search(r'"answer_score"\s*:\s*(\d+)', text)
    if m:
        return 1.0 if int(m.group(1)) == 1 else 0.0
    m = re.search(r'\{\s*"score"\s*:\s*(\d+)\s*\}', text)
    if m:
        return 1.0 if int(m.group(1)) == 1 else 0.0
    return None


def judge_one(client, model: str, messages: list[dict], max_tokens: int, timeout: float, max_retries: int) -> dict:
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                max_completion_tokens=max_tokens,
                temperature=0.0,
            )
            content = resp.choices[0].message.content or ""
            score = extract_score(content)
            return {"content": content, "score": score}
        except Exception as e:
            last_exc = e
            time.sleep(min(30.0, 2.0 ** attempt))
    raise last_exc


def main():
    args = parse_args()
    api_key = args.judge_api_key or os.environ.get("JUDGE_API_KEY", "")
    if not api_key:
        print("ERROR: set JUDGE_API_KEY or --judge-api-key", file=sys.stderr)
        sys.exit(1)

    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=args.judge_base_url, timeout=args.timeout_seconds)

    questions = load_questions(args.data_path)
    print(f"Loaded {len(questions)} questions from {args.data_path}")

    pred_root = Path(args.pred_root)
    conv_dir = pred_root / "conv"
    predictions = load_predictions(conv_dir)
    print(f"Loaded {len(predictions)} predictions from {conv_dir}")

    output_dir = pred_root / "judge_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = pred_root / "judge_summary.jsonl"
    metrics_path = pred_root / "judge_metrics.json"

    pending = []
    for rec in predictions:
        qid = rec["question_id"]
        out_path = output_dir / f"{rec['run_id']}_{rec.get('repeat_index', 1)}.json"
        if out_path.exists() and not args.force:
            continue
        if rec["status"] != "success" and not args.include_failed:
            result = {
                "question_id": qid,
                "run_id": rec["run_id"],
                "repeat_index": rec.get("repeat_index"),
                "status": "skipped_infer_failed",
                "score": None,
                "pred_status": rec["status"],
                "prediction": rec["pred"],
            }
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            continue
        if qid not in questions:
            print(f"WARNING: question {qid} not found in data, skipping")
            continue
        pending.append((rec, questions[qid], out_path))

    print(f"Pending judge: {len(pending)}")
    results_all = []

    def _do_judge(item):
        rec, qdata, out_path = item
        qid = rec["question_id"]

        if not rec["pred"].strip():
            result = {
                "question_id": qid, "run_id": rec["run_id"],
                "repeat_index": rec.get("repeat_index"),
                "status": "skipped_empty", "score": 0.0,
                "pred_status": rec["status"], "prediction": rec["pred"],
                "question": qdata.get("question", ""), "answer": qdata.get("answer", ""),
            }
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result

        messages = build_judge_messages(qdata, rec["pred"])
        judged = judge_one(client, args.judge_model, messages, args.max_tokens, args.timeout_seconds, args.max_retries)
        result = {
            "question_id": qid, "run_id": rec["run_id"],
            "repeat_index": rec.get("repeat_index"),
            "status": "judged", "score": judged["score"],
            "pred_status": rec["status"], "prediction": rec["pred"],
            "question": qdata.get("question", ""), "answer": qdata.get("answer", ""),
            "label": qdata.get("label", ""),
            "judge_raw_response": judged["content"],
        }
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.num_workers) as executor:
        future_map = {executor.submit(_do_judge, item): item for item in pending}
        done_count = 0
        for future in concurrent.futures.as_completed(future_map):
            done_count += 1
            item = future_map[future]
            qid = item[0]["question_id"]
            try:
                result = future.result()
                results_all.append(result)
                print(f"[{done_count}/{len(pending)}] {qid}: {result.get('status')} score={result.get('score')}")
            except Exception as e:
                err_result = {
                    "question_id": qid, "run_id": item[0]["run_id"],
                    "status": "judge_failed", "score": None, "error": str(e),
                }
                item[2].write_text(json.dumps(err_result, ensure_ascii=False, indent=2), encoding="utf-8")
                results_all.append(err_result)
                print(f"[{done_count}/{len(pending)}] {qid}: FAILED {e}")

    # Also load previously judged results
    all_results = []
    for p in sorted(output_dir.rglob("*.json")):
        try:
            all_results.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass

    # Write summary
    with open(summary_path, "w", encoding="utf-8") as f:
        for r in all_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Compute metrics
    scored = [r for r in all_results if r.get("score") is not None]
    correct = sum(1 for r in scored if r.get("score") == 1)
    total = len(all_results)

    by_label = {}
    for r in scored:
        label = r.get("label", "unknown")
        by_label.setdefault(label, {"correct": 0, "total": 0})
        by_label[label]["total"] += 1
        if r.get("score") == 1:
            by_label[label]["correct"] += 1

    metrics = {
        "total": total,
        "scored": len(scored),
        "correct": correct,
        "accuracy": round(correct / len(scored), 4) if scored else 0,
        "skipped": total - len(scored),
        "by_label": {k: {**v, "accuracy": round(v["correct"] / v["total"], 4) if v["total"] else 0} for k, v in sorted(by_label.items())},
    }
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n=== Metrics ===")
    print(f"Total: {total}, Scored: {len(scored)}, Correct: {correct}, Accuracy: {metrics['accuracy']}")
    for label, v in sorted(by_label.items()):
        acc = round(v["correct"] / v["total"], 4) if v["total"] else 0
        print(f"  {label}: {v['correct']}/{v['total']} = {acc}")


if __name__ == "__main__":
    main()
