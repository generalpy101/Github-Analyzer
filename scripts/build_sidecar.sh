#!/bin/bash
# Build the Python Flask backend as a single binary for Tauri sidecar.
# Run this before `npm run tauri build`.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Determine target triple (Tauri requires the binary name to include this)
TARGET_TRIPLE=$(rustc -vV | grep host | cut -d' ' -f2)
BINARY_NAME="github-review-server-${TARGET_TRIPLE}"

echo "==> Building sidecar binary: ${BINARY_NAME}"
echo "    Target: ${TARGET_TRIPLE}"

# Ensure PyInstaller is installed
pip3 install pyinstaller --quiet 2>/dev/null || pip install pyinstaller --quiet

# Keep generated spec files out of repository root
mkdir -p scripts/pyinstaller

# Build with PyInstaller
pyinstaller \
    --onefile \
    --name "${BINARY_NAME}" \
    --distpath "src-tauri/binaries" \
    --specpath "scripts/pyinstaller" \
    --add-data "templates:templates" \
    --add-data "prompt_template.md:." \
    --hidden-import anthropic \
    --hidden-import openai \
    --hidden-import flask \
    --hidden-import jinja2 \
    --hidden-import jinja2.ext \
    --hidden-import markupsafe \
    --hidden-import werkzeug \
    --hidden-import werkzeug.serving \
    --hidden-import werkzeug.debug \
    --hidden-import sqlite3 \
    --hidden-import requests \
    --hidden-import certifi \
    --hidden-import charset_normalizer \
    --hidden-import idna \
    --hidden-import urllib3 \
    --hidden-import server \
    --hidden-import server.config \
    --hidden-import server.db \
    --hidden-import server.llm_client \
    --hidden-import server.fallback_review \
    --hidden-import server.fetch_github_data \
    --hidden-import server.generate_report \
    --hidden-import server.generation_manager \
    --noconfirm \
    --clean \
    app.py

echo ""
echo "==> Sidecar built successfully!"
echo "    Binary: src-tauri/binaries/${BINARY_NAME}"
echo ""
echo "    Next: npm run tauri build"
