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
#   3. Creates /srv/wiredex with .env (Postgres, the schema owner) and api.env (the
#      API's wiredex_app login), with generated passwords that never leave this host.
#   4. Makes Caddy import /etc/caddy/sites/*.caddy; the deploy user owns wiredex.caddy.
#   5. Caps journald at 200 MB on disk (it was the biggest process on this host).
#   6. Backups, when OCI_NAMESPACE is set: pinned, checksum-verified restic and rclone,
#      an rclone remote that authenticates as this VM (instance principal, no stored
#      key), and a nightly systemd timer running /srv/wiredex/bin/backup.sh.
#      The restic password is uploaded separately (deploy/README.md) and never
#      generated here, so a copy always exists off the host.
#   7. A nightly timer running `wiredex demo reset` (expired guests) and then
#      `wiredex files prune` (orphaned files), ADR 0011.
#
#   ssh corvax "sudo DEPLOY_PUBLIC_KEY='…' OCI_NAMESPACE=idtgsqumsw81 BACKUP_CHECK_PUBLIC_KEY='…' bash -s" < deploy/server-setup.sh
set -euo pipefail

DEPLOY_USER=wiredex
ROOT=/srv/wiredex
: "${DEPLOY_PUBLIC_KEY:?set DEPLOY_PUBLIC_KEY to the CI deploy key (ssh-ed25519 ...)}"

step() { printf '\n== %s\n' "$*"; }

step "1/7 Docker Engine and Compose plugin"
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

step "2/7 Deploy user '$DEPLOY_USER'"
id "$DEPLOY_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$DEPLOY_USER"
passwd --lock "$DEPLOY_USER" >/dev/null # no password login, SSH key only
usermod --append --groups docker "$DEPLOY_USER"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
{
  echo "$DEPLOY_PUBLIC_KEY"
  # Optional monitoring key for the scheduled "Backup check" workflow. `restrict` and a
  # forced command mean it can only print the last backup time: no shell, no Docker.
  if [[ -n "${BACKUP_CHECK_PUBLIC_KEY:-}" ]]; then
    echo "restrict,command=\"cat $ROOT/backup/last-success\" $BACKUP_CHECK_PUBLIC_KEY"
  fi
} >"/home/$DEPLOY_USER/.ssh/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh/authorized_keys"
chmod 600 "/home/$DEPLOY_USER/.ssh/authorized_keys"
sudoers="$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl reload caddy"
echo "$sudoers" >/etc/sudoers.d/wiredex-deploy
chmod 440 /etc/sudoers.d/wiredex-deploy
visudo --check --file=/etc/sudoers.d/wiredex-deploy >/dev/null

step "3/7 $ROOT and its secrets"
install -d -m 755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$ROOT" "$ROOT/bin" "$ROOT/caddy" "$ROOT/web" "$ROOT/web/releases"
if [[ ! -f "$ROOT/.env" ]]; then
  owner_password=$(openssl rand -hex 24)
  app_password=$(openssl rand -hex 24)
  cat >"$ROOT/.env" <<EOF
# Created by server-setup.sh. Never commit or copy this file off the host.
# Postgres and the schema owner's login, for the db and migrate services only.
POSTGRES_USER=wiredex
POSTGRES_DB=wiredex
POSTGRES_PASSWORD=$owner_password
WIREDEX_ADMIN_DATABASE_URL=postgresql+asyncpg://wiredex:$owner_password@db:5432/wiredex
EOF
  cat >"$ROOT/api.env" <<EOF
# Created by server-setup.sh. Never commit or copy this file off the host.
# The API logs in as wiredex_app (ADR 0007); "wiredex db upgrade" sets its password.
WIREDEX_DATABASE_URL=postgresql+asyncpg://wiredex_app:$app_password@db:5432/wiredex
EOF
  echo "generated new database passwords"
else
  echo ".env exists, left untouched (deploy.sh creates api.env from it if missing)"
fi
for secrets in "$ROOT/.env" "$ROOT/api.env"; do
  if [[ -f "$secrets" ]]; then
    chown "$DEPLOY_USER:$DEPLOY_USER" "$secrets"
    chmod 600 "$secrets"
  fi
done

step "4/7 Caddy imports per-site files"
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

step "5/7 journald size cap"
install -d /etc/systemd/journald.conf.d
journald_conf=$'[Journal]\nSystemMaxUse=200M\nRuntimeMaxUse=50M'
if [[ "$(cat /etc/systemd/journald.conf.d/wiredex-size.conf 2>/dev/null)" != "$journald_conf" ]]; then
  echo "$journald_conf" >/etc/systemd/journald.conf.d/wiredex-size.conf
  systemctl restart systemd-journald
  journalctl --vacuum-size=200M >/dev/null 2>&1 || true
fi

step "6/7 Backups"
RESTIC_VERSION=0.19.1
RESTIC_SHA256=f415415624dcc452f2a02b8c33641791a8c6d6d3b65bbb3543fcf9a25151585c
RCLONE_VERSION=1.75.1
RCLONE_SHA256=982b5aa772841168f8e380f139e9e787b2a105403e32b94da8676a0e1c0a13ab

