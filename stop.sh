#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-${0}}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
LOG_DIR="$PROJECT_ROOT/logs"
PID_FILE="$LOG_DIR/service.pid"

COLOR_RESET='\033[0m'
COLOR_INFO='\033[32m'
COLOR_WARN='\033[33m'
COLOR_ERROR='\033[31m'

info() {
  printf '%b[INFO]%b %s\n' "$COLOR_INFO" "$COLOR_RESET" "$1"
}

warn() {
  printf '%b[WARN]%b %s\n' "$COLOR_WARN" "$COLOR_RESET" "$1"
}

error() {
  printf '%b[ERROR]%b %s\n' "$COLOR_ERROR" "$COLOR_RESET" "$1" >&2
  exit 1
}

cd "$PROJECT_ROOT"

if [ ! -d "$LOG_DIR" ]; then
  error "Logs directory not found at $LOG_DIR"
fi

if [ ! -f "$PID_FILE" ]; then
  error "PID file $PID_FILE does not exist. Is the service running?"
fi

PID="$(cat "$PID_FILE" 2>/dev/null || true)"
PID="${PID//[$'\r\n\t ']}"

if [ -z "$PID" ]; then
  rm -f "$PID_FILE"
  error "PID file was empty. Removed stale PID file."
fi

if ! kill -0 "$PID" 2>/dev/null; then
  rm -f "$PID_FILE"
  error "No process with PID $PID is running. Removed stale PID file."
fi

info "Sending SIGTERM to process $PID"
kill "$PID"

sleep 2

if kill -0 "$PID" 2>/dev/null; then
  warn "Process $PID did not exit after SIGTERM. Sending SIGKILL."
  kill -9 "$PID"
  sleep 2
fi

if kill -0 "$PID" 2>/dev/null; then
  error "Unable to stop process $PID. Please check manually."
fi

rm -f "$PID_FILE"
info "Service stopped successfully."
