#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Local OpenAI-compatible Qwen endpoint. This private IP must bypass the
# global proxy in this environment.
HERMES_API_KEY="${HERMES_API_KEY:-sk-2f8nSdpTYtOEvTOraocJ3dY4jDinlHRqRgxp3974pwgbbvkp}"
HERMES_BASE_URL="${HERMES_BASE_URL:-https://tokenhub.sensetime.com/v1}"
MODEL="${MODEL:-gemini-3.5-flash-thinking}"

PROVIDER="${PROVIDER:-custom}"
HERMES_BIN="${HERMES_BIN:-/root/.local/bin/hermes}"

DATA_SOURCE="${DATA_SOURCE:-/mnt/afs_agents/sujiaqi/workspace/projects/hermes-agent/Browsecomp_eval/data/browsecomp_subset_final/questions_200.jsonl}"
DATASET="${DATASET:-browsecomp_subset_200}"
FIRST_N="${FIRST_N:-200}"
DATA_PATH="${DATA_PATH:-data/${DATASET}/questions_${FIRST_N}.jsonl}"
EXPECTED_TOTAL="${EXPECTED_TOTAL:-200}"

SAVE_NAME="${SAVE_NAME:-${MODEL//\//_}}"
REPEATS="${REPEATS:-3}"
NUM_WORKERS="${NUM_WORKERS:-10}"
MAX_ROUNDS="${MAX_ROUNDS:-200}"
MAX_RETRIES="${MAX_RETRIES:-3}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-3600}"
CONTEXT_LENGTH="${CONTEXT_LENGTH:-262144}"
COMPRESS_THRESHOLD="${COMPRESS_THRESHOLD:-32768}"
HERMES_QUIET="${HERMES_QUIET:-1}"
HERMES_SESSION_STORAGE_ROOT="${HERMES_SESSION_STORAGE_ROOT:-/root/.hermes/sessions}"
FORCE="${FORCE:-0}"
CM="${CM:-compressor}"

# Toolsets enabled here cover browser/web/terminal/process/file/code tools:
# browser_navigate, browser_snapshot, browser_click, browser_type,
# browser_press, browser_scroll, browser_back, browser_console,
# browser_get_images, browser_vision, browser_dialog, browser_cdp,
# web_search, web_extract, terminal, process, read_file, write_file,
# search_files, patch, execute_code.
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

export NO_PROXY="10.120.4.40,localhost,127.0.0.1,::1"
export no_proxy="${NO_PROXY}"
export HERMES_API_KEY
export HERMES_BASE_URL
export HERMES_SESSION_STORAGE_ROOT

# Set context engine (CM=none to disable compression entirely)
"${HERMES_BIN}" config set context.engine "${CM}"

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
  --timeout-seconds "${TIMEOUT_SECONDS}" \
  --context-length "${CONTEXT_LENGTH}" \
  --tool-whitelist "${TOOL_WHITELIST}" \
  --skill-whitelist "${SKILL_WHITELIST}" \
  --ignore-rules \
  $(if [[ "${HERMES_QUIET}" == "0" ]]; then printf '%s' "--no-quiet"; fi) \
  $(if [[ "${FORCE}" == "1" ]]; then printf '%s' "--force"; fi)
INFER_EXIT=$?
set -e

# ── Judge ────────────────────────────────────────────────────
echo ""
echo "=== Judge ==="
DATASET="${DATASET}" SAVE_NAME="${SAVE_NAME}" FORCE=1 bash scripts/judge_browsecomp.sh