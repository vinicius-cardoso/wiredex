#!/usr/bin/env bash
# Runs a `wiredex` command in the image of the release that's live, e.g.
#
#   /srv/wiredex/bin/wiredex users create --email you@example.com --name "You"
#   /srv/wiredex/bin/wiredex demo invite --email friend@example.com --expires 7d
#
# It uses the API's own login (api.env, the wiredex_app role). wiredex-demo-reset.timer
# runs `demo reset` through it every night.
set -euo pipefail

ROOT=/srv/wiredex
cd "$ROOT"
WIREDEX_TAG=$(cat current-tag)
export WIREDEX_TAG

# A terminal when there is one (password prompts), none under systemd.
tty=()
[[ -t 0 ]] || tty=(-T)
exec docker compose --file compose.yml run --rm --no-deps "${tty[@]}" api wiredex "$@"
