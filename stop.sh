#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT="${PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3100}"

cd "$ROOT_DIR"

stop_port() {
  local port="$1"
  local label="$2"

  local pids
  pids="$(lsof -t -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | tr '\n' ' ' | xargs || true)"

  if [[ -z "$pids" ]]; then
    echo "$label not running on port $port"
    return 0
  fi

  echo "Stopping $label on port $port (PID(s): $pids)"
  kill $pids 2>/dev/null || true

  # Give processes a moment to exit gracefully.
  for _ in $(seq 1 8); do
    if ! lsof -t -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "$label stopped"
      return 0
    fi
    sleep 1
  done

  # Force-kill anything still listening.
  local remaining
  remaining="$(lsof -t -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | tr '\n' ' ' | xargs || true)"
  if [[ -n "$remaining" ]]; then
    echo "Force stopping $label on port $port (PID(s): $remaining)"
    kill -9 $remaining 2>/dev/null || true
  fi

  if lsof -t -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Warning: $label may still be running on port $port"
    return 1
  fi

  echo "$label stopped"
  return 0
}

status=0
stop_port "$BACKEND_PORT" "Backend" || status=1
stop_port "$FRONTEND_PORT" "Frontend" || status=1

if [[ "$status" -eq 0 ]]; then
  echo "GPMPE services are stopped."
else
  echo "One or more services could not be stopped cleanly."
fi

exit "$status"
