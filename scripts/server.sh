#!/bin/bash
set -euo pipefail

OMNISAVE_ROOT="${OMNISAVE_ROOT:-/mnt/srv/omnisavedev}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_SRC="${REPO_ROOT}/deploy/compose.yml"
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
    cp "${COMPOSE_SRC}" "${OMNISAVE_ROOT}/compose.yml"
    cp "${REPO_ROOT}/deploy/compose.no-network.yml" "${OMNISAVE_ROOT}/"

    sync_env_file

    echo "Layout ready under ${OMNISAVE_ROOT}:"
    ls -la "${OMNISAVE_ROOT}"
}

compose() {
    if [ ! -f "${OMNISAVE_ROOT}/compose.yml" ]; then
        echo "Run: $(basename "$0") init"
        exit 1
    fi
    docker compose -f "${OMNISAVE_ROOT}/compose.yml" \
        --project-directory "${OMNISAVE_ROOT}" \
        --env-file "${ENV_FILE}" \
        "$@"
}

cmd_up() {
    cp "${COMPOSE_SRC}" "${OMNISAVE_ROOT}/compose.yml"
    sync_env_file

    # The compose template always uses service name "omnisave".
    # Docker auto-creates a network alias from the service name, so if two instances
    # share a network and both have service name "omnisave", Docker DNS round-robins
    # between them — routing PROD traffic to the DEV container and vice versa.
    # Rewrite the service name to match OMNISAVE_CONTAINER_NAME so every instance
    # gets a unique alias. (Discovered 2026-06-20: caused token oscillation in prod.)
    CONTAINER_NAME=$(grep "^OMNISAVE_CONTAINER_NAME=" "${ENV_FILE}" | cut -d= -f2)
    CONTAINER_NAME="${CONTAINER_NAME:-omnisave}"
    SAFE_CONTAINER_NAME=$(printf '%s' "$CONTAINER_NAME" | sed 's/[&\\/]/\\&/g')
    sed -i "s/^  omnisave:/  ${SAFE_CONTAINER_NAME}:/" "${OMNISAVE_ROOT}/compose.yml"

    GIT_SHA=$(git -C "$REPO_ROOT" rev-parse --short=8 HEAD 2>/dev/null || echo "unknown")
    git -C "$REPO_ROOT" diff --quiet HEAD 2>/dev/null || GIT_SHA="${GIT_SHA}-dirty"
    export GIT_SHA
    compose up -d --build

    # Guard: fail loudly if another container on the same network shares our alias.
    # Checks cross-container collisions only — Docker normally gives each container
    # two identical aliases (service name + container name) which is not a collision.
    NETWORK=$(grep "^OMNISAVE_DOCKER_NETWORK=" "${ENV_FILE}" | cut -d= -f2)
    NETWORK="${NETWORK:-selfhost}"
    ALIAS_DUPS=$(
        CONTAINERS=$(docker network inspect "${NETWORK}" \
            --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null)
        [ -z "${CONTAINERS}" ] && exit 0
        # shellcheck disable=SC2086
        docker inspect ${CONTAINERS} \
            --format '{{.Name}}|{{range .NetworkSettings.Networks}}{{range .Aliases}}{{.}} {{end}}{{end}}' \
            2>/dev/null \
        | awk -F'|' '{
            container=$1; n=split($2,aliases," ")
            for(i=1;i<=n;i++){
                a=aliases[i]; if(a=="") continue
                if(alias_owner[a] && alias_owner[a]!=container) dups[a]=1
                else alias_owner[a]=container
            }
          } END { for(a in dups) print a }' | sort
    )
    if [ -n "${ALIAS_DUPS}" ]; then
        echo ""
        echo "ERROR: network alias collision on ${NETWORK}: ${ALIAS_DUPS}"
        echo "Two containers share the same alias — Docker DNS will round-robin between them."
        echo "Check compose.yml service names match their OMNISAVE_CONTAINER_NAME."
        exit 1
    fi

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
