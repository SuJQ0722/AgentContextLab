#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

HERMES_API_KEY="${HERMES_API_KEY:-EMPTY}"
HERMES_BASE_URL="${HERMES_BASE_URL:-http://10.120.5.36:8000/v1}"
MODEL="${MODEL:-Qwen3-5-9B}"
PROVIDER="${PROVIDER:-custom}"
HERMES_BIN="${HERMES_BIN:-/root/hermes-agent/.venv/bin/hermes}"
HERMES_SESSION_STORAGE_ROOT="${HERMES_SESSION_STORAGE_ROOT:-/root/.hermes/sessions}"
QWEN_NO_PROXY="${QWEN_NO_PROXY:-10.120.5.36,localhost,127.0.0.1,::1}"

URLS="${URLS:-https://example.com,https://www.google.com}"
RUNS_PER_URL="${RUNS_PER_URL:-50}"
CONCURRENCY="${CONCURRENCY:-50}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-240}"
MAX_TURNS="${MAX_TURNS:-4}"
DATASET="${DATASET:-browser_cdp_stress_$(date +%Y%m%d_%H%M%S)}"
BROWSER_PORTS="${BROWSER_PORTS:-9222,9223,9224,9225}"
BROWSER_BIN="${BROWSER_BIN:-}"
BROWSER_STARTUP_TIMEOUT="${BROWSER_STARTUP_TIMEOUT:-30}"
START_BROWSERS="${START_BROWSERS:-1}"
KEEP_BROWSERS="${KEEP_BROWSERS:-0}"

export HERMES_API_KEY
export HERMES_BASE_URL
export HERMES_SESSION_STORAGE_ROOT
export START_BROWSERS
export KEEP_BROWSERS
export NO_PROXY="${QWEN_NO_PROXY}"
export no_proxy="${QWEN_NO_PROXY}"

python -u scripts/browser_cdp_stress.py \
  --urls "${URLS}" \
  --runs-per-url "${RUNS_PER_URL}" \
  --concurrency "${CONCURRENCY}" \
  --timeout-seconds "${TIMEOUT_SECONDS}" \
  --max-turns "${MAX_TURNS}" \
  --model "${MODEL}" \
  --provider "${PROVIDER}" \
  --base-url "${HERMES_BASE_URL}" \
  --api-key "${HERMES_API_KEY}" \
  --hermes-bin "${HERMES_BIN}" \
  --session-storage-root "${HERMES_SESSION_STORAGE_ROOT}" \
  --no-proxy "${QWEN_NO_PROXY}" \
  --browser-ports "${BROWSER_PORTS}" \
  --browser-bin "${BROWSER_BIN}" \
  --browser-startup-timeout "${BROWSER_STARTUP_TIMEOUT}" \
  --dataset "${DATASET}"
