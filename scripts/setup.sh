#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="${PROJECT_ROOT}/.tools/node-v24.11.0-linux-x64/bin:${PROJECT_ROOT}/.tools/pnpm/node_modules/.bin:${PATH}"
case "${1:-help}" in
  runtime)
    mkdir -p "${PROJECT_ROOT}/.tools"
    LAB_NODE_VERSION=v24.11.0
    LAB_NODE_ARCHIVE="node-${LAB_NODE_VERSION}-linux-x64.tar.xz"
    curl -fL --retry 2 "https://nodejs.org/dist/${LAB_NODE_VERSION}/${LAB_NODE_ARCHIVE}" -o "${PROJECT_ROOT}/.tools/${LAB_NODE_ARCHIVE}"
    curl -fL --retry 2 "https://nodejs.org/dist/${LAB_NODE_VERSION}/SHASUMS256.txt" -o "${PROJECT_ROOT}/.tools/SHASUMS256.txt"
    (cd "${PROJECT_ROOT}/.tools" && rg " ${LAB_NODE_ARCHIVE}$" SHASUMS256.txt | sha256sum --check -)
    tar --no-same-owner -xf "${PROJECT_ROOT}/.tools/${LAB_NODE_ARCHIVE}" -C "${PROJECT_ROOT}/.tools"
    npm install --prefix "${PROJECT_ROOT}/.tools/pnpm" pnpm@11.28.5
    ;;
  hermes)
    LAB_PYTHON="${2:-python3.11}"
    "$LAB_PYTHON" -c 'import sys; assert (3,11) <= sys.version_info[:2] < (3,14), "Python 3.11-3.13 required"'
    "$LAB_PYTHON" -m venv "${PROJECT_ROOT}/.venv"
    "${PROJECT_ROOT}/.venv/bin/python" -m pip install -e "${PROJECT_ROOT}/hermes-agent" -e "${PROJECT_ROOT}/hermes-agent/Browsecomp_eval" reportlab pymupdf Pillow pdf2image PyPDF2 numpy
    ;;
  renderer)
    # Local Ubuntu 22.04 runtime; no system package replacement.
    mkdir -p "${PROJECT_ROOT}/.tools/poppler"
    cd "${PROJECT_ROOT}/.tools"
    apt-get download poppler-utils libpoppler118 libopenjp2-7
    for LAB_DEB in poppler-utils_*.deb libpoppler118_*.deb libopenjp2-7_*.deb; do
      dpkg-deb --fsys-tarfile "$LAB_DEB" | tar --no-same-owner -x -C poppler
    done
    ;;
  dsh)
    git -C "${PROJECT_ROOT}" submodule update --init deepseekHarness
    node -e 'const [a,b]=process.versions.node.split(".").map(Number); if(a<24 || (a===24 && b<9)) { console.error("Node >=24.9 required"); process.exit(1) }'
    cd "${PROJECT_ROOT}/deepseekHarness"
    # The upstream hook installer cannot manage a submodule's core.worktree.
    # CI mode uses its supported hook-install skip while retaining other scripts.
    CI=true pnpm install --frozen-lockfile
    pnpm run build
    ;;
  *) echo 'Usage: bash scripts/setup.sh runtime|hermes|renderer|dsh'; exit 2 ;;
esac
