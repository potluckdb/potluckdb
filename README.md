# PotluckDB

Local-first SQLite and DuckDB, synced through a storage bucket you own. No
server. Reads and writes stay local and fast; changes reach your other devices
in about half a second.

PotluckDB is a drop-in replacement for the standard SQLite library: your
existing code, drivers and ORMs keep working, and sync is switched on with a
bucket address.

> **Status: pre-release.** The 0.8 series is being built in the open, with a
> new pre-release every few hours. Early pre-releases do not sync yet; the
> [changelog](CHANGELOG.md) says what each one does. Not for production use
> before 1.0.

## Try a pre-release

Download the archive for your platform from the
[releases page](https://github.com/potluckdb/potluckdb/releases), then point
your program at the library inside it. For example, Python's built-in
`sqlite3` module on Linux:

```sh
tar xzf potluckdb-sqlite-<version>-linux-x64-gnu.tar.gz
LD_LIBRARY_PATH=$PWD/potluckdb-sqlite-<version>-linux-x64-gnu/lib \
  python3 -c "import sqlite3; print(sqlite3.connect(':memory:').execute('select potluckdb_version()').fetchone())"
```

Each release lists how to check its files (`SHA256SUMS` and Sigstore signatures).

## This repository

| Path | What |
| --- | --- |
| `CHANGELOG.md` | Release notes for every version |
| `changes/` | Notes for changes not released yet |
| `tools/` | Release tooling |
| `docs/` | The docs site, docs.potluckdb.com ([Starlight](https://starlight.astro.build/)) |

Language add-ons, docs and examples arrive here during the 0.8 series. The
sync engine itself is built in a private repository; its binaries are
published here.

## Licence

The code in this repository is licensed under [Apache-2.0](LICENSE). The
PotluckDB binaries attached to releases come with their own licence (included
in each archive).
