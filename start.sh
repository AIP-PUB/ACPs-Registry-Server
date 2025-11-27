#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-${0}}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
LOG_DIR="$PROJECT_ROOT/logs"
PID_FILE="$LOG_DIR/service.pid"
ENV_FILE="$PROJECT_ROOT/.env"
VENV_DIR="$PROJECT_ROOT/venv"
PYTHON_BIN="$VENV_DIR/bin/python"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
STDOUT_LOG="$LOG_DIR/server-$TIMESTAMP.log"

COLOR_RESET='\033[0m'
COLOR_INFO='\033[32m'
COLOR_ERROR='\033[31m'

info() {
  printf '%b[INFO]%b %s\n' "$COLOR_INFO" "$COLOR_RESET" "$1"
}

error() {
  printf '%b[ERROR]%b %s\n' "$COLOR_ERROR" "$COLOR_RESET" "$1" >&2
  exit 1
}

cd "$PROJECT_ROOT"

if [ ! -d "$VENV_DIR" ] || [ ! -x "$PYTHON_BIN" ]; then
  error "Missing Python virtual environment at $VENV_DIR"
fi

if [ ! -f "$ENV_FILE" ]; then
  error "Configuration file .env not found at $ENV_FILE"
fi

if ! command -v lsof >/dev/null 2>&1; then
  error "Required command 'lsof' is not available."
fi

mkdir -p "$LOG_DIR"

if [ -f "$PID_FILE" ]; then
  PID_CONTENT="$(cat "$PID_FILE")"
  if [ -n "$PID_CONTENT" ] && kill -0 "$PID_CONTENT" 2>/dev/null; then
    error "Service already appears to be running with PID $PID_CONTENT. Use ./stop.sh first."
  fi
  error "PID file $PID_FILE already exists. Use ./stop.sh to stop the service or remove the stale PID file."
fi

export PYTHONPATH="$PROJECT_ROOT"
PORT="$("$PYTHON_BIN" - <<'PY'
from app.core.config import settings
print(settings.UVICORN_PORT)
PY
)"

PORT="${PORT//[$'\r\n\t ']}"

if [ -z "$PORT" ]; then
  error "Unable to determine service port from configuration."
fi

if lsof -ti tcp:"$PORT" >/dev/null 2>&1; then
  error "Port $PORT is already in use."
fi

info "Starting service on port $PORT..."

nohup env PYTHONPATH="$PROJECT_ROOT" "$PYTHON_BIN" "$PROJECT_ROOT/main.py" >>"$STDOUT_LOG" 2>&1 &
SERVICE_PID=$!

if [ -z "$SERVICE_PID" ]; then
  error "Failed to obtain service PID."
fi

echo "$SERVICE_PID" >"$PID_FILE"

sleep 3

if ! kill -0 "$SERVICE_PID" 2>/dev/null; then
  rm -f "$PID_FILE"
  error "Service failed to start. Check log at $STDOUT_LOG"
fi

info "Service started successfully (PID: $SERVICE_PID)."
info "Logs are being written to $STDOUT_LOG"
info "To stop the service, run ./stop.sh"
