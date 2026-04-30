#!/usr/bin/env bash
# GPMPE Git Sync Worker
# Periodically polls the GPMPE API to pull latest YAML changes from Git.

set -euo pipefail

API_URL="${GPMPE_API_URL:-http://localhost:8000}"
INTERVAL_SECONDS="${SYNC_INTERVAL_SECONDS:-60}"

echo "Starting GPMPE Git Sync Worker..."
echo "Target API: $API_URL"
echo "Polling interval: ${INTERVAL_SECONDS}s"

while true; do
  echo "Checking for repository updates at $(date)..."
  
  # Trigger the /data/pull endpoint
  RESPONSE=$(curl -s -X POST "$API_URL/data/pull" || echo '{"error": "API unreachable"}')
  
  if echo "$RESPONSE" | grep -q '"changed": true'; then
    SYNCED_BIZ=$(echo "$RESPONSE" | grep -o '"businesses": [0-9]*' | cut -d' ' -f2 || echo "0")
    SYNCED_CAMP=$(echo "$RESPONSE" | grep -o '"campaigns": [0-9]*' | cut -d' ' -f2 || echo "0")
    echo "SUCCESS: Pulled new changes. Synced $SYNCED_BIZ businesses and $SYNCED_CAMP campaigns."
  elif echo "$RESPONSE" | grep -q '"changed": false'; then
    echo "No changes found."
  elif echo "$RESPONSE" | grep -q '"error"'; then
    echo "WARNING: Could not connect to GPMPE API."
  else
    echo "INFO: Response received: $RESPONSE"
  fi

  sleep "$INTERVAL_SECONDS"
done
