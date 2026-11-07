#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"
python3 -m unittest discover -s tests -v
if [[ "${1:-}" == "--hermes" ]]; then
  shift
  cd hermes-agent
  bash scripts/run_tests.sh "$@"
fi
