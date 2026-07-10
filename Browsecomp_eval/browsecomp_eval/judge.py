from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


INCORRECT_SCORE = 0.0
CORRECT_SCORE = 1.0


@dataclass(frozen=True)
class JudgeClientConfig:
    api_key: str
    base_url: str
    model: str
    provider: str
    api_version: str
    timeout_seconds: float
    max_retries: int
    max_tokens: int
    temperature: float
    top_p: float
    token_param: str
    use_json_schema: bool


@dataclass(frozen=True)
class JudgeRunConfig:
    conv_dir: Path
    output_dir: Path
    summary_path: Path
    metrics_path: Path
    num_workers: int
    force: bool
    include_failed: bool


@dataclass(frozen=True)
class PredictionRecord:
    path: Path
    question_id: str
    run_id: str
    repeat_index: int | None
    question: str
    answer: Any
    pred: str
    pred_status: str
    type: str
    token_usage: dict[str, Any]
    raw: dict[str, Any]


class JudgeClient:
    def __init__(self, config: JudgeClientConfig):
        self.config = config
        self._sdk_client: Any | None = None

    def judge(self, record: PredictionRecord) -> dict[str, Any]:
        prompt = build_judge_prompt(record.question, record.pred, record.answer)
        request_payload = self._build_payload(prompt)
        raw_response = self._post_with_retries(request_payload)
        content = extract_message_content(raw_response)
        score = analyse_judgemodel_res(content)
        if score is None:
            raise ValueError(f"judge response did not contain score 0/1: {content[:500]}")
        return {
            "score": score,
            "judge_reason": extract_judge_reason(content),
            "judge_raw_response": content,
            "judge_response": serialize_response(raw_response),
        }

    def _build_payload(self, prompt: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        }
                    ],
                }
            ],
            self.config.token_param: self.config.max_tokens,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
        }
        if self.config.use_json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "judge_result",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "reason": {"type": "string"},
                            "score": {"type": "integer", "enum": [0, 1]},
                        },
                        "required": ["reason", "score"],
                        "additionalProperties": False,
                    },
                },
            }
        return payload

    def _post_with_retries(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(1, max(1, self.config.max_retries) + 1):
            try:
                return self._post(payload)
            except Exception as exc:
                last_exc = exc
                if attempt >= self.config.max_retries:
                    break
                time.sleep(min(30.0, 2.0 ** (attempt - 1)))
        assert last_exc is not None
        raise last_exc

    def _post(self, payload: dict[str, Any]) -> Any:
        return self._client().chat.completions.create(**payload)

    def _client(self) -> Any:
        if self._sdk_client is not None:
            return self._sdk_client
        try:
            from openai import AzureOpenAI, OpenAI
        except ImportError as exc:
            raise RuntimeError("missing package: openai. Install it with `python -m pip install openai`.") from exc

        if self.config.provider == "azure":
            self._sdk_client = AzureOpenAI(
                api_version=self.config.api_version,
                azure_endpoint=self.config.base_url,
                api_key=self.config.api_key,
                timeout=self.config.timeout_seconds,
                max_retries=0,
            )
        else:
            self._sdk_client = OpenAI(
                base_url=self.config.base_url,
                api_key=self.config.api_key,
                timeout=self.config.timeout_seconds,
                max_retries=0,
            )
        return self._sdk_client


class BrowseCompJudge:
    def __init__(self, client: JudgeClient | None, config: JudgeRunConfig):
        self.client = client
        self.config = config
        self._summary_lock = threading.Lock()

    def run(self) -> dict[str, Any]:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.config.summary_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.metrics_path.parent.mkdir(parents=True, exist_ok=True)

        records = load_prediction_records(self.config.conv_dir)
        pending = [record for record in records if self._should_run(record)]
        print(f"loaded predictions: {len(records)}")
        print(f"pending judge records: {len(pending)}")

        if pending:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.num_workers) as executor:
                future_to_record = {executor.submit(self._judge_one, record): record for record in pending}
                completed = 0
                for future in concurrent.futures.as_completed(future_to_record):
                    record = future_to_record[future]
                    completed += 1
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = self._judge_failed_result(record, exc)
                        self._write_result(record, result)
                    print(f"[{completed}/{len(pending)}] {record.run_id}: {result.get('status')} score={result.get('score')}")

        metrics = compute_metrics(load_judge_results(self.config.output_dir))
        self.config.metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return metrics

    def _should_run(self, record: PredictionRecord) -> bool:
        if self.config.force:
            return True
        return not self._result_path(record).exists()

    def _judge_one(self, record: PredictionRecord) -> dict[str, Any]:
        if record.pred_status != "success" and not self.config.include_failed:
            result = self._base_result(record)
            result.update(
                {
                    "status": "skipped_infer_failed",
                    "score": None,
                    "judge_reason": f"inference status is {record.pred_status}",
                    "judge_raw_response": "",
                    "judge_response": None,
                }
            )
            self._write_result(record, result)
            return result

        if not record.pred.strip():
            result = self._base_result(record)
            result.update(
                {
                    "status": "skipped_empty_prediction",
                    "score": None,
                    "judge_reason": "empty model response",
                    "judge_raw_response": "",
                    "judge_response": None,
                }
            )
            self._write_result(record, result)
            return result

        if self.client is None:
            raise RuntimeError("judge client is not configured")

        judged = self.client.judge(record)
        result = self._base_result(record)
        result.update(
            {
                "status": "judged",
                "score": judged["score"],
                "judge_reason": judged["judge_reason"],
                "judge_raw_response": judged["judge_raw_response"],
                "judge_response": judged["judge_response"],
            }
        )
        self._write_result(record, result)
        return result

    def _base_result(self, record: PredictionRecord) -> dict[str, Any]:
        return {
            "question_id": record.question_id,
            "run_id": record.run_id,
            "repeat_index": record.repeat_index,
            "type": record.type,
            "pred_status": record.pred_status,
            "question": record.question,
            "answer": record.answer,
            "prediction": record.pred,
            "token_usage": record.token_usage,
            "compression_stats": record.raw.get("compression_stats", {}),
            "pred_path": str(record.path),
        }

    def _judge_failed_result(self, record: PredictionRecord, exc: Exception) -> dict[str, Any]:
        result = self._base_result(record)
        result.update(
            {
                "status": "judge_failed",
                "score": None,
                "judge_reason": "",
                "judge_raw_response": "",
                "judge_response": None,
                "error": str(exc),
            }
        )
        return result

    def _write_result(self, record: PredictionRecord, result: dict[str, Any]) -> None:
        path = self._result_path(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

        summary = {
            "question_id": result.get("question_id"),
            "run_id": result.get("run_id"),
            "repeat_index": result.get("repeat_index"),
            "type": result.get("type"),
            "status": result.get("status"),
            "pred_status": result.get("pred_status"),
            "score": result.get("score"),
            "judge_reason": result.get("judge_reason", ""),
            "pred_path": result.get("pred_path"),
            "result_path": str(path),
            "error": result.get("error", ""),
        }
        with self._summary_lock:
            with self.config.summary_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(summary, ensure_ascii=False) + "\n")

    def _result_path(self, record: PredictionRecord) -> Path:
        return self.config.output_dir / f"iter{record.repeat_index}" / f"{record.question_id}.json"


