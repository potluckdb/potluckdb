---
title: Sync a folder
description: Keep a folder the same on several devices through a bucket you own, and restore any version.
---

The `potluckdb` command keeps a folder of any files the same on several
devices, through a storage bucket you own. It keeps 7 days of history and
restores any version from it. Download it from the
[releases page](https://github.com/potluckdb/potluckdb/releases): the
archives named `potluckdb-cli-<version>-<platform>`.

## Start syncing

On the first device, point it at the folder and a bucket:

```sh
potluckdb sync ~/notes s3://my-bucket/notes
```

On every other device, the same command (the folder is created if needed):

```sh
potluckdb sync ~/notes s3://my-bucket/notes
```

After that, `potluckdb sync ~/notes` is enough. To keep syncing until you
stop it (Ctrl+C), every second while files change and every 5 seconds when
quiet:

```sh
potluckdb sync ~/notes --watch
```

## Buckets

| Address | Where | Credentials |
| --- | --- | --- |
| `s3://bucket/prefix` | Amazon S3 | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` |
| `s3://bucket/prefix` with `AWS_ENDPOINT_URL` | MinIO, RustFS and other S3-compatible services | as above |
| `r2://account-id/bucket/prefix` | Cloudflare R2 | `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` (or the `AWS_` ones) |
| `gs://bucket/prefix` | Google Cloud Storage | a signed-in `gcloud`, or `GOOGLE_OAUTH_ACCESS_TOKEN` |
| `az://account/container/prefix` | Azure Blob Storage | a signed-in `az`, or `AZURE_STORAGE_KEY` |
| a folder path | A shared or mounted drive | none |

Credentials are never stored with the folder. The first sync checks that
the bucket refuses conflicting writes; one that ignores them is refused,
because devices could overwrite each other.

## When a file changed on two devices

Both versions are kept. The version that reached the bucket first keeps the
file's name; the other is saved next to it as
`notes (conflict 2026-10-23 18-35-02).txt`, and syncs to every device too.

## History and restoring

```sh
potluckdb history ~/notes
potluckdb restore ~/notes --version 12 --into ~/notes-as-of-12
potluckdb restore ~/notes --version 12
```

The first restore writes version 12's files into a new folder and changes
nothing else. The second makes the folder's files version 12's on every
device, as a new version, so the versions in between stay restorable.

Sync deletes history older than 7 days once a day. To delete it now, or
keep a different amount:

```sh
potluckdb cleanup ~/notes --keep 36h
```

## Good to know

- PotluckDB keeps its own state in `.potluckdb` inside the folder. It is
  never synced; don't edit it.
- Links are not synced, and files larger than 1 GB are skipped for now.
- `potluckdb status ~/notes` shows the bucket, the version and whether the
  folder has changes not synced yet.
