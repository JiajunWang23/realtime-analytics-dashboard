#!/usr/bin/env bash
# One-command local run: Postgres, Redis, 2x backend, frontend, live Wikipedia connector.
# Dashboard: http://localhost:8080
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Starting Docker Desktop..."
  open -a Docker 2>/dev/null || true
  for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
  docker info >/dev/null 2>&1 || { echo "Docker did not start. Open Docker Desktop and re-run."; exit 1; }
fi

docker compose up --build -d
echo
echo "Waiting for the dashboard..."
for _ in $(seq 1 60); do
  curl -fs http://localhost:8080/api/stats/summary >/dev/null 2>&1 && break
  sleep 2
done
echo "Dashboard:  http://localhost:8080"
echo "Logs:       docker compose logs -f wikipedia backend"
echo "Stop:       docker compose down"
(command -v open >/dev/null && open http://localhost:8080) || true
