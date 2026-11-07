#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(cd .. && pwd)"
export PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export HERMES_BUNDLED_PLUGINS="${PROJECT_ROOT}/plugins"
if [[ -z "${HERMES_HOME:-}" && -f "${HOME}/.hermes/active_profile" ]]; then
  ACTIVE_PROFILE="$(tr -d '[:space:]' < "${HOME}/.hermes/active_profile")"
  if [[ -n "${ACTIVE_PROFILE}" && "${ACTIVE_PROFILE}" != "default" ]]; then
    export HERMES_HOME="${HOME}/.hermes/profiles/${ACTIVE_PROFILE}"
  fi
fi
HERMES_CONFIG_SOURCE="${HERMES_CONFIG_SOURCE:-${PROJECT_ROOT}/config.yaml}"
HERMES_CONFIG_TARGET="${HERMES_CONFIG_TARGET:-${HERMES_HOME:-${HOME}/.hermes}/config.yaml}"
if [[ "${BROWSECOMP_SYNC_HERMES_CONFIG:-1}" == "1" && -f "${HERMES_CONFIG_SOURCE}" ]]; then
  mkdir -p "$(dirname "${HERMES_CONFIG_TARGET}")"
  cp "${HERMES_CONFIG_SOURCE}" "${HERMES_CONFIG_TARGET}"
  echo "Synced Hermes config: ${HERMES_CONFIG_SOURCE} -> ${HERMES_CONFIG_TARGET}"
fi

# Local OpenAI-compatible Qwen endpoint. This private IP must bypass the
# global proxy in this environment.
HERMES_API_KEY="${HERMES_API_KEY:-sk-p1gpZaKqMwtIglnSkIZMyRTgGtk7lnzmCVX4SutmHmtj7P7V}"
HERMES_BASE_URL="${HERMES_BASE_URL:-https://tokenhub.sensetime.com/v1}"
MODEL="${MODEL:-claude-sonnet-4-6}"

PROVIDER="${PROVIDER:-custom}"
HERMES_BIN="${HERMES_BIN:-/root/.local/bin/hermes}"

BENCHMARK="${BENCHMARK:-${BENCH:-}}"
case "${BENCHMARK}" in
  "")
    DEFAULT_DATA_SOURCE="/mnt/afs_agents/sujiaqi/workspace/projects/hermes-agent/Browsecomp_eval/data/browsecomp_subset_final/questions_200.jsonl"
    DEFAULT_DATASET="browsecomp_subset_200"
    DEFAULT_FIRST_N="100"
    DEFAULT_EXPECTED_TOTAL="200"
    ;;
  bc|browsecomp)
    DEFAULT_DATA_SOURCE="${PROJECT_ROOT}/Browsecomp_eval/data/browsecomp_subset_final/questions_200.jsonl"
    DEFAULT_DATASET="bc"
    DEFAULT_FIRST_N="200"
    DEFAULT_EXPECTED_TOTAL="200"
    ;;
  bc-zh|bc_zh|browsecomp-zh|browsecomp_zh)
    DEFAULT_DATA_SOURCE="${PROJECT_ROOT}/Browsecomp_eval/data/bc_zh.jsonl"
    DEFAULT_DATASET="bc_zh"
    DEFAULT_FIRST_N="289"
    DEFAULT_EXPECTED_TOTAL="289"
    ;;
  sealo|seal0|seal-0|seal_0)
    DEFAULT_DATA_SOURCE="${PROJECT_ROOT}/Browsecomp_eval/data/seal-0.jsonl"
    DEFAULT_DATASET="seal0"
    DEFAULT_FIRST_N="111"
    DEFAULT_EXPECTED_TOTAL="111"
    ;;
  xbench|xbench-deepsearch|xbench_deepsearch|Xbench_deepsearch)
    DEFAULT_DATA_SOURCE="${PROJECT_ROOT}/Browsecomp_eval/data/Xbench_deepsearch.jsonl"
    DEFAULT_DATASET="xbench_deepsearch"
    DEFAULT_FIRST_N="100"
    DEFAULT_EXPECTED_TOTAL="100"
    ;;
  *)
    echo "Unknown BENCHMARK=${BENCHMARK}. Use one of: bc, bc-zh, seal0, xbench-deepsearch." >&2
    exit 2
    ;;
esac

DATA_SOURCE="${DATA_SOURCE:-${DEFAULT_DATA_SOURCE}}"
DATASET="${DATASET:-${DEFAULT_DATASET}}"
FIRST_N="${FIRST_N:-${DEFAULT_FIRST_N}}"
DATA_PATH="${DATA_PATH:-data/${DATASET}/questions_${FIRST_N}.jsonl}"
EXPECTED_TOTAL="${EXPECTED_TOTAL:-${DEFAULT_EXPECTED_TOTAL}}"

REPEATS="${REPEATS:-3}"
NUM_WORKERS="${NUM_WORKERS:-10}"
MAX_ROUNDS="${MAX_ROUNDS:-200}"
MAX_RETRIES="${MAX_RETRIES:-3}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-3600}"
CONTEXT_LENGTH="${CONTEXT_LENGTH:-262144}"
COMPRESS_THRESHOLD="${COMPRESS_THRESHOLD:-65536}"
HERMES_QUIET="${HERMES_QUIET:-1}"
HERMES_SESSION_STORAGE_ROOT="${HERMES_SESSION_STORAGE_ROOT:-/root/.hermes/sessions}"
FORCE="${FORCE:-0}"
CM="${CM:-visual}"
HERMES_VISUAL_HISTORY_SCALE="${HERMES_VISUAL_HISTORY_SCALE:-${HISTORY_SCALE:-}}"

