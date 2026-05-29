#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/logs/run"
LOG_DIR="$ROOT_DIR/logs"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8002}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-5176}"
START_INFRA=1

usage() {
  cat <<EOF
Usage: ./start.sh [--no-infra]

Options:
  --no-infra   Do not run docker compose up -d.

Environment:
  BACKEND_HOST   Default: 127.0.0.1
  BACKEND_PORT   Default: 8002
  FRONTEND_HOST  Default: 0.0.0.0
  FRONTEND_PORT  Default: 5176
EOF
}

log() {
  printf '[start] %s\n' "$*"
}

warn() {
  printf '[start][warn] %s\n' "$*" >&2
}

die() {
  printf '[start][error] %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-infra)
      START_INFRA=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      die "Unknown option: $1"
      ;;
  esac
done

mkdir -p "$RUN_DIR" "$LOG_DIR"

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

is_managed_process() {
  local pid="$1"
  local marker="$2"
  local command_line
  command_line="$(process_command "$pid")"
  [[ "$command_line" == *"$ROOT_DIR"* && "$command_line" == *"$marker"* ]]
}

screen_session_exists() {
  local session_name="$1"
  command_exists screen || return 1
  local sessions
  sessions="$(screen -ls 2>/dev/null || true)"
  grep -q "[.]$session_name[[:space:]]" <<< "$sessions"
}

is_service_running_from_pid_file() {
  local pid_file="$1"
  local marker="$2"

  [[ -f "$pid_file" ]] || return 1

  local token
  token="$(tr -d '[:space:]' < "$pid_file")"
  if [[ "$token" == screen:* ]]; then
    screen_session_exists "${token#screen:}"
    return $?
  fi

  if is_pid_running "$token"; then
    is_managed_process "$token" "$marker"
    return $?
  fi

  rm -f "$pid_file"
  return 1
}

port_owner() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
}

assert_port_available() {
  local port="$1"
  local pid_file="$2"
  local marker="$3"
  local label="$4"

  if is_service_running_from_pid_file "$pid_file" "$marker"; then
    return 0
  fi

  if port_owner "$port" | sed -n '2p' | grep -q .; then
    warn "$label port $port is already in use by an unmanaged process:"
    port_owner "$port" >&2
    die "Refusing to start duplicate $label service."
  fi
}

