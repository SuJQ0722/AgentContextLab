#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# ── API & Model ──────────────────────────────────────────────
HERMES_API_KEY="${HERMES_API_KEY:-sk-2f8nSdpTYtOEvTOraocJ3dY4jDinlHRqRgxp3974pwgbbvkp}"
HERMES_BASE_URL="${HERMES_BASE_URL:-https://tokenhub.sensetime.com/v1}"
MODEL="${MODEL:-gpt-5.5}"

PROVIDER="${PROVIDER:-custom}"
HERMES_BIN="${HERMES_BIN:-/root/.local/bin/hermes}"

# ── Dataset ──────────────────────────────────────────────────
DATA_SOURCE="${DATA_SOURCE:-/mnt/afs_agents/sujiaqi/workspace/projects/qa_produce/data_filtered/questions_total_judged/questions_verified/verified_pass_random10.jsonl}"
DATASET="${DATASET:-browsecomp_subset_final}"
DATA_PATH="${DATA_PATH:-data/${DATASET}/questions.jsonl}"
EXPECTED_TOTAL="${EXPECTED_TOTAL:-10}"
FIRST_N="${FIRST_N:-10}"

# ── Run parameters ───────────────────────────────────────────
SAVE_NAME="${SAVE_NAME:-${MODEL//\//_}}"
REPEATS="${REPEATS:-1}"
NUM_WORKERS="${NUM_WORKERS:-10}"
MAX_ROUNDS="${MAX_ROUNDS:-200}"
MAX_RETRIES="${MAX_RETRIES:-3}"
HERMES_SESSION_STORAGE_ROOT="${HERMES_SESSION_STORAGE_ROOT:-/root/.hermes/sessions}"
FORCE="${FORCE:-0}"
REASONING_EFFORT="${REASONING_EFFORT:-high}"

# ── Context & compression ────────────────────────────────────
CONTEXT_LENGTH="${CONTEXT_LENGTH:-1000000}"
COMPRESSION_THRESHOLD="${COMPRESSION_THRESHOLD:-0.80}"
CONTEXT_ENGINE="${CONTEXT_ENGINE:-compressor}"
MAX_TOOL_RESPONSE="${MAX_TOOL_RESPONSE:-16384}"
API_MODE="${API_MODE:-codex_responses}"

# The runner accepts Hermes toolset names. The "web" toolset resolves to only:
# web_search, web_extract.
TOOL_WHITELIST="${TOOL_WHITELIST:-web,browser,code_execution}"
SKILL_WHITELIST="${SKILL_WHITELIST:-}"

if [[ ! -x "${HERMES_BIN}" ]]; then
  echo "Hermes executable not found or not executable: ${HERMES_BIN}" >&2
  exit 2
fi

# ── Validate & prepare dataset ───────────────────────────────
python - "${DATA_SOURCE}" "${DATA_PATH}" "${EXPECTED_TOTAL}" "${FIRST_N}" <<'PY'
import json
import sys
from pathlib import Path

source = Path(sys.argv[1])
output = Path(sys.argv[2])
expected_total = int(sys.argv[3])
first_n = int(sys.argv[4])

if not source.is_file():
    raise SystemExit(f"data source not found: {source}")

rows = []
errors = []
total = 0

with source.open("r", encoding="utf-8") as f:
    for line_no, line in enumerate(f, start=1):
        if not line.strip():
            continue
        total += 1
        try:
            row = json.loads(line)
        except Exception as exc:
            errors.append(f"line {line_no}: invalid JSON: {exc}")
            continue

        if not isinstance(row, dict):
            errors.append(f"line {line_no}: expected object, got {type(row).__name__}")
            continue

        missing = [key for key in ("question", "answer", "type") if key not in row]
        if missing:
            errors.append(f"line {line_no}: missing required field(s): {', '.join(missing)}")
            continue

        if not str(row["question"]).strip():
            errors.append(f"line {line_no}: question must not be empty")
            continue

        if len(rows) < first_n:
            rows.append(row)

if errors:
    print("Dataset validation failed:", file=sys.stderr)
    for error in errors[:20]:
        print(f"  {error}", file=sys.stderr)
    if len(errors) > 20:
        print(f"  ... {len(errors) - 20} more", file=sys.stderr)
    raise SystemExit(1)

if total != expected_total:
    raise SystemExit(f"expected {expected_total} rows, found {total}: {source}")

if len(rows) < first_n:
    raise SystemExit(f"expected at least {first_n} rows, found {len(rows)}")

output.parent.mkdir(parents=True, exist_ok=True)
with output.open("w", encoding="utf-8") as f:
    for row in rows:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

print(f"Validated {total} rows and wrote first {first_n} rows to {output}")
PY

if [[ "${PREPARE_ONLY:-0}" == "1" ]]; then
  exit 0
fi

# ── Sanity-check credentials ─────────────────────────────────
if [[ "${HERMES_API_KEY}" == "sk-exa...e-me" ||
      "${HERMES_BASE_URL}" == "https://example-llm-endpoint/v1" ||
      "${MODEL}" == "example-model-name" ]]; then
  echo "Replace HERMES_API_KEY, HERMES_BASE_URL, and MODEL at the top of this script or export them before running." >&2
  exit 2
fi

# ── Run ──────────────────────────────────────────────────────
export HERMES_API_KEY
export HERMES_BASE_URL
export HERMES_SESSION_STORAGE_ROOT

set +e
python -m browsecomp_eval.run \
  --dataset "${DATASET}" \
  --data-path "${DATA_PATH}" \
  --model "${MODEL}" \
  --provider "${PROVIDER}" \
  --base-url "${HERMES_BASE_URL}" \
  --hermes-bin "${HERMES_BIN}" \
  --save-name "${SAVE_NAME}" \
  --repeats "${REPEATS}" \
  --num-workers "${NUM_WORKERS}" \
  --max-rounds "${MAX_ROUNDS}" \
  --max-retries "${MAX_RETRIES}" \
  --tool-whitelist "${TOOL_WHITELIST}" \
  --skill-whitelist "${SKILL_WHITELIST}" \
  --reasoning-effort "${REASONING_EFFORT}" \
  --context-length "${CONTEXT_LENGTH}" \
  --compression-threshold "${COMPRESSION_THRESHOLD}" \
  --context-engine "${CONTEXT_ENGINE}" \
  --max-tool-response "${MAX_TOOL_RESPONSE}" \
  --api-mode "${API_MODE}" \
  --ignore-rules \
  $(if [[ "${FORCE}" == "1" ]]; then printf '%s' "--force"; fi)
INFER_EXIT=$?
set -e

# ── Judge ────────────────────────────────────────────────────
echo ""
echo "=== Judge ==="
DATASET=browsecomp_subset_final MODEL="${MODEL}" FORCE=1 bash scripts/judge_browsecomp.sh