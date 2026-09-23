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
| `server-setup.sh` | *(run once)* | Docker, the `wiredex` deploy user, `/srv/wiredex`, Caddy import, journald cap |

## Everyday use

- **Deploy a release:** merge the release PR. The Release workflow tags it,
  builds, scans and deploys, then checks `https://wiredex.vinilabs.cc/api/version`
  for the exact commit.
- **Redeploy or roll back:** *Actions → Release → Run workflow* with a ref, e.g.
  `v0.1.0`. Any ref works. Non-release refs deploy as `sha-<short>`.
- **See what's live:** `ssh corvax cat /srv/wiredex/current-tag`, or the footer of
  the app.
- **Deploy history:** `ssh corvax tail /srv/wiredex/deploy.log`.

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
4. **GHCR:** the `wiredex-api` package is **public**, so the host pulls without a
   token. The image contains no secrets.

## Security notes

- The `wiredex` user logs in with its key only. It can run Docker, which is
  root-equivalent on this host, and its only `sudo` right is `systemctl reload caddy`.
- The API and Postgres listen on loopback only. Caddy is the one way in.
- The API container is read-only, has no Linux capabilities, can't gain privileges,
  and runs as uid 10001.