wait_for_url() {
  local label="$1"
  local url="$2"
  local attempts="${3:-30}"

  for _ in $(seq 1 "$attempts"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "$label is ready: $url"
      return 0
    fi
    sleep 1
  done

  warn "$label did not become ready in time: $url"
  return 1
}

start_infra() {
  if [[ "$START_INFRA" -eq 0 ]]; then
    log "Skipping docker compose (--no-infra)."
    return 0
  fi

  command_exists docker || die "docker is not installed or not in PATH."
  log "Starting docker compose infrastructure..."
  (cd "$ROOT_DIR" && docker compose up -d)
}

check_runtime() {
  [[ -f "$ROOT_DIR/.env" ]] || warn ".env is missing; backend may fail if required secrets are not available."
  [[ -x "$ROOT_DIR/.venv/bin/python" ]] || die "Missing Python virtualenv at .venv/bin/python."
  [[ -x "$ROOT_DIR/.venv/bin/uvicorn" ]] || die "Missing uvicorn in .venv. Install backend dependencies first."
  [[ -x "$ROOT_DIR/frontend/node_modules/.bin/vite" ]] || die "Missing frontend/node_modules. Run npm install in frontend first."
}

clean_python_cache() {
  log "Cleaning Python bytecode cache..."
  find "$ROOT_DIR" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
}

start_backend() {
  local pid_file="$RUN_DIR/backend.pid"
  local log_file="$LOG_DIR/backend.log"
  local marker="uvicorn app.main:app"
  local session_name="interview-agent-backend"

  if is_service_running_from_pid_file "$pid_file" "$marker"; then
    log "Backend already running ($(tr -d '[:space:]' < "$pid_file"))."
    return 0
  fi

  assert_port_available "$BACKEND_PORT" "$pid_file" "$marker" "backend"

  log "Starting backend on http://$BACKEND_HOST:$BACKEND_PORT ..."
  if command_exists screen; then
    local root_q python_q env_q log_q
    printf -v root_q "%q" "$ROOT_DIR"
    printf -v python_q "%q" "$ROOT_DIR/.venv/bin/python"
    printf -v env_q "%q" "$ROOT_DIR/.env"
    printf -v log_q "%q" "$log_file"
    screen -dmS "$session_name" bash -lc \
      "cd $root_q && set -a && [[ -f $env_q ]] && source $env_q; set +a; exec $python_q -B -m uvicorn app.main:app --host $BACKEND_HOST --port $BACKEND_PORT > $log_q 2>&1"
    echo "screen:$session_name" > "$pid_file"
  else
    (
      cd "$ROOT_DIR"
      set -a
      [[ -f "$ROOT_DIR/.env" ]] && source "$ROOT_DIR/.env"
      set +a
      nohup "$ROOT_DIR/.venv/bin/python" -B -m uvicorn app.main:app \
        --host "$BACKEND_HOST" \
        --port "$BACKEND_PORT" \
        > "$log_file" 2>&1 &
      echo $! > "$pid_file"
    )
  fi

  wait_for_url "Backend" "http://127.0.0.1:$BACKEND_PORT/api/health" 45 || {
    warn "Backend log tail:"
    tail -n 80 "$log_file" >&2 || true
    return 1
  }
}

start_frontend() {
  local pid_file="$RUN_DIR/frontend.pid"
  local port_file="$RUN_DIR/frontend.port"
  local log_file="$LOG_DIR/frontend.log"
  local marker="vite"
  local session_name="interview-agent-frontend"

  if is_service_running_from_pid_file "$pid_file" "$marker"; then
    log "Frontend already running ($(tr -d '[:space:]' < "$pid_file"))."
    return 0
  fi

  assert_port_available "$FRONTEND_PORT" "$pid_file" "$marker" "frontend"

  log "Starting frontend on http://127.0.0.1:$FRONTEND_PORT ..."
  local api_proxy_target="http://127.0.0.1:$BACKEND_PORT"
  if command_exists screen; then
    local frontend_dir_q vite_q log_q
    printf -v frontend_dir_q "%q" "$ROOT_DIR/frontend"
    printf -v vite_q "%q" "$ROOT_DIR/frontend/node_modules/.bin/vite"
    printf -v log_q "%q" "$log_file"
    screen -dmS "$session_name" bash -lc \
      "cd $frontend_dir_q && VITE_API_PROXY_TARGET=$api_proxy_target exec $vite_q --host $FRONTEND_HOST --port $FRONTEND_PORT --strictPort > $log_q 2>&1"
    echo "screen:$session_name" > "$pid_file"
    echo "$FRONTEND_PORT" > "$port_file"
  else
    (
      cd "$ROOT_DIR/frontend"
      export VITE_API_PROXY_TARGET="$api_proxy_target"
      nohup "$ROOT_DIR/frontend/node_modules/.bin/vite" \
        --host "$FRONTEND_HOST" \
        --port "$FRONTEND_PORT" \
        --strictPort \
        > "$log_file" 2>&1 &
      echo $! > "$pid_file"
      echo "$FRONTEND_PORT" > "$port_file"
    )
  fi

  wait_for_url "Frontend" "http://127.0.0.1:$FRONTEND_PORT" 45 || {
    warn "Frontend log tail:"
    tail -n 80 "$log_file" >&2 || true
    return 1
  }
}

main() {
  check_runtime
  start_infra
  clean_python_cache
  start_backend
  start_frontend

  log "All services started."
  log "Frontend: http://127.0.0.1:$FRONTEND_PORT"
  log "Backend:  http://127.0.0.1:$BACKEND_PORT"
  log "Logs:     $LOG_DIR"
}

main
