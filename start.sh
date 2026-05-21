#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/logs/run"
BACKEND_LOG="$ROOT_DIR/logs/backend.log"
FRONTEND_LOG="$ROOT_DIR/logs/frontend.log"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
FRONTEND_PORT_FILE="$RUN_DIR/frontend.port"
BACKEND_SESSION="interview-agent-backend"
FRONTEND_SESSION="interview-agent-frontend"

BACKEND_PORT="${BACKEND_PORT:-8002}"
FRONTEND_PORT="${FRONTEND_PORT:-}"

cd "$ROOT_DIR"
mkdir -p "$RUN_DIR"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    echo "Docker Compose is required." >&2
    exit 1
  fi
}

load_env() {
  if [[ ! -f "$ROOT_DIR/.env" ]]; then
    echo ".env not found. Copy .env.example to .env and fill in the API keys first." >&2
    exit 1
  fi

  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
}

port_in_use() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

pid_is_alive() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" >/dev/null 2>&1
}

screen_session_is_alive() {
  local session="$1"
  if ! command -v screen >/dev/null 2>&1; then
    return 1
  fi
  local sessions
  sessions="$(screen -ls 2>/dev/null || true)"
  grep -q "[.]$session[[:space:]]" <<<"$sessions"
}

wait_http() {
  local url="$1"
  local label="$2"
  local attempts="${3:-60}"

  for _ in $(seq 1 "$attempts"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  echo "$label did not become ready: $url" >&2
  return 1
}

wait_container_healthy() {
  local name="$1"
  local attempts="${2:-60}"
  local status

  for _ in $(seq 1 "$attempts"); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name" 2>/dev/null || true)"
    if [[ "$status" == "healthy" || "$status" == "running" ]]; then
      return 0
    fi
    sleep 1
  done

  echo "Container $name did not become healthy." >&2
  return 1
}

ensure_backend_deps() {
  if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
    if command -v uv >/dev/null 2>&1; then
      uv venv --python 3.11 "$ROOT_DIR/.venv"
    elif command -v python3.11 >/dev/null 2>&1; then
      python3.11 -m venv "$ROOT_DIR/.venv"
    else
      echo "Python 3.11 is required. Install it first, then rerun ./start.sh." >&2
      exit 1
    fi
  fi

  if "$ROOT_DIR/.venv/bin/python" - <<'PY' >/dev/null 2>&1
import fastapi, uvicorn, sqlalchemy, asyncpg, redis
PY
  then
    return 0
  fi

  echo "Installing backend dependencies into .venv..."
  local req_file="$RUN_DIR/requirements-start.txt"
  grep -v '^unstructured' "$ROOT_DIR/requirements.txt" > "$req_file"

  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$ROOT_DIR/.venv/bin/python" -r "$req_file" pytest pytest-asyncio ruff
  else
    "$ROOT_DIR/.venv/bin/python" -m pip install -r "$req_file" pytest pytest-asyncio ruff
  fi
}

ensure_frontend_deps() {
  if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
    echo "Installing frontend dependencies..."
    (cd "$ROOT_DIR/frontend" && npm install --no-package-lock --no-audit --no-fund)
  fi
}

ensure_pgvector_extension() {
  local db="${POSTGRES_DB:-interview_guide}"
  local user="${POSTGRES_USER:-postgres}"

  echo "Ensuring pgvector extension exists..."
  docker exec interview-postgres psql -U "$user" -d "$db" -c 'CREATE EXTENSION IF NOT EXISTS vector;' >/dev/null
}

choose_frontend_port() {
  if [[ -n "$FRONTEND_PORT" ]]; then
    if port_in_use "$FRONTEND_PORT"; then
      echo "FRONTEND_PORT=$FRONTEND_PORT is already in use." >&2
      exit 1
    fi
    echo "$FRONTEND_PORT"
    return 0
  fi

  for port in $(seq 5173 5185); do
    if ! port_in_use "$port"; then
      echo "$port"
      return 0
    fi
  done

  echo "No free frontend port found in 5173-5185." >&2
  exit 1
}

start_backend() {
  if screen_session_is_alive "$BACKEND_SESSION"; then
    echo "Backend already running in screen session: $BACKEND_SESSION"
    return 0
  fi

  if pid_is_alive "$BACKEND_PID_FILE"; then
    echo "Backend already running: pid $(cat "$BACKEND_PID_FILE")"
    return 0
  fi

  if port_in_use "$BACKEND_PORT"; then
    echo "Backend port $BACKEND_PORT is already in use. Run ./stop.sh or free the port first." >&2
    exit 1
  fi

  echo "Starting backend on http://localhost:$BACKEND_PORT ..."
  if command -v screen >/dev/null 2>&1; then
    local root_q python_q log_q
    printf -v root_q "%q" "$ROOT_DIR"
    printf -v python_q "%q" "$ROOT_DIR/.venv/bin/python"
    printf -v log_q "%q" "$BACKEND_LOG"
    screen -dmS "$BACKEND_SESSION" bash -lc "cd $root_q && exec $python_q -B -m uvicorn app.main:app --host 0.0.0.0 --port $BACKEND_PORT >$log_q 2>&1"
    echo "screen:$BACKEND_SESSION" > "$BACKEND_PID_FILE"
  else
    nohup "$ROOT_DIR/.venv/bin/python" -B -m uvicorn app.main:app \
      --host 0.0.0.0 \
      --port "$BACKEND_PORT" \
      >"$BACKEND_LOG" 2>&1 &
    echo "$!" > "$BACKEND_PID_FILE"
  fi

  wait_http "http://127.0.0.1:$BACKEND_PORT/api/health" "Backend" 90 || {
    echo "Backend log: $BACKEND_LOG" >&2
    exit 1
  }
}

start_frontend() {
  if screen_session_is_alive "$FRONTEND_SESSION"; then
    echo "Frontend already running in screen session: $FRONTEND_SESSION"
    return 0
  fi

  if pid_is_alive "$FRONTEND_PID_FILE"; then
    echo "Frontend already running: pid $(cat "$FRONTEND_PID_FILE")"
    return 0
  fi

  local port
  port="$(choose_frontend_port)"
  echo "$port" > "$FRONTEND_PORT_FILE"

  echo "Starting frontend on http://localhost:$port ..."
  if command -v screen >/dev/null 2>&1; then
    local frontend_dir_q log_q
    printf -v frontend_dir_q "%q" "$ROOT_DIR/frontend"
    printf -v log_q "%q" "$FRONTEND_LOG"
    screen -dmS "$FRONTEND_SESSION" bash -lc "cd $frontend_dir_q && exec npm run dev -- --host 0.0.0.0 --port $port --strictPort >$log_q 2>&1"
    echo "screen:$FRONTEND_SESSION" > "$FRONTEND_PID_FILE"
  else
    (
      cd "$ROOT_DIR/frontend"
      nohup npm run dev -- --host 0.0.0.0 --port "$port" --strictPort >"$FRONTEND_LOG" 2>&1 &
      echo "$!" > "$FRONTEND_PID_FILE"
    )
  fi

  wait_http "http://127.0.0.1:$port/" "Frontend" 60 || {
    echo "Frontend log: $FRONTEND_LOG" >&2
    exit 1
  }
}

main() {
  load_env

  echo "Starting Docker services..."
  compose up -d postgres redis minio minio-init
  wait_container_healthy interview-postgres
  wait_container_healthy interview-redis
  wait_container_healthy interview-minio
  ensure_pgvector_extension

  ensure_backend_deps
  ensure_frontend_deps
  start_backend
  start_frontend

  local frontend_port
  frontend_port="$(cat "$FRONTEND_PORT_FILE")"

  echo
  echo "Project started."
  echo "Frontend: http://localhost:$frontend_port"
  echo "Backend:  http://localhost:$BACKEND_PORT"
  echo "API docs: http://localhost:$BACKEND_PORT/docs"
  echo "Logs:     $ROOT_DIR/logs"
}

main "$@"