case "${CM}" in
  visual|vis)
    STRATEGY_SUFFIX="vis"
    ;;
  sliding_window|sliding-window|sw)
    STRATEGY_SUFFIX="sw"
    ;;
  discard|discard_all|discard-all)
    STRATEGY_SUFFIX="discard"
    ;;
  summarize|summary|sm)
    STRATEGY_SUFFIX="sm"
    ;;
  none|off|false|0|no_cc)
    STRATEGY_SUFFIX="no_cc"
    ;;
  compressor|compression|cc|"")
    STRATEGY_SUFFIX="cc"
    ;;
  *)
    STRATEGY_SUFFIX="${CM//[^A-Za-z0-9_.-]/_}"
    ;;
esac
MODEL_SAFE="${MODEL//\//_}"
SAVE_NAME="${SAVE_NAME:-${DATASET}/${MODEL_SAFE}-${STRATEGY_SUFFIX}}"

# Toolsets enabled here cover browser/web/terminal/process/file/code tools:
# browser_navigate, browser_snapshot, browser_click, browser_type,
# browser_press, browser_scroll, browser_back, browser_console,
# browser_get_images, browser_vision, browser_dialog, browser_cdp,
# web_search, web_extract, vision_analyze, image_search, image_crop, image_zoom_in,
# terminal, process, read_file, write_file, search_files, patch, execute_code.
TOOL_WHITELIST="${TOOL_WHITELIST:-web,browser,vision,code_execution}"
SKILL_WHITELIST="${SKILL_WHITELIST:-}"

if [[ ! -x "${HERMES_BIN}" ]]; then
  echo "Hermes executable not found or not executable: ${HERMES_BIN}" >&2
  exit 2
fi

if [[ ! -f "${HERMES_BUNDLED_PLUGINS}/local_web/plugin.yaml" ]]; then
  echo "local-web plugin not found under HERMES_BUNDLED_PLUGINS: ${HERMES_BUNDLED_PLUGINS}" >&2
  exit 2
fi

if [[ "${BROWSECOMP_WEB_PREFLIGHT:-1}" == "1" ]]; then
  HERMES_PYTHON="python"
  if [[ -f "${HERMES_BIN}" ]]; then
    shebang="$(head -n 1 "${HERMES_BIN}" || true)"
    if [[ "${shebang}" == '#!'* ]]; then
      HERMES_PYTHON="${shebang#\#!}"
    fi
  fi
  "${HERMES_PYTHON}" - <<'PY'
from pathlib import Path
import json
import os
import sys

import tools.web_tools  # register built-in web tools before plugin override
from hermes_cli.config import load_config, get_config_path
from hermes_cli.plugins import PluginManager
from tools.registry import registry

cfg = load_config() or {}
PluginManager().discover_and_load()
status = {}
for name in ("web_search", "web_extract"):
    entry = registry._tools.get(name)
    handler = getattr(entry, "handler", None) if entry else None
    status[name] = {
        "module": getattr(handler, "__module__", ""),
        "name": getattr(handler, "__name__", ""),
        "toolset": getattr(entry, "toolset", ""),
    }

web = cfg.get("web", {}) if isinstance(cfg.get("web"), dict) else {}
plugins = cfg.get("plugins", {}) if isinstance(cfg.get("plugins"), dict) else {}
enabled = plugins.get("enabled", [])
if isinstance(enabled, str):
    enabled = [enabled]
local_web = web.get("local_web", {}) if isinstance(web.get("local_web"), dict) else {}
print("Hermes web preflight:")
print(f"  python: {sys.executable}")
print(f"  cwd: {Path.cwd()}")
print(f"  config: {get_config_path()}")
print(f"  HERMES_HOME: {os.environ.get('HERMES_HOME', '')}")
print(f"  HERMES_BUNDLED_PLUGINS: {os.environ.get('HERMES_BUNDLED_PLUGINS', '')}")
print(f"  requested CM: {os.environ.get('CM', '')}")
print(f"  plugins.enabled: {','.join(map(str, enabled)) if enabled else '(none)'}")
print(f"  web.search_backend: {web.get('search_backend', '')}")
print(f"  web.extract_backend: {web.get('extract_backend', '')}")
print(f"  web.local_web configured: {'yes' if local_web else 'no'}")
print("  effective.web_search: {module}.{name}".format(**status["web_search"]))
print("  effective.web_extract: {module}.{name}".format(**status["web_extract"]))

bad = [
    name
    for name, info in status.items()
    if info["module"] != "hermes_plugins.local_web"
]
if "local-web" not in enabled or bad:
    raise SystemExit(
        "local-web override is not active for: "
        + ",".join(bad or ["plugins.enabled"])
    )
PY
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
if [[ -n "${HERMES_VISUAL_HISTORY_SCALE}" ]]; then
  export HERMES_VISUAL_HISTORY_SCALE
fi

echo ""
echo "=== BrowseComp Eval ==="
echo "  benchmark: ${BENCHMARK:-manual}"
echo "  data_source: ${DATA_SOURCE}"
echo "  dataset: ${DATASET}"
echo "  save_name: ${SAVE_NAME}"
echo "  context_engine: ${CM}"
echo "  first_n: ${FIRST_N}"
echo "  compression_threshold: ${COMPRESS_THRESHOLD}"
echo ""

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
  --compression-threshold "${COMPRESS_THRESHOLD}" \
  --context-engine "${CM}" \
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
