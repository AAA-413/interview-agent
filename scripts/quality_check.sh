#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export JWT_SECRET_KEY="${JWT_SECRET_KEY:-test-secret}"
export AI_BAILIAN_API_KEY="${AI_BAILIAN_API_KEY:-dummy-key}"

cd "$ROOT_DIR"

echo "== Python compile =="
.venv/bin/python -m compileall -q app scripts tests/test_api_contracts.py

echo "== Ruff correctness checks =="
.venv/bin/ruff check .

echo "== Ruff format check =="
.venv/bin/ruff format --check .

echo "== Pytest =="
.venv/bin/pytest -q

echo "== Frontend build =="
(cd frontend && npm run build)
