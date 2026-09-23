#!/usr/bin/env bash
# One-time setup of the OCI host for Wiredex. Safe to run again: every step checks
# before it changes anything. Run as a sudoer, passing the CI deploy key's public half:
#
#   ssh corvax "sudo DEPLOY_PUBLIC_KEY='ssh-ed25519 AAAA… wiredex-deploy' bash -s" < deploy/server-setup.sh
#
# What it does:
#   1. Installs Docker Engine and the Compose plugin from Docker's apt repository,
#      with rotated logs and live-restore.
#   2. Creates the `wiredex` deploy user: SSH key only, in the docker group, and
#      allowed exactly one sudo command, `systemctl reload caddy`.
#   3. Creates /srv/wiredex and a .env with a generated Postgres password that never
#      leaves this host.
#   4. Makes Caddy import /etc/caddy/sites/*.caddy; the deploy user owns wiredex.caddy.
#   5. Caps journald at 200 MB on disk (it was the biggest process on this host).
set -euo pipefail

DEPLOY_USER=wiredex
ROOT=/srv/wiredex
: "${DEPLOY_PUBLIC_KEY:?set DEPLOY_PUBLIC_KEY to the CI deploy key (ssh-ed25519 ...)}"

step() { printf '\n== %s\n' "$*"; }

step "1/5 Docker Engine and Compose plugin"
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck source=/dev/null
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    >/etc/apt/sources.list.d/docker.list
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
else
  echo "already installed: $(docker --version)"
fi
daemon_json='{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "live-restore": true
}'
if [[ "$(cat /etc/docker/daemon.json 2>/dev/null)" != "$daemon_json" ]]; then
  echo "$daemon_json" >/etc/docker/daemon.json
  systemctl restart docker
fi
systemctl enable --now docker >/dev/null

step "2/5 Deploy user '$DEPLOY_USER'"
id "$DEPLOY_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$DEPLOY_USER"
passwd --lock "$DEPLOY_USER" >/dev/null # no password login, SSH key only
usermod --append --groups docker "$DEPLOY_USER"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
echo "$DEPLOY_PUBLIC_KEY" >"/home/$DEPLOY_USER/.ssh/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh/authorized_keys"
chmod 600 "/home/$DEPLOY_USER/.ssh/authorized_keys"
sudoers="$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl reload caddy"
echo "$sudoers" >/etc/sudoers.d/wiredex-deploy
chmod 440 /etc/sudoers.d/wiredex-deploy
visudo --check --file=/etc/sudoers.d/wiredex-deploy >/dev/null

step "3/5 $ROOT and its secrets"
install -d -m 755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$ROOT" "$ROOT/bin" "$ROOT/caddy" "$ROOT/web" "$ROOT/web/releases"
if [[ ! -f "$ROOT/.env" ]]; then
  password=$(openssl rand -hex 24)
  cat >"$ROOT/.env" <<EOF
# Created by server-setup.sh. Never commit or copy this file off the host.
POSTGRES_USER=wiredex
POSTGRES_DB=wiredex
POSTGRES_PASSWORD=$password
WIREDEX_DATABASE_URL=postgresql+asyncpg://wiredex:$password@db:5432/wiredex
EOF
  echo "generated a new Postgres password"
else
  echo ".env exists, left untouched"
fi
chown "$DEPLOY_USER:$DEPLOY_USER" "$ROOT/.env"
chmod 600 "$ROOT/.env"

step "4/5 Caddy imports per-site files"
install -d -m 755 /etc/caddy/sites
if [[ ! -f /etc/caddy/sites/wiredex.caddy ]]; then
  echo "# Written by /srv/wiredex/bin/deploy.sh on the first deploy." >/etc/caddy/sites/wiredex.caddy
fi
chown "$DEPLOY_USER:$DEPLOY_USER" /etc/caddy/sites/wiredex.caddy
chmod 644 /etc/caddy/sites/wiredex.caddy
if ! grep -q '^import /etc/caddy/sites/\*.caddy' /etc/caddy/Caddyfile; then
  cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak-$(date +%Y%m%d%H%M%S)"
  printf '\n# Per-project sites (e.g. Wiredex, deployed from its own repository).\nimport /etc/caddy/sites/*.caddy\n' >>/etc/caddy/Caddyfile
fi
caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile >/dev/null
systemctl reload caddy

step "5/5 journald size cap"
install -d /etc/systemd/journald.conf.d
journald_conf=$'[Journal]\nSystemMaxUse=200M\nRuntimeMaxUse=50M'
if [[ "$(cat /etc/systemd/journald.conf.d/wiredex-size.conf 2>/dev/null)" != "$journald_conf" ]]; then
  echo "$journald_conf" >/etc/systemd/journald.conf.d/wiredex-size.conf
  systemctl restart systemd-journald
  journalctl --vacuum-size=200M >/dev/null 2>&1 || true
fi

step "done"
echo "docker: $(docker --version)"
echo "memory available: $(free -m | awk '/^Mem:/ {print $7}') MB"
