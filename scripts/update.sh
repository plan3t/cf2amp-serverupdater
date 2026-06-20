#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${CONFIG_PATH:-/config/config.yaml}"
SERVER_DIR="${SERVER_DIR:-/server}"
STOP_CMD="${STOP_CMD:-}"
START_CMD="${START_CMD:-}"

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

echo "$(timestamp) cf2amp lifecycle start"

if [ -n "$STOP_CMD" ]; then
  echo "$(timestamp) stopping server"
  bash -lc "$STOP_CMD"
fi

set +e
cf2amp run --config "$CONFIG_PATH"
status=$?
set -e

if [ -n "$START_CMD" ]; then
  echo "$(timestamp) starting server"
  bash -lc "$START_CMD"
fi

echo "$(timestamp) cf2amp lifecycle end status=$status serverDir=$SERVER_DIR"
exit "$status"
