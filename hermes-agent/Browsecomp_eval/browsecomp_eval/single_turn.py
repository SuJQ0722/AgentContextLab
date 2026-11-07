from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

import requests

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_PATH = "/mnt/afs_agents/sujiaqi/workspace/projects/hermes-agent/Browsecomp_eval/data/BrowseComp_full.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "output" / "single_turn"

DEFAULT_JUDGE_API_KEY = ""
DEFAULT_JUDGE_BASE_URL = "https://tokenhub.sensetime.com/v1"
DEFAULT_JUDGE_MODEL = "gpt-5-mini"

SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")
THREAD_LOCAL = threading.local()


def safe_id(value: str) -> str:
    cleaned = SAFE_ID_RE.sub("_", str(value).strip()).strip("._-")
    return cleaned or "unknown"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"line {line_no}: expected JSON object")
            for key in ("question", "answer", "type"):
                if key not in row:
                    raise ValueError(f"line {line_no}: missing field {key}")
            row.setdefault("id", f"q_{line_no:03d}")
            rows.append(row)
    return rows


def chat_url(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def session() -> requests.Session:
    sess = getattr(THREAD_LOCAL, "session", None)
    if sess is None:
        sess = requests.Session()
        THREAD_LOCAL.session = sess
    return sess


def post_chat(
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout: float,
    max_retries: int,
    label: str = "",
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, max(1, max_retries) + 1):
        try:
            response = session().post(
                chat_url(base_url),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:2000]}")
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError(f"unexpected response type: {type(data).__name__}")
            return data
        except Exception as exc:
            last_error = exc
            prefix = f"API error {label} " if label else "API error "
            print(f"{prefix}attempt {attempt}/{max(1, max_retries)}: {short_error(exc, 500)}", file=sys.stderr, flush=True)
            if attempt < max(1, max_retries):
                time.sleep(min(30.0, 2.0 ** (attempt - 1)))
    assert last_error is not None
    raise last_error


def message_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0]
    if not isinstance(choice, dict):
        return ""
    message = choice.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return str(content).strip() if content is not None else ""


def final_answer(text: str) -> str:
    text = text.strip()
    idx = text.lower().rfind("</think>")
    if idx != -1:
        text = text[idx + len("</think>") :].strip()
    for prefix in ("final answer:", "answer:"):
        if text.lower().startswith(prefix):
            return text[len(prefix) :].strip()
    return text


def token_usage(response: dict[str, Any]) -> dict[str, int]:
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    total = int(usage.get("total_tokens") or prompt + completion)
    return {
        "input_tokens": prompt,
        "output_tokens": completion,
        "total_tokens": total,
    }


def answer_prompt(question: str) -> str:
    return (
        "Answer the question below. Think carefully, but only output the final answer. "
        "Do not explain your reasoning.\n\n"
        f"Question:\n{question}\n\n"
        "Final answer:"
    )


def judge_prompt(question: str, gold: str, pred: str) -> str:
    return (
        "You are a strict answer-equivalence judge. Decide whether the model answer "
        "is consistent with the standard answer. Return only JSON in this format: "
        '{"reason":"brief reason","score":1}. Use score 1 for equivalent and 0 for not equivalent.\n\n'
        f"[Question]: {question}\n"
        f"[Standard Answer]: {gold}\n"
        f"[Model Answer]: {pred}\n"
    )


