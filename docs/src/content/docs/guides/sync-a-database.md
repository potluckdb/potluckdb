---
title: Sync a database
description: Keep a SQLite database the same on several devices through a bucket you own.
---

A program running on PotluckDB's library (the [drop-in library](/guides/drop-in/)
or a language package) syncs a database when its address names a bucket.
One device writes; every other device that opens the same address receives
its changes, usually within a second, and reads them like any other data.
The program keeps using SQLite as before.

## Turn it on

Add `potluckdb=<bucket>` to the database's address, as a
[URI filename](https://sqlite.org/uri.html):

```
file:app.db?potluckdb=s3://my-bucket/app
```

For example, with Python's `sqlite3` module:

```python
import sqlite3

db = sqlite3.connect("file:app.db?potluckdb=s3://my-bucket/app", uri=True)
```

To sync a database without changing the program, attach it with the
`potluckdb` command (from the [releases page](https://github.com/potluckdb/potluckdb/releases),
the archives named `potluckdb-cli-<version>-<platform>`):

```sh
potluckdb attach app.db s3://my-bucket/app
```

This writes a small file next to the database, `app.db.potluckdb`, which the
library reads when a program opens `app.db`. `potluckdb detach app.db`
removes it again.

A device that doesn't have the database yet creates it from the bucket's
latest version when it first opens it.

## Buckets

The same addresses and credentials as for [syncing a folder](/guides/sync-a-folder/#buckets):
Amazon S3 and S3-compatible services, Cloudflare R2, Google Cloud Storage,
Azure Blob Storage, or a shared folder. Credentials come from the
environment of the program that opens the database and are never stored
with it. Use one bucket address (or prefix) per database.

## Encryption

Make a key file with the `potluckdb` command (`potluckdb key new app.key`,
see [Encryption](/guides/sync-a-folder/#encryption)), copy it to every device,
and name it when attaching, or in the address:

```sh
potluckdb attach app.db s3://my-bucket/app --key-file app.key
```

```
file:app.db?potluckdb=s3://my-bucket/app&potluckdb_keys=/path/to/app.key
```

## Good to know

- **One writing device at a time, for now.** Several devices writing comes
  in 0.8.3. When two devices write at the same time, one device's changes
  are not merged: they are kept in a copy next to its database
  (`app.db.conflict-<time>.db`), and the database continues with the other
  device's version.
- **Several programs on one device** can use the same synced database. One
  of them syncs for all; when it exits, another takes over within a second.
- Sync keeps its state in a folder next to the database (`app.db-potluckdb`).
  Don't delete it while the database is in use.
- Settings that could let a crash damage the database on every device are
  refused on a synced database: `PRAGMA journal_mode=OFF` or `MEMORY`,
  `PRAGMA synchronous=OFF` and `PRAGMA locking_mode=EXCLUSIVE`.
- Both journal modes work: the default rollback journal and WAL.
- The bucket keeps 7 days of versions; restoring one comes in a later
  pre-release.
- To see sync errors, set the environment variable `POTLUCKDB_LOG=stderr`
  before starting the program.
