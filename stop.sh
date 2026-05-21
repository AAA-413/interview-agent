#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/logs/run"
STOP_INFRA=1
BACKEND_PORT="${BACKEND_PORT:-8002}"
FRONTEND_PORT="${FRONTEND_PORT:-5176}"

usage() {
  cat <<EOF
Usage: ./stop.sh [--keep-infra]

Options:
  --keep-infra  Stop only frontend/backend, keep docker compose services running.
EOF
}

log() {
  printf '[stop] %s\n' "$*"
}

warn() {
  printf '[stop][warn] %s\n' "$*" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-infra|--no-infra)
      STOP_INFRA=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      warn "Unknown option: $1"
      exit 1
      ;;
  esac
done

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

is_pid_running() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" >/dev/null 2>&1
}

process_command() {
  local pid="$1"
  ps -p "$pid" -o command= 2>/dev/null || true
}

process_cwd() {
  local pid="$1"
  lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1
}

is_managed_process() {
  local pid="$1"
  local marker="$2"
  local command_line cwd
  command_line="$(process_command "$pid")"
  cwd="$(process_cwd "$pid")"
  [[ ( "$command_line" == *"$ROOT_DIR"* || "$cwd" == "$ROOT_DIR"* ) && "$command_line" == *"$marker"* ]]
}

wait_until_stopped() {
  local pid="$1"
  local attempts="${2:-20}"

  for _ in $(seq 1 "$attempts"); do
    if ! is_pid_running "$pid"; then
      return 0
    fi
    sleep 1
  done

  return 1
}

stop_numeric_pid() {
  local label="$1"
  local pid="$2"
  local marker="$3"

  if ! is_pid_running "$pid"; then
    log "$label process $pid is not running."
    return 0
  fi

  if ! is_managed_process "$pid" "$marker"; then
    warn "Refusing to stop unmanaged $label process $pid:"
    process_command "$pid" >&2
    return 1
  fi

  log "Stopping $label process $pid ..."
  kill "$pid" >/dev/null 2>&1 || true
  if wait_until_stopped "$pid" 20; then
    return 0
  fi

  warn "$label process $pid did not stop gracefully; sending SIGKILL."
  kill -KILL "$pid" >/dev/null 2>&1 || true
}

screen_session_exists() {
  local session_name="$1"
  command_exists screen || return 1
  local sessions
  sessions="$(screen -ls 2>/dev/null || true)"
  grep -q "[.]$session_name[[:space:]]" <<< "$sessions"
}

stop_screen_session() {
  local session_name="$1"
  if screen_session_exists "$session_name"; then
    log "Stopping legacy screen session $session_name ..."
    screen -S "$session_name" -X quit >/dev/null 2>&1 || true
  fi
}

stop_from_pid_file() {
  local label="$1"
  local pid_file="$2"
  local marker="$3"

  if [[ ! -f "$pid_file" ]]; then
    log "$label pid file not found; skipping."
    return 0
  fi

  local token
  token="$(tr -d '[:space:]' < "$pid_file")"
  if [[ -z "$token" ]]; then
    rm -f "$pid_file"
    return 0
  fi

  if [[ "$token" == screen:* ]]; then
    stop_screen_session "${token#screen:}"
  elif [[ "$token" =~ ^[0-9]+$ ]]; then
    stop_numeric_pid "$label" "$token" "$marker"
  else
    warn "$label pid file has unknown content: $token"
  fi

  rm -f "$pid_file"
}

stop_known_legacy_screens() {
  stop_screen_session "interview-agent-backend"
  stop_screen_session "interview-agent-frontend"
  stop_screen_session "interview-agent-frontend-phase1"
}

stop_port_listener() {
  local label="$1"
  local port="$2"
  local marker="$3"
  local pids

  [[ -n "$port" ]] || return 0
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -n "$pids" ]] || return 0

  for pid in $pids; do
    if is_managed_process "$pid" "$marker"; then
      stop_numeric_pid "$label listener on port $port" "$pid" "$marker"
    else
      warn "Skipping unmanaged $label listener on port $port: pid $pid"
      process_command "$pid" >&2
    fi
  done
}

stop_project_frontend_ports() {
  local port
  local seen=" "
  for port in "$FRONTEND_PORT" 5175 5176; do
    [[ " $seen " == *" $port "* ]] && continue
    seen="$seen $port"
    stop_port_listener "frontend" "$port" "vite"
  done
}

stop_infra() {
  if [[ "$STOP_INFRA" -eq 0 ]]; then
    log "Keeping docker compose infrastructure running."
    return 0
  fi

  if command_exists docker; then
    log "Stopping docker compose infrastructure..."
    (cd "$ROOT_DIR" && docker compose down)
  else
    warn "docker is not installed or not in PATH; skipping infrastructure stop."
  fi
}

main() {
  mkdir -p "$RUN_DIR"

  stop_from_pid_file "frontend" "$RUN_DIR/frontend.pid" "vite"
  rm -f "$RUN_DIR/frontend.port"
  stop_from_pid_file "backend" "$RUN_DIR/backend.pid" "uvicorn app.main:app"
  stop_from_pid_file "legacy frontend phase1" "$RUN_DIR/frontend-phase1.pid" "vite"
  stop_known_legacy_screens
  stop_port_listener "backend" "$BACKEND_PORT" "uvicorn app.main:app"
  stop_project_frontend_ports
  stop_infra

  log "Stop complete."
}

main
