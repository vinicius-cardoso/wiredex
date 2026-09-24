# Deploying Wiredex

Wiredex runs on the same OCI VM as [vinilabs.cc](https://vinilabs.cc) (`corvax`,
`VM.Standard.E2.1.Micro`, under 1 GB of RAM). The host's Caddy serves the static app
and proxies `/api/*` to the API container. Postgres runs next to it in Docker. Nothing
is built on the server. See [ADR 0009](../docs/adr/0009-single-host-deployment.md).

```
GitHub Actions (Release workflow)
  build ──► API image ─► Trivy ─► ghcr.io/vinicius-cardoso/wiredex-api:<tag>
        └─► web build (artifact)
  deploy ─► rsync to wiredex@host:/srv/wiredex ─► bin/deploy.sh <tag> ─► smoke test
```

## Files in this folder

| File | Installed as | Purpose |
| --- | --- | --- |
| `compose.prod.yml` | `/srv/wiredex/compose.yml` | Postgres and the API, with memory limits and a hardened API container |
| `wiredex.caddy` | `/etc/caddy/sites/wiredex.caddy` | The site: TLS, strict CSP, caching, `/api/*` proxy |
| `deploy.sh` | `/srv/wiredex/bin/deploy.sh` | One deploy: start the API, wait for readiness, swap the web build, roll back on failure |
| `server-setup.sh` | *(run once)* | Docker, the `wiredex` deploy user, `/srv/wiredex`, Caddy import, journald cap, backups |
| `backup.sh` | `/srv/wiredex/bin/backup.sh` | Nightly `pg_dump` → restic → OCI Object Storage, with retention |
| `restore-drill.sh` | *(your machine)* | `make restore-drill`: restore the newest backup into a throwaway Postgres |

## Everyday use

- **Deploy a release:** merge the release PR. The Release workflow tags it,
  builds, scans and deploys, then checks `https://wiredex.vinilabs.cc/api/version`
  for the exact commit.
- **Redeploy or roll back:** *Actions → Release → Run workflow* with a ref, e.g.
  `v0.1.0`. Any ref works. Non-release refs deploy as `sha-<short>`.
- **See what's live:** `ssh corvax cat /srv/wiredex/current-tag`, or the footer of
  the app.
- **Deploy history:** `ssh corvax tail /srv/wiredex/deploy.log`.

## Backups

Every night at 03:30 Brazil time (06:30 UTC, exactly), `wiredex-backup.timer` runs
`backup.sh` as the `wiredex` user:

```
pg_dump -Fc (inside the db container) ─► restic (encrypted, deduplicated)
  ─► rclone ─► OCI bucket wiredex-backups/restic   (instance principal: no stored key)
retention: 7 daily, 4 weekly, 6 monthly · Sundays: restic check re-reads 10 % of the data
```

- **Authentication.** The VM authenticates as itself. Dynamic group
  `wiredex-backup-host` matches only this instance, and policy `wiredex-backups`
  lets it read that bucket and manage its objects, nothing else in the account.
- **The restic password** is the one secret, at `/srv/wiredex/backup/restic-password`
  on the host and `~/.config/wiredex/restic-password` on the owner's machine, with a
  third copy in a password manager. **Without it the backups can't be decrypted.**
- **A failed `pg_dump` fails the snapshot** (`--stdin-from-command`), so a broken dump
  never replaces a good one.
- **Stale backups raise an alert.** The *Backup check* workflow runs daily at 12:00 UTC
  and fails when the newest backup is more than 26 hours old, so GitHub emails the
  owner. It uses its own SSH key (repo secret `BACKUP_CHECK_SSH_KEY`), which
  `authorized_keys` pins with `restrict` and a forced command: it can only print
  `last-success`. It can't open a shell, run Docker or forward ports.
- **No random delay on the timer.** On systemd 249, a `daemon-reload` between the
  calendar time and a `RandomizedDelaySec` delay moves the run to the next day. apt's
  timers reload systemd at random hours, and that skipped the first scheduled backup.
- **Check it:** `ssh corvax cat /srv/wiredex/backup/last-success` and
  `ssh corvax journalctl -u wiredex-backup --since today`. Run one now with
  `ssh corvax sudo systemctl start wiredex-backup`.

### Restore drill

```bash
make restore-drill
```

It runs on your machine with your own OCI API key, so it proves the backups are
recoverable **without the host**. It restores the newest snapshot into a throwaway
Postgres container, checks it, and fails if that snapshot is older than 36 hours.
Run it after changing anything about backups, and now and then anyway.

### Recovering on a new host

1. Run `server-setup.sh` on the new host (with `OCI_NAMESPACE`), and update the
   dynamic group's rule to the new instance OCID.
2. Upload the restic password to `/srv/wiredex/backup/restic-password`.
3. Deploy any version (*Run workflow*), which starts an empty database.
4. Restore into it:

   ```bash
   restic dump --tag postgres latest wiredex.dump |
     docker compose --file compose.yml exec -T db \
     pg_restore --username=wiredex --dbname=wiredex --clean --if-exists --exit-on-error
   ```

5. Point the DNS record at the new IP.

## How a deploy can fail, and what happens

| Failure | Result |
| --- | --- |
| Trivy finds a fixable HIGH/CRITICAL vulnerability | Nothing is pushed or deployed |
| The new API never answers `/api/health/ready` within 60 s | The previous tag starts again. The web build and `current-tag` stay as they were. The workflow fails and the API's last log lines are in the job output and `deploy.log` |
| The Caddy site file is invalid | `caddy reload` refuses it and keeps the running config. The deploy stops before touching the API |
| The public smoke test doesn't see the new commit | The workflow fails. The host is serving whatever `current-tag` says |

## One-time setup (already done)

Recorded so a new host can be set up the same way.

1. **DNS:** an `A` record `wiredex` → the host's IP in Cloudflare, *DNS only* (grey
   cloud), so Caddy can get the certificate.
2. **GitHub environment `production`** (deploys allowed from `main` only):
   - secret `DEPLOY_SSH_KEY`: private half of a dedicated ed25519 key, used only by CI
   - secret `DEPLOY_KNOWN_HOSTS`: the host's pinned `ssh-ed25519` key
     (`ssh-keyscan -t ed25519 <ip>`, checked against a trusted fingerprint)
   - variables `DEPLOY_HOST` (the IP) and `DEPLOY_USER` (`wiredex`)
3. **The host:**

   ```bash
   ssh corvax "sudo DEPLOY_PUBLIC_KEY='ssh-ed25519 AAAA… wiredex-deploy' bash -s" < deploy/server-setup.sh
   ```

   It's idempotent, so running it again is safe. It never overwrites `/srv/wiredex/.env`,
   which holds the generated Postgres password and never leaves the host.
4. **Backups (OCI):** bucket `wiredex-backups` (private, Standard tier), dynamic
   group `wiredex-backup-host` (`instance.id = '<this VM>'`), and policy
   `wiredex-backups`:

   ```
   Allow dynamic-group wiredex-backup-host to read buckets in tenancy where target.bucket.name = 'wiredex-backups'
   Allow dynamic-group wiredex-backup-host to manage objects in tenancy where target.bucket.name = 'wiredex-backups'
   ```

5. **GHCR:** the `wiredex-api` package is **public**, so the host pulls without a
   token. The image contains no secrets.

## Security notes

- The `wiredex` user logs in with its key only. It can run Docker, which is
  root-equivalent on this host, and its only `sudo` right is `systemctl reload caddy`.
- The API and Postgres listen on loopback only. Caddy is the one way in.
- The API container is read-only, has no Linux capabilities, can't gain privileges,
  and runs as uid 10001.
