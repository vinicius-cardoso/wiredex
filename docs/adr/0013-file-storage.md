# 0013. File storage in OCI Object Storage through the S3-compatible API

- **Status:** Accepted
- **Date:** 2026-09-25

## Context

Part definitions (and, from `v0.5.0`, project revisions) need attachments:
datasheets, images and pinout diagrams. The bytes shouldn't sit on the small
VM's disk, which already holds the system, the Docker images and the database.
The owner chose OCI Object Storage: its Always Free tier gives 20 GB of storage,
50,000 requests and 10 TB of outbound traffic a month, enough many times over.

OCI has two ways in: Oracle's own `oci` SDK, or its S3-compatible API through a
standard S3 client. It also offers pre-signed URLs, which would let the browser
read bytes straight from the bucket instead of through the API.

## Decision

- **Reach the bucket through its S3-compatible API, with boto3.** Measured on
  this machine, Oracle's `oci` SDK installs about 270 MB and would roughly
  double the image the VM pulls and Trivy scans; boto3 is about 28 MB.
  Importing the part of each that is actually used costs about the same memory
  (a few MB over a bare interpreter either way). boto3 also lets the file-store
  adapter be tested against a MinIO container, the way the repositories are
  tested against Postgres.
- **A dedicated Customer Secret Key, scoped to the files bucket.** The S3 API
  needs a stored secret, so it is kept small: an IAM user whose only permission
  is to manage objects in the `wiredex-files` bucket, and nothing else in the
  cloud account. The key lives in `/srv/wiredex/api.env`, never in the repo.
- **Content-addressed per workspace.** An object's key is
  `workspaces/<workspace_id>/sha256/<hex>`. The same datasheet attached to
  three parts is one object; two workspaces never share one, so a demo reset
  deletes its own prefix without touching anyone else's files, and whether a
  file exists in another workspace can't be probed.
- **The API serves the bytes, not pre-signed URLs.** Every read passes the
  session, the workspace check and the same origin, so the site's
  Content-Security-Policy keeps allowing only `'self'`. The bytes are streamed
  in chunks, so a 25 MB PDF never sits in the container's memory whole.
- **Versioning and a lifecycle rule stand in for restic on objects.** The
  bucket keeps object versions and deletes previous versions after 30 days, so
  a deleted file can be recovered for a month. The database backup covers the
  rows; the objects rely on the bucket's durability plus those 30 days, rather
  than being copied into restic like the database.

## Consequences

- One stored secret to guard, scoped so a leak reaches only the files bucket.
- The file store can be exercised locally against MinIO, and a local folder
  adapter serves development and the e2e run with no cloud account.
- Recent boto3 sends checksums OCI's S3-compatible API rejects, so the client
  is built with `request_checksum_calculation="when_required"` and
  `response_checksum_validation="when_required"`.
- If OCI ever adds an S3 feature the adapter needs and doesn't support, the
  fallback is Oracle's `oci` SDK, at the image-size cost measured above.
