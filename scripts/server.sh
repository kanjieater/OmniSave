#!/bin/bash
set -euo pipefail

# Parse --prod flag before any other arg.
# --prod is the ONLY way to target the production instance (/mnt/srv/omnisave).
# Without it, all commands operate on dev (/mnt/srv/omnisavedev).
PROD=0
ARGS=()
for arg in "$@"; do
    if [ "$arg" = "--prod" ]; then
        PROD=1
    else
        ARGS+=("$arg")
    fi
done
set -- "${ARGS[@]+"${ARGS[@]}"}"

if [ "$PROD" = "1" ]; then
    OMNISAVE_ROOT="/mnt/srv/omnisave"
else
    OMNISAVE_ROOT="/mnt/srv/omnisavedev"
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_SRC="${REPO_ROOT}/deploy/compose.yml"
ENV_FILE="${OMNISAVE_ROOT}/.env"

usage() {
    cat <<EOF
Usage: $(basename "$0") [--prod] <command>

Flags:
  --prod  Target the PRODUCTION instance (/mnt/srv/omnisave).
          Omit to target dev (/mnt/srv/omnisavedev) — the safe default.

Commands:
  init    Create ${OMNISAVE_ROOT}/data and install compose + .env
  up      Build and start the server (detached)
  down    Stop the server
  logs    Follow container logs
  ps      Show compose status

Environment (in ${ENV_FILE}):
  OMNISAVE_REPO        Git checkout path
  OMNISAVE_HOST        Server hostname
  OMNISAVE_PUBLIC_URL  Optional public URL
  OMNISAVE_SWITCHES         Switch FTP hosts for deploy.sh
  OMNISAVE_DOCKER_NETWORK   External network (default: selfhost)
  OMNISAVE_PORT_PUBLISH     Host port mapped to the container

Examples:
  $(basename "$0") init          # dev
  $(basename "$0") up            # dev
  $(basename "$0") --prod up     # PRODUCTION — requires explicit user approval
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

    mkdir -p "${OMNISAVE_ROOT}/data"
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
    sed -i "s/container_name: omnisave$/container_name: ${SAFE_CONTAINER_NAME}/" "${OMNISAVE_ROOT}/compose.yml"
    PORT_PUBLISH=$(grep "^OMNISAVE_PORT_PUBLISH=" "${ENV_FILE}" | cut -d= -f2)
    PORT_PUBLISH="${PORT_PUBLISH:-8991}"
    sed -i "s/\"8991:8991\"/\"${PORT_PUBLISH}:8991\"/" "${OMNISAVE_ROOT}/compose.yml"

    GIT_SHA=$(git -C "$REPO_ROOT" rev-parse --short=8 HEAD 2>/dev/null || echo "unknown")
    git -C "$REPO_ROOT" diff --quiet HEAD 2>/dev/null || GIT_SHA="${GIT_SHA}-dirty"
    export GIT_SHA
    compose up -d --build --remove-orphans

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
