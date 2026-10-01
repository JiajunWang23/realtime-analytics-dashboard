#!/bin/bash
# Double-click to run the Real-Time Analytics Dashboard locally on macOS.
# Uses Docker if it's running; otherwise needs nothing pre-installed except Xcode Command
# Line Tools (for a ~1 min Redis build):
#   Python 3.12 via uv · PostgreSQL via the pgserver wheel · Redis built from source once ·
#   the prebuilt dashboard in frontend/dist, served by the backend.
cd "$(dirname "$0")"
ROOT="$(pwd)"; RUN="$ROOT/.run"; mkdir -p "$RUN"
BACKEND_PORT=5050                # :5000 is taken by macOS AirPlay Receiver
REDIS_VERSION=7.4.2

say()  { printf "\n\033[1;34m==> %s\033[0m\n" "$*"; }
fail() { printf "\n\033[1;31m%s\033[0m\n" "$*"; echo "Press any key to close."; read -n 1; exit 1; }

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  say "Docker is running: starting everything with docker compose"
  ./run-local.sh; echo "Press any key to close."; read -n 1; exit 0
fi

# ---------- Python 3.12 (uv downloads a prebuilt interpreter) ----------
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  say "Installing uv (fast Python package manager)"
  curl -LsSf https://astral.sh/uv/install.sh | sh || fail "Could not install uv"
  export PATH="$HOME/.local/bin:$PATH"
fi
say "Preparing Python 3.12 environment"
[ -x .venv/bin/python ] || uv venv -q --python 3.12 .venv || fail "uv venv failed"
source .venv/bin/activate
uv pip install -q -r backend/requirements.txt -r connectors/requirements.txt pgserver || fail "Python packages failed to install"

# ---------- PostgreSQL (pgserver wheel: real Postgres 16, no install) ----------
say "Starting PostgreSQL"
DATABASE_URL="$(python scripts/local_postgres.py "$RUN/pgdata" 2>"$RUN/postgres.log" | tail -1)"
[ -n "$DATABASE_URL" ] || fail "PostgreSQL did not start. See .run/postgres.log"
export DATABASE_URL

# ---------- Redis (reuse a running one, else build once from source) ----------
REDIS_CLI=""
if (exec 3<>/dev/tcp/127.0.0.1/6379) 2>/dev/null; then
  say "Redis already running on :6379, reusing it"
else
  if [ ! -x "$RUN/redis/src/redis-server" ]; then
    command -v make >/dev/null 2>&1 || { xcode-select --install 2>/dev/null; fail "Xcode Command Line Tools are needed to build Redis. Finish the install dialog, then run start.command again."; }
    say "Building Redis $REDIS_VERSION (one time, ~1 minute)"
    rm -rf "$RUN/redis" && mkdir -p "$RUN/redis"
    curl -fsSL "https://github.com/redis/redis/archive/refs/tags/$REDIS_VERSION.tar.gz" | tar xz -C "$RUN/redis" --strip-components 1 \
      || fail "Could not download Redis source"
    (cd "$RUN/redis" && make -j"$(sysctl -n hw.ncpu)" MALLOC=libc BUILD_TLS=no >"$RUN/redis-build.log" 2>&1) \
      || fail "Redis build failed. See .run/redis-build.log"
  fi
  say "Starting Redis"
  "$RUN/redis/src/redis-server" --port 6379 --save "" --appendonly no --daemonize yes \
      --logfile "$RUN/redis.log" --dir "$RUN" || fail "Redis did not start. See .run/redis.log"
  sleep 1
fi
export REDIS_URL="redis://localhost:6379/0"

# ---------- Dashboard UI ----------
# The React app ships prebuilt in frontend/dist and is served by the backend itself,
# so no Node/npm is needed. (Developing the UI: cd frontend && npm install && npm run dev)
[ -f frontend/dist/index.html ] || fail "frontend/dist is missing. Build it with: cd frontend && npm install && npm run build"

# ---------- Run ----------
export WEB_CONCURRENCY=2 PORT=$BACKEND_PORT BACKEND_URL="http://localhost:$BACKEND_PORT"
export COLLECT_ORIGINS="http://localhost:$BACKEND_PORT,https://uiucwangjiajun.com,https://www.uiucwangjiajun.com"
cleanup() { say "Stopping dashboard (Postgres and Redis keep running; see README to stop them)"; kill $(jobs -p) 2>/dev/null; exit 0; }
trap cleanup INT TERM HUP

say "Starting backend on :$BACKEND_PORT"
(cd backend && gunicorn -c gunicorn.conf.py wsgi:app) >"$RUN/backend.log" 2>&1 &
for _ in $(seq 1 40); do curl -fs "localhost:$BACKEND_PORT/readyz" >/dev/null 2>&1 && break; sleep 1; done
curl -fs "localhost:$BACKEND_PORT/readyz" >/dev/null 2>&1 || fail "Backend did not start. See .run/backend.log"

say "Connecting to the live Wikipedia stream"
python connectors/wikipedia.py --api "$BACKEND_URL" >"$RUN/wikipedia.log" 2>&1 &

open "http://localhost:$BACKEND_PORT/#wikipedia"

printf "\n\033[1;32mRunning.\033[0m  Dashboard: http://localhost:$BACKEND_PORT\n"
echo "Logs in .run/   |   Close this window or press Ctrl+C to stop."
tail -f "$RUN/wikipedia.log"
