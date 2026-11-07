#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

BENCHMARKS="${BENCHMARKS:-bc bc-zh seal0 xbench-deepsearch}"
RUN_SCRIPT="${RUN_SCRIPT:-scripts/run_browsecomp_vlm.sh}"
COMPRESS_THRESHOLD="${COMPRESS_THRESHOLD:-65536}"
CONTINUE_ON_ERROR="${CONTINUE_ON_ERROR:-0}"
EXIT_STATUS=0

for bench in ${BENCHMARKS//,/ }; do
  if [[ -z "${bench}" ]]; then
    continue
  fi

  echo ""
  echo "============================================================"
  echo "Running benchmark: ${bench}"
  echo "  run_script: ${RUN_SCRIPT}"
  echo "  compression_threshold: ${COMPRESS_THRESHOLD}"
  echo "============================================================"

  set +e
  (
    unset DATA_SOURCE DATASET DATA_PATH EXPECTED_TOTAL SAVE_NAME STRATEGY_SUFFIX
    export BENCHMARK="${bench}"
    export COMPRESS_THRESHOLD
    bash "${RUN_SCRIPT}"
  )
  rc=$?
  set -e

  if [[ "${rc}" -ne 0 ]]; then
    echo "Benchmark failed: ${bench} (exit ${rc})" >&2
    EXIT_STATUS="${rc}"
    if [[ "${CONTINUE_ON_ERROR}" != "1" ]]; then
      exit "${rc}"
    fi
  fi
done

exit "${EXIT_STATUS}"
