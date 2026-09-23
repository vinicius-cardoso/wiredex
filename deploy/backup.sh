#!/usr/bin/env bash
# Nightly backup of the Wiredex database. wiredex-backup.timer runs it as the deploy user.
#
# pg_dump (custom format) streams straight into restic: encrypted, deduplicated, and sent
# to the OCI bucket through rclone. rclone authenticates as this VM (instance principal),
# so no API key or secret access key lives on the host. Only the restic password does.
#
# restic's --stdin-from-command fails the snapshot when pg_dump fails, so a broken dump
# never replaces a good one.
set -euo pipefail

ROOT=/srv/wiredex
export RESTIC_REPOSITORY="rclone:oci:wiredex-backups/restic"
export RESTIC_PASSWORD_FILE="$ROOT/backup/restic-password"
export RESTIC_CACHE_DIR="$ROOT/backup/cache"
export RCLONE_CONFIG="$ROOT/backup/rclone.conf"
# compose.yml needs a tag to parse; the database service doesn't depend on it.
WIREDEX_TAG=$(cat "$ROOT/current-tag")
export WIREDEX_TAG

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }

cd "$ROOT"

if ! restic cat config >/dev/null 2>&1; then
  log "initialising the restic repository"
  restic init
fi

log "backing up the database"
# shellcheck disable=SC2016 # $POSTGRES_* expand inside the db container, on purpose
restic backup --quiet --host wiredex --tag postgres \
  --stdin-filename wiredex.dump \
  --stdin-from-command -- \
  docker compose --file compose.yml exec -T db \
  sh -c 'pg_dump --format=custom --username="$POSTGRES_USER" "$POSTGRES_DB"'

log "applying retention: 7 daily, 4 weekly, 6 monthly"
restic forget --quiet --tag postgres --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune

# Sundays: re-read a tenth of the stored data to catch silent corruption.
if [[ "$(date -u +%u)" == 7 ]]; then
  log "weekly integrity check"
  restic check --read-data-subset=10%
fi

date -u +%FT%TZ >"$ROOT/backup/last-success"
log "done: $(restic snapshots --tag postgres --latest 1 --compact | grep -E '^[0-9a-f]{8} ')"
