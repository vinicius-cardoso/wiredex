# Running your own Wiredex

**English** · [Português (Brasil)](self-hosting.pt-BR.md)

Wiredex is built for one person's bench, and runs on a very small server: the instance at
wiredex.vinilabs.cc is a VM with under 1 GB of RAM. This guide takes you from a fork to a
running copy of your own. [deploy/README.md](../deploy/README.md) is the runbook for that
one instance, and is the reference when a step here needs more detail.

There is no public sign-up and no multi-tenant mode: you create accounts from the command
line, and each account gets its own workspace ([ADR 0008](adr/0008-sessions.md)).

## What you need

| What | Why |
| --- | --- |
| A Linux host with a public IP, 1 GB of RAM or less is enough | Runs Docker (Postgres and the API) and Caddy |
| A domain name pointing at it | Caddy gets the TLS certificate for it |
| An S3-compatible bucket and an access key limited to it | Attachments (datasheets, photos, Gerbers) live there, not on the host's disk. In production the API refuses to start without it |
| A fork of this repository on GitHub | The release workflow builds the image and deploys it |
| A second bucket, optional | Nightly encrypted backups |

Any S3-compatible storage works: the instance uses Oracle Cloud Object Storage through its
S3 API, and MinIO, Backblaze B2 or AWS S3 answer the same calls.

## How it fits together

```
GitHub Actions (Release workflow)
  build ──► API image ─► Trivy scan ─► ghcr.io/<you>/wiredex-api:<tag>
        └─► web build (artifact)
  deploy ─► rsync to wiredex@host:/srv/wiredex ─► bin/deploy.sh <tag> ─► smoke test
```

Nothing is built on the server. Caddy serves the static web app and proxies `/api/*` to the
API container; Postgres runs beside it in Docker
([ADR 0009](adr/0009-single-host-deployment.md)).

## 1. Make the fork yours

Four places name the original instance. Change them in your fork:

| File | What to change |
| --- | --- |
| `deploy/wiredex.caddy` | `wiredex.vinilabs.cc` on the first line of the site block, to your domain |
| `deploy/compose.prod.yml` | `ghcr.io/vinicius-cardoso/wiredex-api`, to `ghcr.io/<your-user>/wiredex-api` |
| `.github/workflows/release.yml` | The image name, and `https://wiredex.vinilabs.cc` in the deploy job's name, URL and smoke test |
| `README.md` | The links to the live instance, if you publish your fork |

After the first release, make the `wiredex-api` package **public** in your GitHub account
(Packages → the package → Package settings), so the host can pull it without a token. The
image holds no secrets.

## 2. Point the domain at the host