_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "api_call_count",
)


def _extract_token_usage(raw: dict[str, Any]) -> dict[str, int]:
    """Pull hermes' real token accounting out of a prediction/conv record.

    Prefers the nested ``token_usage`` object, falling back to top-level
    ``input_tokens`` / ``output_tokens`` etc. Missing fields default to 0.
    """
    usage: dict[str, int] = {field: 0 for field in _TOKEN_FIELDS}
    nested = raw.get("token_usage") if isinstance(raw.get("token_usage"), dict) else {}
    for field in _TOKEN_FIELDS:
        value = nested.get(field, raw.get(field, 0))
        try:
            usage[field] = int(value or 0)
        except (TypeError, ValueError):
            usage[field] = 0
    if usage["total_tokens"] == 0:
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    return usage


def _aggregate_token_usage(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum token usage over judge results and report totals + per-run averages.

    Only runs that actually carry usage (api_call_count > 0 or any tokens)
    contribute to the average denominator, so skipped/failed inference rows
    don't dilute the mean.
    """
    totals: dict[str, int] = {field: 0 for field in _TOKEN_FIELDS}
    counted = 0
    for result in results:
        usage = result.get("token_usage")
        if not isinstance(usage, dict):
            continue
        has_data = any(int(usage.get(f, 0) or 0) for f in _TOKEN_FIELDS)
        if not has_data:
            continue
        counted += 1
        for field in _TOKEN_FIELDS:
            try:
                totals[field] += int(usage.get(field, 0) or 0)
            except (TypeError, ValueError):
                pass

    avg = {
        f"avg_{field}": round(totals[field] / counted, 2) if counted else 0.0
        for field in _TOKEN_FIELDS
    }
    return {
        "runs_with_usage": counted,
        "total": totals,
        "average_per_run": avg,
    }


_COMPRESSION_FIELDS = (
    "total_text_tokens",
    "total_image_tokens",
    "total_token_savings",
    "compressions",
)


def _aggregate_compression_stats(results: list[dict[str, Any]], token_usage: dict[str, Any]) -> dict[str, Any]:
    """Aggregate visual compression stats across all judge results.

    Computes:
      - totals: summed text/image/savings tokens across all runs
      - averages: per-run means (only counting runs that have compression data)
      - estimated_tokens_without_compression: actual total_input + total savings
      - compression_ratio: estimated_without / actual total_input
    """
    totals: dict[str, int] = {f: 0 for f in _COMPRESSION_FIELDS}
    counted = 0
    for result in results:
        cs = result.get("compression_stats")
        if not isinstance(cs, dict) or not cs:
            continue
        has_data = cs.get("compressions", 0) > 0
        if not has_data:
            continue
        counted += 1
        for f in _COMPRESSION_FIELDS:
            try:
                totals[f] += int(cs.get(f, 0) or 0)
            except (TypeError, ValueError):
                pass

    avg = {
        f"avg_{f}": round(totals[f] / counted, 2) if counted else 0.0
        for f in _COMPRESSION_FIELDS
    }

    actual_input = 0
    tu_total = token_usage.get("total", {}) if isinstance(token_usage, dict) else {}
    if isinstance(tu_total, dict):
        actual_input = tu_total.get("input_tokens", 0)

    estimated_without = actual_input + totals["total_token_savings"]
    ratio = round(estimated_without / actual_input, 4) if actual_input > 0 else None

    return {
        "runs_with_compression": counted,
        "total": totals,
        "average_per_run": avg,
        "actual_total_input_tokens": actual_input,
        "estimated_input_tokens_without_compression": estimated_without,
        "compression_ratio": ratio,
    }


def load_prediction_records(conv_dir: Path) -> list[PredictionRecord]:
    if not conv_dir.is_dir():
        raise FileNotFoundError(f"prediction conv dir not found: {conv_dir}")

    records: list[PredictionRecord] = []
    for path in sorted(conv_dir.rglob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            continue
        run_id = str(raw.get("run_id") or path.stem)
        question_id = str(raw.get("question_id") or infer_question_id(run_id, path))
        records.append(
            PredictionRecord(
                path=path,
                question_id=question_id,
                run_id=run_id,
                repeat_index=coerce_int(raw.get("repeat_index")),
                question=str(raw.get("question", "")),
                answer=raw.get("answer", ""),
                pred=str(raw.get("model_response") or raw.get("prediction") or raw.get("final_answer") or ""),
                pred_status=str(raw.get("status", "unknown")),
                type=str(raw.get("type", "")),
                token_usage=_extract_token_usage(raw),
                raw=raw,
            )
        )
    return records


def load_judge_results(output_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not output_dir.is_dir():
        return results
    for path in sorted(output_dir.rglob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(raw, dict):
            results.append(raw)
    return results


def compute_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    scored = [result for result in results if result.get("score") in (0, 1)]
    judged = [result for result in results if result.get("status") == "judged"]
    skipped_infer_failed = [result for result in results if result.get("status") == "skipped_infer_failed"]
    skipped_empty_prediction = [result for result in results if result.get("status") == "skipped_empty_prediction"]
    judge_failed = [result for result in results if result.get("status") == "judge_failed"]
    correct = sum(1 for result in scored if result.get("score") == 1)

    by_type: dict[str, dict[str, Any]] = {}
    for result in results:
        item_type = str(result.get("type") or "unknown")
        bucket = by_type.setdefault(
            item_type,
            {
                "total": 0,
                "scored": 0,
                "judged": 0,
                "skipped": 0,
                "correct": 0,
                "accuracy": None,
            },
        )
        bucket["total"] += 1
        if result.get("status") == "judged":
            bucket["judged"] += 1
        if str(result.get("status", "")).startswith("skipped_"):
            bucket["skipped"] += 1
        if result.get("score") in (0, 1):
            bucket["scored"] += 1
            bucket["correct"] += int(result.get("score") == 1)
    by_type_tokens: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        item_type = str(result.get("type") or "unknown")
        by_type_tokens.setdefault(item_type, []).append(result)
    for bucket in by_type.values():
        bucket["accuracy"] = safe_ratio(bucket["correct"], bucket["scored"])
        bucket["accuracy_by_total"] = safe_ratio(bucket["correct"], bucket["total"])
    for item_type, bucket in by_type.items():
        bucket["token_usage"] = _aggregate_token_usage(by_type_tokens.get(item_type, []))

    question_groups: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        question_groups.setdefault(str(result.get("question_id") or "unknown"), []).append(result)

    question_total_all = len(question_groups)
    question_total_scored = 0
    any_correct = 0
    majority_correct = 0
    for group in question_groups.values():
        scores = [int(result.get("score") == 1) for result in group if result.get("score") in (0, 1)]
        if not scores:
            continue
        question_total_scored += 1
        if any(scores):
            any_correct += 1
        if sum(scores) >= math.ceil(len(scores) / 2):
            majority_correct += 1

    token_usage = _aggregate_token_usage(results)

    return {
        "prediction_total": total,
        "scored": len(scored),
        "judged": len(judged),
        "skipped_infer_failed": len(skipped_infer_failed),
        "skipped_empty_prediction": len(skipped_empty_prediction),
        "judge_failed": len(judge_failed),
        "correct": correct,
        "accuracy": safe_ratio(correct, len(scored)),
        "accuracy_by_total": safe_ratio(correct, total),
        "token_usage": token_usage,
        "compression": _aggregate_compression_stats(results, token_usage),
        "run_level_accuracy_scored": safe_ratio(correct, len(scored)),
        "question_total_all": question_total_all,
        "question_total_scored": question_total_scored,
        "question_any_correct": any_correct,
        "question_any_correct_accuracy": safe_ratio(any_correct, question_total_scored),
        "question_any_correct_by_total": safe_ratio(any_correct, question_total_all),
        "question_majority_correct": majority_correct,
        "question_majority_accuracy": safe_ratio(majority_correct, question_total_scored),
        "question_majority_by_total": safe_ratio(majority_correct, question_total_all),
        "by_type": by_type,
    }


def get_chat_template() -> str:
    return (
        "You are a strict answer-equivalence judge. You will be given a question, "
        "a standard answer, and a model answer.\n\n"
        "Determine whether the model answer is consistent with the standard answer. "
        "They are consistent if they convey the same meaning, even if worded differently "
        '(e.g., "pink" and "it is pink" are consistent).\n\n'
        "Respond in JSON with two fields:\n"
        '- "reason": a brief explanation of why the answers are or are not consistent\n'
        '- "score": 1 if consistent, 0 if inconsistent\n'
    )


def build_judge_prompt(user_question: str, pred: str, ground_truths: Any) -> str:
    return (
        get_chat_template()
        + "\n"
        + f"[Question]: {user_question}\n"
        + f"[Standard Answer]: {format_ground_truth(ground_truths)}\n"
        + f"[Model Answer]: {pred}\n"
    )


def analyse_judgemodel_res(judge_res: str) -> float | None:
    # Keep the scoring logic aligned with the referenced reward script.
    import re as _re

    try:
        obj = json.loads(judge_res.strip())
        if "score" in obj:
            return CORRECT_SCORE if obj["score"] == 1 else INCORRECT_SCORE
    except (json.JSONDecodeError, TypeError):
        pass

    json_match = _re.search(r'\{[^{}]*"score"\s*:\s*(\d+)[^{}]*\}', judge_res)
    if json_match:
        score_val = int(json_match.group(1))
        return CORRECT_SCORE if score_val == 1 else INCORRECT_SCORE

    return None


def extract_judge_reason(judge_res: str) -> str:
    obj = extract_judge_object(judge_res)
    reason = obj.get("reason") if isinstance(obj, dict) else None
    return reason if isinstance(reason, str) else ""


def extract_judge_object(judge_res: str) -> dict[str, Any]:
    try:
        obj = json.loads(judge_res.strip())
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError):
        pass

    match = re.search(r'\{[^{}]*"score"\s*:\s*\d+[^{}]*\}', judge_res)
    if not match:
        return {}
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def extract_message_content(response: Any) -> str:
    if hasattr(response, "choices"):
        choices = response.choices
        if not choices:
            raise ValueError(f"judge response missing choices: {response}")
        message = choices[0].message
        content = message.content
        return content if isinstance(content, str) else str(content)

    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError(f"judge response missing choices: {response}")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ValueError(f"judge response missing message: {response}")
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(content)


def serialize_response(response: Any) -> Any:
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if hasattr(response, "dict"):
        return response.dict()
    return response


def format_ground_truth(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def infer_question_id(run_id: str, path: Path) -> str:
    if path.stem.startswith("q_"):
        return path.stem
    if path.parent.name != "conv":
        return path.parent.name
    return run_id


def safe_ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def make_absolute(path: Path) -> Path:
    if path.is_absolute():
        return path
    return Path.cwd() / path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Judge Browse Comp Hermes predictions with an answer-equivalence LLM")
    parser.add_argument("--pred-root", required=True, help="Prediction root: output/preds/{save_name}/{dataset}")
    parser.add_argument("--conv-dir", help="Prediction JSON directory. Defaults to {pred-root}/conv")
    parser.add_argument("--judge-output-dir", help="Judge output directory. Defaults to {pred-root}/judge")
    parser.add_argument("--summary-path", help="Judge summary JSONL. Defaults to {pred-root}/judge_summary.jsonl")
    parser.add_argument("--metrics-path", help="Judge metrics JSON. Defaults to {pred-root}/judge_metrics.json")
    parser.add_argument("--judge-model", default=os.getenv("JUDGE_MODEL", "gpt-5-mini"), help="Judge model/deployment name")
    parser.add_argument(
        "--judge-provider",
        choices=["openai", "azure"],
        default=os.getenv("JUDGE_PROVIDER", os.getenv("JUDGE_API_TYPE", "azure")),
        help="Judge API style",
    )
    parser.add_argument(
        "--judge-base-url",
        default=os.getenv("JUDGE_BASE_URL", os.getenv("AZURE_OPENAI_ENDPOINT", "")),
        help="OpenAI-compatible base URL or Azure endpoint",
    )
    parser.add_argument("--judge-api-key-env", default="JUDGE_API_KEY", help="Environment variable containing judge API key")
    parser.add_argument("--judge-api-key", default=None, help="Judge API key override. Prefer --judge-api-key-env.")
    parser.add_argument(
        "--judge-api-version",
        default=os.getenv("JUDGE_API_VERSION", os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")),
        help="Azure API version",
    )
    parser.add_argument("--num-workers", type=int, default=4, help="Parallel judge requests")
    parser.add_argument("--max-retries", type=int, default=3, help="Retries per judge request")
    parser.add_argument("--timeout-seconds", type=float, default=60, help="Per-request timeout")
    parser.add_argument("--max-tokens", type=int, default=2048, help="Judge max output tokens")
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--token-param", choices=["max_completion_tokens", "max_tokens"], default="max_completion_tokens")
    parser.add_argument("--no-json-schema", action="store_true", help="Do not send response_format json_schema")
    parser.add_argument("--include-failed", action="store_true", help="Also send failed inference outputs to the judge")
    parser.add_argument("--force", action="store_true", help="Rejudge even when judge output exists")
    parser.add_argument("--dry-run", action="store_true", help="Print planned judge count and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pred_root = Path(args.pred_root)
    if not pred_root.is_absolute():
        pred_root = Path.cwd() / pred_root
    if args.conv_dir:
        conv_dir = make_absolute(Path(args.conv_dir))
    elif (pred_root / "history").is_dir():
        conv_dir = make_absolute(pred_root / "history")
    else:
        conv_dir = make_absolute(pred_root / "conv")
    output_dir = make_absolute(Path(args.judge_output_dir) if args.judge_output_dir else pred_root / "judge")
    summary_path = make_absolute(Path(args.summary_path) if args.summary_path else pred_root / "judge_summary.jsonl")
    metrics_path = make_absolute(Path(args.metrics_path) if args.metrics_path else pred_root / "judge_metrics.json")

    records = load_prediction_records(conv_dir)
    pending = [record for record in records if args.force or not (output_dir / f"iter{record.repeat_index}" / f"{record.question_id}.json").exists()]
    needs_client = any(record.pred_status == "success" or args.include_failed for record in pending)

    print("Browse Comp Judge")
    print(f"  pred_root: {pred_root}")
    print(f"  conv_dir: {conv_dir}")
    print(f"  judge_output: {output_dir}")
    print(f"  judge_model: {args.judge_model}")
    print(f"  judge_provider: {args.judge_provider}")
    print(f"  predictions: {len(records)}")
    print(f"  pending: {len(pending)}")
    print(f"  workers: {args.num_workers}")
    print(f"  retries: {args.max_retries}")

    if args.dry_run:
        return 0

    client: JudgeClient | None = None
    if needs_client:
        api_key = args.judge_api_key or os.getenv(args.judge_api_key_env, "")
        if not api_key:
            print(f"missing judge API key: set {args.judge_api_key_env} or pass --judge-api-key")
            return 2
        if not args.judge_base_url:
            print("missing judge base URL: set JUDGE_BASE_URL/AZURE_OPENAI_ENDPOINT or pass --judge-base-url")
            return 2
        client = JudgeClient(
            JudgeClientConfig(
                api_key=api_key,
                base_url=args.judge_base_url,
                model=args.judge_model,
                provider=args.judge_provider,
                api_version=args.judge_api_version,
                timeout_seconds=args.timeout_seconds,
                max_retries=args.max_retries,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                top_p=args.top_p,
                token_param=args.token_param,
                use_json_schema=not args.no_json_schema,
            )
        )

    runner = BrowseCompJudge(
        client=client,
        config=JudgeRunConfig(
            conv_dir=conv_dir,
            output_dir=output_dir,
            summary_path=summary_path,
            metrics_path=metrics_path,
            num_workers=args.num_workers,
            force=args.force,
            include_failed=args.include_failed,
        ),
    )
    metrics = runner.run()
    print("done")
    print("  " + " ".join(f"{key}={value}" for key, value in metrics.items() if key not in ("by_type", "token_usage", "compression")))
    tu = metrics.get("token_usage", {})
    tu_total = tu.get("total", {}) if isinstance(tu, dict) else {}
    tu_avg = tu.get("average_per_run", {}) if isinstance(tu, dict) else {}
    print(
        "  tokens: runs_with_usage=%s total_input=%s total_output=%s total=%s | avg_input=%s avg_output=%s avg_total=%s avg_api_calls=%s"
        % (
            tu.get("runs_with_usage", 0) if isinstance(tu, dict) else 0,
            tu_total.get("input_tokens", 0),
            tu_total.get("output_tokens", 0),
            tu_total.get("total_tokens", 0),
            tu_avg.get("avg_input_tokens", 0),
            tu_avg.get("avg_output_tokens", 0),
            tu_avg.get("avg_total_tokens", 0),
            tu_avg.get("avg_api_call_count", 0),
        )
    )
    comp = metrics.get("compression", {})
    if isinstance(comp, dict) and comp.get("runs_with_compression", 0) > 0:
        ct = comp.get("total", {})
        print(
            "  compression: runs=%s text_tokens=%s image_tokens=%s savings=%s ratio=%s"
            % (
                comp.get("runs_with_compression", 0),
                ct.get("total_text_tokens", 0),
                ct.get("total_image_tokens", 0),
                ct.get("total_token_savings", 0),
                comp.get("compression_ratio", "N/A"),
            )
        )
    return 0 if metrics.get("judge_failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
