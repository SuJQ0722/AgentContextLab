#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
case "${1:-help}" in
  hermes)
    LAB_PYTHON="${2:-python3.11}"
    "$LAB_PYTHON" -c 'import sys; assert (3,11) <= sys.version_info[:2] < (3,14), "Python 3.11-3.13 required"'
    "$LAB_PYTHON" -m venv "${PROJECT_ROOT}/.venv"
    "${PROJECT_ROOT}/.venv/bin/python" -m pip install -e "${PROJECT_ROOT}/hermes-agent" -e "${PROJECT_ROOT}/hermes-agent/Browsecomp_eval" reportlab pymupdf Pillow
    ;;
  dsh)
    git -C "${PROJECT_ROOT}" submodule update --init deepseekHarness
    node -e 'const [a,b]=process.versions.node.split(".").map(Number); if(a<24 || (a===24 && b<9)) { console.error("Node >=24.9 required"); process.exit(1) }'
    cd "${PROJECT_ROOT}/deepseekHarness"
    pnpm install --frozen-lockfile
    pnpm run build
    ;;
  *) echo 'Usage: bash scripts/setup.sh hermes|dsh'; exit 2 ;;
esac