Add an `A` record for your domain to the host's IP. If your DNS provider proxies traffic
(Cloudflare's orange cloud), turn the proxy off for this record: Caddy needs to answer the
certificate challenge itself.

## 3. Give GitHub a way in

Create an SSH key that only the deploy uses:

```bash
ssh-keygen -t ed25519 -f wiredex-deploy -C wiredex-deploy -N ""
```

In your fork, under *Settings → Environments*, create an environment called `production`
that deploys from `main` only, with:

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `DEPLOY_SSH_KEY` | The private key (`wiredex-deploy`) |
| Secret | `DEPLOY_KNOWN_HOSTS` | The host's key: `ssh-keyscan -t ed25519 <ip>`, checked against a fingerprint you trust |
| Variable | `DEPLOY_HOST` | The host's IP |
| Variable | `DEPLOY_USER` | `wiredex` |

## 4. Prepare the host

One script installs Docker, creates the `wiredex` deploy user and `/srv/wiredex`, hooks the
site into Caddy, caps the journal, and installs the nightly jobs. Run it from your machine,
with the public half of the key from step 3:

```bash
ssh <host> "sudo DEPLOY_PUBLIC_KEY='ssh-ed25519 AAAA… wiredex-deploy' bash -s" < deploy/server-setup.sh
```

It is safe to run again. It generates two secret files that never leave the host and are
never overwritten:

- `/srv/wiredex/.env`: Postgres and the schema owner's login, for the database and for
  migrations only.
- `/srv/wiredex/api.env`: the API's login, as the restricted `wiredex_app` role that
  row-level security applies to ([ADR 0007](adr/0007-workspace-isolation.md)).

The script expects Caddy to be installed already, and makes it import
`/etc/caddy/sites/*.caddy`. The backup part is written for Oracle Cloud (it authenticates as the VM itself); on another
cloud, skip the backup variables and see *Backups* below.

## 5. Tell the API where files go

Add the file store to `/srv/wiredex/api.env` on the host. All six are required in
production:

```bash
WIREDEX_FILE_STORE=s3
WIREDEX_FILES_ENDPOINT=https://<your S3 endpoint>
WIREDEX_FILES_REGION=<region>
WIREDEX_FILES_BUCKET=<bucket>
WIREDEX_FILES_ACCESS_KEY=<access key>
WIREDEX_FILES_SECRET_KEY=<secret key>
```

Use a key that can reach that one bucket and nothing else. Keep the bucket private: the API
streams every file itself, after checking who asks. Turning on object versioning with a
30-day expiry for old versions gives you an undo for a deleted attachment.

## 6. Release

Merge to `main` in your fork. release-please opens a release PR; merging it tags the
version, builds and scans the image, deploys it and runs a smoke test
([ADR 0012](adr/0012-versioning-and-releases.md)). A deploy takes about three minutes.
Database migrations run by themselves during it, and a deploy that fails its readiness
check rolls back to the release before.

To deploy by hand, or to go back to an older tag, run the *Release* workflow with the tag as
its input.

## 7. Create your account

```bash
ssh -t <host> sudo -u wiredex /srv/wiredex/bin/wiredex users create --email you@example.com --name "Your name"
```

It asks for a password and creates the account with a workspace of its own. Then open your
domain and log in.

## Day to day

Every command runs through the same wrapper, in the live release's image:

| To | Run on the host, as `sudo -u wiredex /srv/wiredex/bin/wiredex …` |
| --- | --- |
| Invite a guest to a demo bench of their own | `demo invite --email friend@example.com --expires 7d`, or *Share a demo* in the account menu |
| Start a workspace over, keeping the account | `workspace clear --email you@example.com` |
| Recompute stock balances from the ledger | `stock rebuild` |
| Delete files nothing points at any more | `files prune` (also runs nightly) |

A systemd timer resets the demo benches and prunes files every night. Check it with
`journalctl -u wiredex-demo-reset --since today`.

## Backups

The database is the only state on the host: files are in your bucket, and everything else
comes from the image. `deploy/backup.sh` dumps the database every night, encrypts it with
restic and uploads it, keeping daily, weekly and monthly copies. As written it targets an
Oracle Cloud bucket and authenticates as the VM. On another cloud, point restic at your own
repository: the script's `pg_dump | restic backup --stdin` core is unchanged.

Whatever you use, restore a backup before you trust it. `make restore-drill` loads the
newest one into a throwaway Postgres on your machine.

## Upgrading

Pull the upstream changes into your fork and merge the release PR. Migrations only ever add
to the schema within a release, so the previous version keeps working while the new one
starts, and a failed deploy can roll back.

One release has a caveat: after `0.5.0`, units can be reserved for or in use in a build,
which `0.4.x` can't read. Going back past `0.5.0` by hand means cancelling or dismantling
every build that holds a unit first. Deploys never go backwards on their own.

## Running it on your own machine instead

For a look around without a server, the development stack is a few commands, with files
kept in a local folder and no bucket needed:

```bash
make install
make migrate    # starts Postgres in Docker and applies the migrations
make api    # http://localhost:9000, API docs at /api/docs
make web    # http://localhost:5173, in another terminal
```

Create an account for it with `cd apps/api && uv run wiredex users create --email … --name …`.
This setup is for development: it has no TLS, and the API reloads on every change.
