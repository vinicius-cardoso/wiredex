#!/usr/bin/env bash
# Deploys one build of Wiredex on this host. The Release workflow uploads the files
# and runs it over SSH as the deploy user:
#
#   /srv/wiredex/bin/deploy.sh <tag>        e.g. v0.1.0 or sha-1a2b3c4
#
# Before calling it, the workflow has put in /srv/wiredex:
#   compose.yml            deploy/compose.prod.yml
#   caddy/wiredex.caddy    deploy/wiredex.caddy
#   web/releases/<tag>/    the web build for this tag
#
# Order: Caddy site → database → new API → wait for /api/health/ready → switch the
# web build → record the tag. If the new API never gets ready, the previous API is
# started again and the web build is left as it was.
set -euo pipefail

TAG=${1:?usage: deploy.sh <tag>}
ROOT=/srv/wiredex
READY_URL=http://127.0.0.1:8100/api/health/ready
CADDY_SITE=/etc/caddy/sites/wiredex.caddy

cd "$ROOT"

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$ROOT/deploy.log"; }
compose() { WIREDEX_TAG="$1" docker compose --file compose.yml "${@:2}"; }

wait_until_ready() {
  for _ in $(seq 1 60); do
    if curl --silent --fail --max-time 2 "$READY_URL" >/dev/null; then return 0; fi
    sleep 1
  done
  return 1
}

# Hosts set up before v0.2 have one .env, whose WIREDEX_DATABASE_URL is the schema
# owner. Split it once: the owner's login stays in .env for migrations, and the API
# gets its own login as wiredex_app in api.env. `wiredex db upgrade` then sets that
# role's password from api.env.
split_database_logins() {
  if [[ -f api.env ]]; then return 0; fi
  local app_password
  app_password=$(openssl rand -hex 24)
  (
    umask 077
    {
      echo "# The API logs in as wiredex_app (ADR 0007). Never copy this file off the host."
      echo "WIREDEX_DATABASE_URL=postgresql+asyncpg://wiredex_app:$app_password@db:5432/wiredex"
    } >api.env.new
  )
  sed -i 's/^WIREDEX_DATABASE_URL=/WIREDEX_ADMIN_DATABASE_URL=/' .env
  mv api.env.new api.env
  log "split the database logins: the API's is now in api.env"
}

update_caddy_site() {
  if cmp --silent caddy/wiredex.caddy "$CADDY_SITE"; then return 0; fi
  cp caddy/wiredex.caddy "$CADDY_SITE"
  # `caddy reload` validates first and keeps the running config if the new one is bad.
  sudo --non-interactive /usr/bin/systemctl reload caddy
  log "Caddy site updated"
}

rollback() {
  local previous=$1
  if [[ -z "$previous" ]]; then
    log "no previous version to roll back to"
    return 1
  fi
  compose "$previous" up --detach api
  if wait_until_ready; then log "rolled back to $previous"; else log "$previous is not ready either"; fi
}

[[ -d "web/releases/$TAG" ]] || { log "no web build at web/releases/$TAG"; exit 1; }
previous=$(cat current-tag 2>/dev/null || true)
log "deploying $TAG (previous: ${previous:-none})"

split_database_logins
update_caddy_site
compose "$TAG" pull --quiet api
compose "$TAG" up --detach --wait db
# Migrate with the new image before its API starts. Migrations must stay compatible
# with the previous version (expand, then contract in a later release), because a
# failed deploy rolls back the API but never the schema.
log "migrating the database"
compose "$TAG" run --rm migrate
compose "$TAG" up --detach api

if ! wait_until_ready; then
  log "$TAG never became ready; last API log lines:"
  compose "$TAG" logs --tail 40 api 2>&1 | tee -a "$ROOT/deploy.log" >&2 || true
  rollback "$previous" || true
  exit 1
fi

# Swap the web build atomically: make a new symlink, then rename it over the old one.
ln -sfn "releases/$TAG" web/current.new
mv --no-target-directory web/current.new web/current
echo "$TAG" >current-tag
log "$TAG is live"

# Keep the five newest web builds, and images from the last 30 days for rollbacks.
find web/releases -mindepth 1 -maxdepth 1 -type d -printf '%T@ %f\n' | sort -rn | tail -n +6 |
  while read -r _ old; do rm -rf "web/releases/$old"; done
docker image prune --all --force --filter "until=720h" >/dev/null
