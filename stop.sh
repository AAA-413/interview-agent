#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/logs/run"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
FRONTEND_PORT_FILE="$RUN_DIR/frontend.port"
BACKEND_SESSION="interview-agent-backend"
FRONTEND_SESSION="interview-agent-frontend"
BACKEND_PORT="${BACKEND_PORT:-8002}"

cd "$ROOT_DIR"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    return 0
  fi
}

stop_pid_file() {
  local label="$1"
  local pid_file="$2"

  if [[ ! -f "$pid_file" ]]; then
    return 0
  fi

  local pid
  pid="$(cat "$pid_file")"
  if [[ "$pid" == screen:* ]]; then
    rm -f "$pid_file"
    return 0
  fi

  if ! kill -0 "$pid" >/dev/null 2>&1; then
    rm -f "$pid_file"
    return 0
  fi

  echo "Stopping $label: pid $pid"
  terminate_pid "$label" "$pid"
  rm -f "$pid_file"
}

terminate_pid() {
  local label="$1"
  local pid="$2"

  if ! kill -0 "$pid" >/dev/null 2>&1; then
    return 0
  fi

  kill "$pid" >/dev/null 2>&1 || true

  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done

  echo "$label did not stop gracefully; killing pid $pid"
  kill -9 "$pid" >/dev/null 2>&1 || true
}

stop_screen_session() {
  local label="$1"
  local session="$2"

  if ! command -v screen >/dev/null 2>&1; then
    return 0
  fi

  local sessions
  sessions="$(screen -ls 2>/dev/null || true)"

  if grep -q "[.]$session[[:space:]]" <<<"$sessions"; then
    echo "Stopping $label screen session: $session"
    screen -S "$session" -X quit >/dev/null 2>&1 || true
  fi
}

process_cwd() {
  local pid="$1"
  lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1
}

process_belongs_to_project() {
  local pid="$1"
  local cmd cwd

  cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  cwd="$(process_cwd "$pid")"

  [[ "$cmd" == *"$ROOT_DIR"* || "$cwd" == "$ROOT_DIR"* ]]
}

stop_port_listener() {
  local label="$1"
  local port="$2"

  if [[ -z "$port" ]]; then
    return 0
  fi

  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"

  for pid in $pids; do
    if process_belongs_to_project "$pid"; then
      echo "Stopping $label listener on port $port: pid $pid"
      terminate_pid "$label listener on port $port" "$pid"
    else
      echo "Skipping $label listener on port $port: pid $pid is outside this project"
    fi
  done
}

main() {
  local frontend_port=""
  if [[ -f "$FRONTEND_PORT_FILE" ]]; then
    frontend_port="$(cat "$FRONTEND_PORT_FILE")"
  fi

  stop_screen_session "frontend" "$FRONTEND_SESSION"
  stop_screen_session "backend" "$BACKEND_SESSION"
  stop_pid_file "frontend" "$FRONTEND_PID_FILE"
  stop_pid_file "backend" "$BACKEND_PID_FILE"
  stop_port_listener "frontend" "$frontend_port"
  stop_port_listener "backend" "$BACKEND_PORT"
  rm -f "$FRONTEND_PORT_FILE"

  echo "Stopping Docker services..."
  compose down

  echo "Project stopped."
}

main "$@"
