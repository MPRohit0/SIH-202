#!/usr/bin/env bash
# One-command dev start for Linux/WSL: API (uvicorn), job worker, and the frontend dev server.
#
# Usage: ./scripts/start.sh
# Stop:  Ctrl+C (stops all three; background solver runs the worker already launched keep going
#        and are picked up again next time the worker starts, per CLAUDE.md rule 14).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p logs

if [ ! -f .env ]; then
  echo "No .env found — copying .env.example. Fill in real values before using GEE/OpenTopography." >&2
  cp .env.example .env
fi

# --- pick a Python for the API + worker ---------------------------------------------------------
PYTHON=""
if [ -n "${SIH26_PYTHON:-}" ]; then
  PYTHON="$SIH26_PYTHON"
elif command -v conda >/dev/null 2>&1 && conda env list | grep -qE '^\s*sih26\s'; then
  PYTHON="conda run -n sih26 --no-capture-output python"
elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
else
  echo "No Python environment found. Create one first:" >&2
  echo "  conda env create -f environment.yml && conda activate sih26" >&2
  echo "  # or: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

if [ ! -d frontend/node_modules ]; then
  echo "Installing frontend dependencies (first run only)..." >&2
  (cd frontend && npm install)
fi

PIDS=()
cleanup() {
  echo "Stopping API, worker, frontend..." >&2
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting API on http://localhost:8000 (logs/api.log)..."
$PYTHON -m uvicorn backend.m0_api.main:app --reload --port 8000 >logs/api.log 2>&1 &
PIDS+=($!)

echo "Starting job worker (logs/worker.log)..."
$PYTHON -m backend.m0_api.worker >logs/worker.log 2>&1 &
PIDS+=($!)

echo "Starting frontend on http://localhost:5173 (logs/frontend.log)..."
(cd frontend && npm run dev) >logs/frontend.log 2>&1 &
PIDS+=($!)

echo ""
echo "All three are starting. Tail logs/*.log for progress."
echo "  API health:  http://localhost:8000/api/v1/health"
echo "  Frontend:    http://localhost:5173"
echo "Press Ctrl+C to stop everything."
wait