def run_one(row: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    qid = safe_id(str(row.get("id") or row["question"]))
    started = time.time()
    payload: dict[str, Any] = {
        "model": args.model,
        "messages": [{"role": "user", "content": answer_prompt(str(row["question"]))}],
        args.token_param: args.max_tokens,
    }
    if args.reasoning_effort:
        payload["reasoning_effort"] = args.reasoning_effort
    if args.temperature != "":
        payload["temperature"] = float(args.temperature)
    if args.top_p != "":
        payload["top_p"] = float(args.top_p)

    response = post_chat(
        base_url=args.base_url,
        api_key=args.api_key,
        payload=payload,
        timeout=args.timeout_seconds,
        max_retries=args.max_retries,
        label=qid,
    )
    raw_answer = message_text(response)
    pred = final_answer(raw_answer)
    usage = token_usage(response)
    choice = first_choice(response)
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    finish_reason = choice.get("finish_reason", "")
    reasoning = message.get("reasoning") if isinstance(message, dict) else ""
    reasoning_chars = len(reasoning) if isinstance(reasoning, str) else 0
    error = ""
    if not pred:
        error = "empty response"
        if finish_reason:
            error += f"; finish_reason={finish_reason}"
        if reasoning_chars:
            error += f"; reasoning_chars={reasoning_chars}"
        if finish_reason == "length":
            error += "; model used the output budget before producing content, increase --max-tokens"
    return {
        "question_id": qid,
        "question": row["question"],
        "answer": row["answer"],
        "type": row["type"],
        "model": args.model,
        "status": "success" if pred else "failed",
        "error": error,
        "finish_reason": finish_reason,
        "reasoning_chars": reasoning_chars,
        "prediction": pred,
        "raw_prediction": raw_answer,
        "response": response,
        "token_usage": usage,
        "duration_seconds": round(time.time() - started, 2),
    }


def failed_prediction(row: dict[str, Any], args: argparse.Namespace, exc: Exception) -> dict[str, Any]:
    return {
        "question_id": safe_id(str(row.get("id") or row.get("question") or "unknown")),
        "question": row.get("question", ""),
        "answer": row.get("answer", ""),
        "type": row.get("type", ""),
        "model": args.model,
        "status": "failed",
        "error": short_error(exc, 2000),
        "finish_reason": "",
        "reasoning_chars": 0,
        "prediction": "",
        "raw_prediction": "",
        "response": None,
        "token_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "duration_seconds": 0,
    }


def judge_one(prediction: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if prediction.get("status") != "success" or not str(prediction.get("prediction", "")).strip():
        result = dict(prediction)
        result.update({"judge_status": "skipped", "score": None, "judge_reason": "empty or failed prediction"})
        return result

    payload = {
        "model": args.judge_model,
        "messages": [
            {
                "role": "user",
                "content": judge_prompt(
                    str(prediction["question"]),
                    str(prediction["answer"]),
                    str(prediction["prediction"]),
                ),
            }
        ],
        args.judge_token_param: args.judge_max_tokens,
    }
    response = post_chat(
        base_url=args.judge_base_url,
        api_key=args.judge_api_key,
        payload=payload,
        timeout=args.judge_timeout_seconds,
        max_retries=args.judge_max_retries,
        label=f"judge/{prediction.get('question_id', '')}",
    )
    text = message_text(response)
    score, reason = parse_judge(text)
    result = dict(prediction)
    result.update(
        {
            "judge_status": "judged" if score in (0, 1) else "judge_failed",
            "score": score,
            "judge_reason": reason,
            "judge_raw": text,
            "judge_response": response,
        }
    )
    return result


def failed_judge(prediction: dict[str, Any], exc: Exception) -> dict[str, Any]:
    result = dict(prediction)
    result.update({"judge_status": "judge_failed", "score": None, "judge_reason": "", "judge_error": short_error(exc, 2000)})
    return result


def question_id(row: dict[str, Any]) -> str:
    return safe_id(str(row.get("id") or row.get("question_id") or row.get("question") or "unknown"))


def first_choice(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0]
    return {}


def parse_judge(text: str) -> tuple[int | None, str]:
    try:
        obj = json.loads(text.strip())
    except json.JSONDecodeError:
        match = re.search(r"\{.*?\}", text, flags=re.S)
        if not match:
            return None, ""
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None, ""
    if not isinstance(obj, dict):
        return None, ""
    score = obj.get("score")
    if score in (0, 1):
        return int(score), str(obj.get("reason", ""))
    return None, str(obj.get("reason", ""))


def short_error(exc: Exception | str, limit: int = 240) -> str:
    text = str(exc).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def append_jsonl(handle, row: dict[str, Any]) -> None:
    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    handle.flush()


def load_latest_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return latest
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"skip bad jsonl line {path}:{line_no}: {exc}", file=sys.stderr, flush=True)
                continue
            if isinstance(row, dict):
                latest[question_id(row)] = row
    return latest


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def accuracy_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    scored = [r for r in rows if r.get("score") in (0, 1)]
    correct = sum(1 for r in scored if r.get("score") == 1)
    failed = sum(1 for r in rows if r.get("status") != "success")
    return {
        "total": total,
        "success": total - failed,
        "failed": failed,
        "scored": len(scored),
        "correct": correct,
        "accuracy": round(correct / len(scored), 6) if scored else None,
        "accuracy_by_total": round(correct / total, 6) if total else None,
    }


def run_parallel(
    rows: list[dict[str, Any]],
    fn,
    fail_fn,
    workers: int,
    desc: str,
    stream_path: Path | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any] | None] = [None] * len(rows)
    stream_handle = None
    if stream_path is not None:
        stream_path.parent.mkdir(parents=True, exist_ok=True)
        stream_handle = stream_path.open("a", encoding="utf-8")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        try:
            futures = {executor.submit(fn, row): idx for idx, row in enumerate(rows)}
            completed = concurrent.futures.as_completed(futures)
            progress = tqdm(completed, total=len(futures), desc=desc, unit="q", file=sys.stderr) if tqdm else completed
            done = 0
            for future in progress:
                idx = futures[future]
                done += 1
                try:
                    result = future.result()
                except Exception as exc:
                    result = fail_fn(rows[idx], exc)
                results[idx] = result
                if stream_handle is not None:
                    append_jsonl(stream_handle, result)
                status = result.get("judge_status") or result.get("status")
                score = result.get("score")
                if tqdm:
                    postfix = {"status": status}
                    if score in (0, 1):
                        postfix["score"] = score
                    error = result.get("judge_error") or result.get("error")
                    if error:
                        postfix["error"] = short_error(str(error), 80)
                    progress.set_postfix(postfix)
                else:
                    label = result.get("question_id", idx)
                    error = result.get("judge_error") or result.get("error")
                    suffix = f" score={score}" if score in (0, 1) else ""
                    if error:
                        suffix += f" error={short_error(str(error), 200)}"
                    print(f"[{done}/{len(rows)}] {label}: {status}{suffix}", flush=True)
        finally:
            if stream_handle is not None:
                stream_handle.close()
    return [r for r in results if r is not None]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple BrowseComp single-turn pass1 eval with LLM judge")
    parser.add_argument("--data-path", default=str(DEFAULT_DATA_PATH))
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--workers", "--num-workers", dest="workers", type=int, default=int(os.getenv("NUM_WORKERS", "20")))
    parser.add_argument("--force", action="store_true", help="Rerun predictions and judge even if resumable outputs exist")
    parser.add_argument("--timeout-seconds", type=float, default=900)
    parser.add_argument("--max-retries", type=int, default=int(os.getenv("MAX_RETRIES", "3")))
    parser.add_argument("--max-tokens", type=int, default=int(os.getenv("MAX_TOKENS", "16384")))
    parser.add_argument("--token-param", choices=["max_tokens", "max_completion_tokens"], default=os.getenv("TOKEN_PARAM", "max_tokens"))
    parser.add_argument("--reasoning-effort", default=os.getenv("REASONING_EFFORT", "none"))
    parser.add_argument("--temperature", default=os.getenv("TEMPERATURE", ""))
    parser.add_argument("--top-p", default=os.getenv("TOP_P", ""))
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument("--judge-workers", type=int, default=int(os.getenv("JUDGE_NUM_WORKERS", os.getenv("NUM_WORKERS", "20"))))
    parser.add_argument("--judge-api-key", default=os.getenv("HERMES_API_KEY", DEFAULT_JUDGE_API_KEY))
    parser.add_argument("--judge-base-url", default=os.getenv("HERMES_BASE_URL", DEFAULT_JUDGE_BASE_URL))
    parser.add_argument("--judge-model", default=os.getenv("MODEL", DEFAULT_JUDGE_MODEL))
    parser.add_argument("--judge-timeout-seconds", type=float, default=float(os.getenv("JUDGE_TIMEOUT_SECONDS", "60")))
    parser.add_argument("--judge-max-retries", type=int, default=int(os.getenv("JUDGE_MAX_RETRIES", "3")))
    parser.add_argument("--judge-max-tokens", type=int, default=int(os.getenv("JUDGE_MAX_TOKENS", "1024")))
    parser.add_argument(
        "--judge-token-param",
        choices=["max_tokens", "max_completion_tokens"],
        default=os.getenv("JUDGE_TOKEN_PARAM", "max_completion_tokens"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    data_path = Path(args.data_path)
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR / safe_id(args.model)

    rows = load_jsonl(data_path)
    pred_path = output_dir / "predictions.jsonl"
    judged_path = output_dir / "judged.jsonl"
    print("single-turn pass1 eval")
    print(f"  data: {data_path}")
    print(f"  questions: {len(rows)}")
    print(f"  model: {args.model}")
    print(f"  base_url: {args.base_url}")
    print(f"  workers: {args.workers}")
    print(f"  reasoning_effort: {args.reasoning_effort or '(omitted)'}")
    print(f"  output_dir: {output_dir}")

    existing_predictions = {} if args.force else load_latest_jsonl(pred_path)
    pending_rows = [
        row for row in rows
        if existing_predictions.get(question_id(row), {}).get("status") != "success"
    ]
    print(f"prediction resume: existing_success={len(rows) - len(pending_rows)} pending={len(pending_rows)}")
    new_predictions = run_parallel(
        pending_rows,
        lambda row: run_one(row, args),
        lambda row, exc: failed_prediction(row, args, exc),
        args.workers,
        "answer",
        pred_path,
    )
    latest_predictions = dict(existing_predictions)
    for row in new_predictions:
        latest_predictions[question_id(row)] = row
    predictions = [latest_predictions.get(question_id(row), failed_prediction(row, args, RuntimeError("missing prediction"))) for row in rows]
    write_jsonl(output_dir / "predictions.jsonl", predictions)
    print_failures(predictions, "prediction")

    if args.skip_judge:
        metrics = accuracy_metrics(predictions)
        write_json(output_dir / "metrics.json", metrics)
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        return 0

    print("judge")
    existing_judged = {} if args.force else load_latest_jsonl(judged_path)
    pending_judge_rows = [
        row for row in predictions
        if not is_judge_done(existing_judged.get(question_id(row)), row)
    ]
    print(f"judge resume: existing_done={len(predictions) - len(pending_judge_rows)} pending={len(pending_judge_rows)}")
    new_judged = run_parallel(
        pending_judge_rows,
        lambda row: judge_one(row, args),
        failed_judge,
        args.judge_workers,
        "judge",
        judged_path,
    )
    latest_judged = dict(existing_judged)
    for row in new_judged:
        latest_judged[question_id(row)] = row
    judged = [latest_judged.get(question_id(row), failed_judge(row, RuntimeError("missing judge result"))) for row in predictions]
    metrics = accuracy_metrics(judged)
    write_jsonl(judged_path, judged)
    write_json(output_dir / "metrics.json", metrics)
    print_failures(judged, "judge")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


def is_judge_done(existing: dict[str, Any] | None, prediction: dict[str, Any]) -> bool:
    if not existing:
        return False
    if existing.get("prediction") != prediction.get("prediction"):
        return False
    if existing.get("judge_status") == "skipped" and prediction.get("status") != "success":
        return True
    return existing.get("judge_status") == "judged" and existing.get("score") in (0, 1)


def print_failures(rows: list[dict[str, Any]], label: str, limit: int = 10) -> None:
    failures = [
        row
        for row in rows
        if row.get("status") == "failed" or row.get("judge_status") == "judge_failed"
    ]
    if not failures:
        return
    print(f"{label} failures: {len(failures)}", flush=True)
    for row in failures[:limit]:
        err = row.get("judge_error") or row.get("error") or row.get("judge_raw") or ""
        print(f"  {row.get('question_id')}: {short_error(str(err), 500)}", flush=True)
    if len(failures) > limit:
        print(f"  ... {len(failures) - limit} more; see output jsonl for full errors", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
