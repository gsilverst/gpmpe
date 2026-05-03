#!/usr/bin/env bash
set -euo pipefail

# Run GPMPE against a project-owned data/config directory.
#
# Typical use from a sibling project:
#   cd ../private_customer_data
#   ../gpmpe/start-project.sh
#
# The project directory owns .config, DATA_DIR, DATABASE_PATH, OUTPUT_DIR, and
# any source-controlled YAML data. The GPMPE repo supplies the application code.

PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
APP_DIR="${GPMPE_APP_DIR:-}"
PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
SKIP_FRONTEND_BUILD="${SKIP_FRONTEND_BUILD:-false}"

if [[ -z "$APP_DIR" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  if [[ -d "$SCRIPT_DIR/backend" && -d "$SCRIPT_DIR/frontend" ]]; then
    APP_DIR="$SCRIPT_DIR"
  elif [[ -d "$PROJECT_DIR/../gpmpe/backend" && -d "$PROJECT_DIR/../gpmpe/frontend" ]]; then
    APP_DIR="$(cd "$PROJECT_DIR/../gpmpe" && pwd)"
  else
    echo "Unable to locate GPMPE app directory."
    echo "Set GPMPE_APP_DIR=/path/to/gpmpe and try again."
    exit 1
  fi
fi

CONFIG_FILE="$PROJECT_DIR/.config"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Missing project config at $CONFIG_FILE"
  exit 1
fi

if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  echo "Missing Python environment at $APP_DIR/.venv"
  exit 1
fi

if [[ "$SKIP_FRONTEND_BUILD" != "true" ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm is required but not found in PATH"
    exit 1
  fi

  echo "Building frontend static bundle from $APP_DIR/frontend ..."
  npm --prefix "$APP_DIR/frontend" ci
  npm --prefix "$APP_DIR/frontend" run build

  mkdir -p "$APP_DIR/backend/app/static"
  rm -rf "$APP_DIR/backend/app/static"/*
  cp -R "$APP_DIR/frontend/out/." "$APP_DIR/backend/app/static/"
else
  echo "Skipping frontend build because SKIP_FRONTEND_BUILD=true"
fi

echo "Project directory: $PROJECT_DIR"
echo "GPMPE app directory: $APP_DIR"
echo "Config file: $CONFIG_FILE"
echo "Starting backend on http://$HOST:$PORT ..."

GPMPE_CONFIG_FILE="$CONFIG_FILE" \
  "$APP_DIR/.venv/bin/python" -m uvicorn app.main:app \
  --app-dir "$APP_DIR/backend" \
  --host "$HOST" \
  --port "$PORT" &
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