if [[ -z "${OCI_NAMESPACE:-}" ]]; then
  echo "skipped: set OCI_NAMESPACE to set up backups"
else
  download() { # url sha256 output
    curl -fsSL "$1" -o "$3"
    echo "$2  $3" | sha256sum --check --quiet
  }
  workdir=$(mktemp -d)
  if [[ "$(restic version 2>/dev/null | awk '{print $2}')" != "$RESTIC_VERSION" ]]; then
    download "https://github.com/restic/restic/releases/download/v$RESTIC_VERSION/restic_${RESTIC_VERSION}_linux_amd64.bz2" \
      "$RESTIC_SHA256" "$workdir/restic.bz2"
    bunzip2 "$workdir/restic.bz2"
    install -m 755 "$workdir/restic" /usr/local/bin/restic
  fi
  if [[ "$(rclone version 2>/dev/null | awk 'NR==1 {print $2}')" != "v$RCLONE_VERSION" ]]; then
    download "https://github.com/rclone/rclone/releases/download/v$RCLONE_VERSION/rclone-v$RCLONE_VERSION-linux-amd64.zip" \
      "$RCLONE_SHA256" "$workdir/rclone.zip"
    (cd "$workdir" && python3 -m zipfile -e rclone.zip .)
    install -m 755 "$workdir/rclone-v$RCLONE_VERSION-linux-amd64/rclone" /usr/local/bin/rclone
  fi
  rm -rf "$workdir"
  echo "restic $(restic version | awk '{print $2}'), rclone $(rclone version | awk 'NR==1 {print $2}')"

  install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$ROOT/backup" "$ROOT/backup/cache"
  metadata=$(curl -fsS -H "Authorization: Bearer Oracle" http://169.254.169.254/opc/v2/instance/)
  region=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["canonicalRegionName"])' <<<"$metadata")
  compartment=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["compartmentId"])' <<<"$metadata")
  cat >"$ROOT/backup/rclone.conf" <<RCLONE
# Written by server-setup.sh. Authenticates as this VM: no key is stored here.
[oci]
type = oracleobjectstorage
provider = instance_principal_auth
namespace = $OCI_NAMESPACE
compartment = $compartment
region = $region
RCLONE
  chown "$DEPLOY_USER:$DEPLOY_USER" "$ROOT/backup/rclone.conf"
  chmod 600 "$ROOT/backup/rclone.conf"

  cat >/etc/systemd/system/wiredex-backup.service <<'UNIT'
[Unit]
Description=Back up the Wiredex database to OCI Object Storage
Wants=network-online.target
After=network-online.target docker.service

[Service]
Type=oneshot
User=wiredex
Group=wiredex
ExecStart=/srv/wiredex/bin/backup.sh
# Stay out of the way of the API on a small host.
Nice=10
IOSchedulingClass=idle
UNIT
  cat >/etc/systemd/system/wiredex-backup.timer <<'UNIT'
[Unit]
Description=Nightly Wiredex database backup

[Timer]
# 03:30 in Brazil. Persistent: a run missed while the host was down happens at boot.
# No RandomizedDelaySec: on systemd 249 a daemon-reload between the calendar time and
# the delayed time (apt's timers reload at random hours) silently moves the run to the
# next day. That skipped the first scheduled backup on 2026-09-23.
OnCalendar=*-*-* 06:30:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
UNIT
  systemctl daemon-reload
  systemctl enable wiredex-backup.timer >/dev/null
  # Restart, not just start: a running timer keeps its old schedule otherwise.
  systemctl restart wiredex-backup.timer
  echo "next backup: $(systemctl show wiredex-backup.timer --property=NextElapseUSecRealtime --value)"
  [[ -f "$ROOT/backup/restic-password" ]] || echo "WARNING: $ROOT/backup/restic-password is missing; upload it before the first run"
fi

step "7/7 Nightly demo reset and file prune"
cat >/etc/systemd/system/wiredex-demo-reset.service <<'UNIT'
[Unit]
Description=Reset Wiredex demo data and prune orphaned files
Wants=network-online.target
After=network-online.target docker.service

[Service]
Type=oneshot
User=wiredex
Group=wiredex
# Two steps, in order (Type=oneshot runs each ExecStart to completion): first drop
# expired guests and reset their benches, then delete files no attachment names and
# the objects behind them, this reset included.
ExecStart=/srv/wiredex/bin/wiredex demo reset
ExecStart=/srv/wiredex/bin/wiredex files prune
Nice=10
UNIT
cat >/etc/systemd/system/wiredex-demo-reset.timer <<'UNIT'
[Unit]
Description=Nightly Wiredex demo reset

[Timer]
# 03:00 in Brazil, before the backup. No RandomizedDelaySec: see wiredex-backup.timer.
OnCalendar=*-*-* 06:00:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable wiredex-demo-reset.timer >/dev/null
systemctl restart wiredex-demo-reset.timer
echo "next demo reset: $(systemctl show wiredex-demo-reset.timer --property=NextElapseUSecRealtime --value)"

step "done"
echo "docker: $(docker --version)"
echo "memory available: $(free -m | awk '/^Mem:/ {print $7}') MB"
