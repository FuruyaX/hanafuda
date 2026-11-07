#!/usr/bin/env bash
# Hanafuda app: development environment in Docker (macOS / Linux / WSL).
# Run "setup" once while online. After that every command except "update" works offline.
#   ./setup.sh [setup|start|stop|logs|test|shell|export|update|clean]   (default: setup)
set -euo pipefail
cd "$(dirname "$0")"

CMD="${1:-setup}"
IMAGE="hanafuda-app-dev"
URL="http://localhost:8000"

step() { printf '\n==> %s\n' "$1"; }

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not installed or not running. Start it and re-run." >&2
  exit 1
fi

init_env() {
  if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    step "Building dev image"
    docker compose build dev
  fi
  step "Preparing Pyodide (downloads only if missing)"
  docker compose run --rm dev python scripts/fetch_pyodide.py
}

case "$CMD" in
  setup)
    init_env
    step "Running tests"
    docker compose run --rm dev pytest
    echo "Setup complete (offline-ready). Start with:  ./setup.sh start"
    ;;
  start)
    init_env
    step "Starting dev server"
    docker compose up -d dev
    for _ in $(seq 1 60); do curl -fs "$URL" >/dev/null 2>&1 && break; sleep 1; done
    if command -v open >/dev/null 2>&1; then open "$URL"
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
    fi
    echo "Running at $URL  (stop with: ./setup.sh stop)"
    ;;
  stop)   docker compose down ;;
  logs)   docker compose logs -f dev ;;
  test)   init_env; docker compose run --rm dev pytest ;;
  shell)  docker compose run --rm dev bash ;;
  export)
    init_env
    docker compose run --rm dev python scripts/build.py --out /app/dist
    echo "Upload the contents of ./dist to any HTTPS static host (e.g. GitHub Pages)."
    ;;
  update) docker compose build --pull dev ;;
  clean)
    docker compose down --volumes
    if docker image inspect "$IMAGE" >/dev/null 2>&1; then docker image rm "$IMAGE"; fi
    ;;
  *) echo "Usage: ./setup.sh [setup|start|stop|logs|test|shell|export|update|clean]" >&2; exit 1 ;;
esac
