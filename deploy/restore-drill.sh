#!/usr/bin/env bash
# Restore drill: prove the newest backup can be restored without the server.
#
#   make restore-drill
#
# Runs on your machine with your own OCI API key (~/.oci/config), never through the
# host. It restores the latest snapshot into a throwaway Postgres container, checks it,
# and removes the container. Fails if the newest snapshot is older than 36 hours.
#
# Needs Docker, ~/.oci/config, and the restic password at
# ~/.config/wiredex/restic-password (keep a copy in your password manager as well).
# restic and rclone are fetched into ~/.local/bin, pinned and checksum-verified,
# when missing. Keep the versions in sync with deploy/server-setup.sh.
set -euo pipefail

RESTIC_VERSION=0.19.1
RESTIC_SHA256=f415415624dcc452f2a02b8c33641791a8c6d6d3b65bbb3543fcf9a25151585c
RCLONE_VERSION=1.75.1
RCLONE_SHA256=982b5aa772841168f8e380f139e9e787b2a105403e32b94da8676a0e1c0a13ab
POSTGRES_IMAGE=postgres:18.6-alpine
MAX_AGE_HOURS=36
OCI_NAMESPACE=idtgsqumsw81
BIN="$HOME/.local/bin"
CONTAINER="wiredex-restore-drill-$$"

log() { printf '\n== %s\n' "$*"; }
oci_config_value() { sed -n "s/^$1=//p" "$HOME/.oci/config" | head -1; }

ensure_tools() {
  mkdir -p "$BIN"
  export PATH="$BIN:$PATH"
  local work
  work=$(mktemp -d)
  if [[ "$(restic version 2>/dev/null | awk '{print $2}')" != "$RESTIC_VERSION" ]]; then
    curl -fsSL "https://github.com/restic/restic/releases/download/v$RESTIC_VERSION/restic_${RESTIC_VERSION}_linux_amd64.bz2" -o "$work/restic.bz2"
    echo "$RESTIC_SHA256  $work/restic.bz2" | sha256sum --check --quiet
    bunzip2 "$work/restic.bz2" && install -m 755 "$work/restic" "$BIN/restic"
  fi
  if [[ "$(rclone version 2>/dev/null | awk 'NR==1 {print $2}')" != "v$RCLONE_VERSION" ]]; then
    curl -fsSL "https://github.com/rclone/rclone/releases/download/v$RCLONE_VERSION/rclone-v$RCLONE_VERSION-linux-amd64.zip" -o "$work/rclone.zip"
    echo "$RCLONE_SHA256  $work/rclone.zip" | sha256sum --check --quiet
    (cd "$work" && python3 -m zipfile -e rclone.zip .)
    install -m 755 "$work/rclone-v$RCLONE_VERSION-linux-amd64/rclone" "$BIN/rclone"
  fi
  rm -rf "$work"
}

cleanup() { docker rm --force "$CONTAINER" >/dev/null 2>&1 || true; }
trap cleanup EXIT

ensure_tools

# An rclone remote defined in the environment, authenticating as you (not the VM).
export RCLONE_CONFIG=/dev/null # the remote is defined entirely by the variables below
export RCLONE_CONFIG_WIREDEXBACKUP_TYPE=oracleobjectstorage
export RCLONE_CONFIG_WIREDEXBACKUP_PROVIDER=user_principal_auth
export RCLONE_CONFIG_WIREDEXBACKUP_NAMESPACE="$OCI_NAMESPACE"
RCLONE_CONFIG_WIREDEXBACKUP_COMPARTMENT=$(oci_config_value tenancy)
RCLONE_CONFIG_WIREDEXBACKUP_REGION=$(oci_config_value region)
export RCLONE_CONFIG_WIREDEXBACKUP_COMPARTMENT RCLONE_CONFIG_WIREDEXBACKUP_REGION
export RCLONE_CONFIG_WIREDEXBACKUP_CONFIG_FILE="$HOME/.oci/config"
export RCLONE_CONFIG_WIREDEXBACKUP_CONFIG_PROFILE=DEFAULT
export RESTIC_REPOSITORY="rclone:wiredexbackup:wiredex-backups/restic"
export RESTIC_PASSWORD_FILE="${WIREDEX_RESTIC_PASSWORD_FILE:-$HOME/.config/wiredex/restic-password}"

log "Newest snapshot"
restic snapshots --tag postgres --latest 1 --compact
latest=$(restic snapshots --tag postgres --latest 1 --json)
age_hours=$(python3 -c '
import datetime, json, sys
snapshot = json.loads(sys.argv[1])[-1]
taken = datetime.datetime.fromisoformat(snapshot["time"].replace("Z", "+00:00"))
print(int((datetime.datetime.now(datetime.UTC) - taken).total_seconds() // 3600))
' "$latest")
echo "taken ${age_hours} h ago (limit ${MAX_AGE_HOURS} h)"
((age_hours <= MAX_AGE_HOURS)) || { echo "FAIL: the newest backup is too old" >&2; exit 1; }

log "Restoring into a throwaway $POSTGRES_IMAGE"
docker run --detach --name "$CONTAINER" --env POSTGRES_PASSWORD=drill "$POSTGRES_IMAGE" >/dev/null
until docker exec "$CONTAINER" pg_isready --username=postgres --quiet; do sleep 1; done
restic dump --tag postgres latest wiredex.dump |
  docker exec --interactive "$CONTAINER" \
    pg_restore --username=postgres --dbname=postgres --create --no-owner --no-privileges --exit-on-error

log "Checking the restored database"
docker exec "$CONTAINER" psql --username=postgres --dbname=wiredex --tuples-only --no-align --command \
  "SELECT 'tables: ' || count(*) FROM information_schema.tables WHERE table_schema = 'public'
   UNION ALL SELECT 'size: ' || pg_size_pretty(pg_database_size('wiredex'))"

log "Restore drill passed"
