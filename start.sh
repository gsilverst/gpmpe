#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"

cd "$ROOT_DIR"

if [[ ! -f .config ]]; then
  echo "Missing .config at $ROOT_DIR/.config"
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "Missing Python environment at $ROOT_DIR/.venv"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required but not found in PATH"
  exit 1
fi

echo "Building frontend static bundle..."
npm --prefix frontend ci
npm --prefix frontend run build

mkdir -p backend/app/static
rm -rf backend/app/static/*
cp -R frontend/out/. backend/app/static/

echo "Starting backend on http://$HOST:$PORT ..."
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host "$HOST" --port "$PORT" &
SERVER_PID=$!

cleanup() {
  if kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

echo "Waiting for readiness at /health ..."
for _ in $(seq 1 40); do
  if curl -fsS "http://$HOST:$PORT/health" >/dev/null 2>&1; then
    echo "GPMPE is ready: http://$HOST:$PORT"
    wait "$SERVER_PID"
    exit $?
  fi
  sleep 1
done

echo "Service did not become ready in time"
exit 1
