#!/bin/bash
set -euo pipefail

OMNISAVE_ROOT="${OMNISAVE_ROOT:-/mnt/srv/omnisavedev}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_SRC="${REPO_ROOT}/deploy/docker-compose.yml"
ENV_FILE="${OMNISAVE_ROOT}/.env"

usage() {
    cat <<EOF
Usage: $(basename "$0") <command>

Commands:
  init    Create ${OMNISAVE_ROOT}/{data,config} and install compose + .env
  up      Build and start the server (detached)
  down    Stop the server
  logs    Follow container logs
  ps      Show compose status

Environment:
  OMNISAVE_ROOT        Install path (default: /mnt/srv/omnisave)
  OMNISAVE_REPO        Git checkout (in ${ENV_FILE})
  OMNISAVE_HOST        Server hostname (in ${ENV_FILE} only)
  OMNISAVE_PUBLIC_URL  Optional public URL (in ${ENV_FILE} only)
  OMNISAVE_SWITCHES         Switch FTP hosts for deploy.sh (in .env only)
  OMNISAVE_DOCKER_NETWORK   External network (default: selfhost)
  OMNISAVE_PORT_PUBLISH     Host port mapped to the container

Examples:
  $(basename "$0") init
  $(basename "$0") up
  $(basename "$0") logs
EOF
}

sync_env_file() {
    # Remove stale symlinks so cp can write a real file
    if [ -L "${ENV_FILE}" ]; then
        rm "${ENV_FILE}"
    fi
    if [ ! -f "${ENV_FILE}" ]; then
        cp "${REPO_ROOT}/deploy/.env.example" "${ENV_FILE}"
        sed -i "s|^OMNISAVE_REPO=.*|OMNISAVE_REPO=${REPO_ROOT}|" "${ENV_FILE}"
        echo "Wrote ${ENV_FILE} from deploy/.env.example"
    fi
}

cmd_init() {
    if [ ! -w "$(dirname "$OMNISAVE_ROOT")" ] 2>/dev/null; then
        echo "Creating ${OMNISAVE_ROOT} (may need sudo)..."
        sudo mkdir -p "${OMNISAVE_ROOT}"
        sudo chown "$(id -u):$(id -g)" "${OMNISAVE_ROOT}"
    fi

    mkdir -p "${OMNISAVE_ROOT}/data" "${OMNISAVE_ROOT}/config"
    cp "${COMPOSE_SRC}" "${OMNISAVE_ROOT}/docker-compose.yml"
    cp "${REPO_ROOT}/deploy/docker-compose.no-network.yml" "${OMNISAVE_ROOT}/"

    sync_env_file

    echo "Layout ready under ${OMNISAVE_ROOT}:"
    ls -la "${OMNISAVE_ROOT}"
}

compose() {
    if [ ! -f "${OMNISAVE_ROOT}/docker-compose.yml" ]; then
        echo "Run: $(basename "$0") init"
        exit 1
    fi
    docker compose -f "${OMNISAVE_ROOT}/docker-compose.yml" \
        --project-directory "${OMNISAVE_ROOT}" \
        --env-file "${ENV_FILE}" \
        "$@"
}

cmd_up() {
    cp "${COMPOSE_SRC}" "${OMNISAVE_ROOT}/docker-compose.yml"
    sync_env_file
    compose up -d --build
    echo ""
    echo "Server running."
    echo "  data:   ${OMNISAVE_ROOT}/data"
    echo "  config: ${OMNISAVE_ROOT}/config"
    compose logs --tail=20
}

cmd_down() { compose down; }
cmd_logs() { compose logs -f; }
cmd_ps()   { compose ps; }

case "${1:-}" in
    init) cmd_init ;;
    up)   cmd_up ;;
    down) cmd_down ;;
    logs) cmd_logs ;;
    ps)   cmd_ps ;;
    *)    usage; exit 1 ;;
esac
