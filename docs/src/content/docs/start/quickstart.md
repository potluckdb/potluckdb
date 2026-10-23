---
title: Quickstart
description: Download the PotluckDB library and run a query with it, in a few minutes.
sidebar:
  order: 1
---

Pre-releases ship PotluckDB as a drop-in SQLite library: programs that use
SQLite load it in place of their usual one. Databases don't sync yet; folders
do, with the [`potluckdb` command](/guides/sync-a-folder/).

From Python, the quickest start is the package:

```sh
pip install --pre potluckdb
python -c "import potluckdb as sqlite3; print(sqlite3.connect(':memory:').execute('select potluckdb_version()').fetchone())"
```

See [Python](/guides/python/), [Node.js](/guides/node/), [Rust](/guides/rust/), [Go](/guides/go/) and [.NET](/guides/dotnet/). For any other
program, use the library directly:

## 1. Download

Get the archive for your platform from the
[releases page](https://github.com/potluckdb/potluckdb/releases) (see
[platforms](/reference/platforms/) for the names), and
[check it](/guides/verify-downloads/) if you like. Then unpack it:

```sh
tar xzf potluckdb-sqlite-<version>-linux-x64-gnu.tar.gz
```

Each archive holds the library (`lib/`, or `bin/` on Windows), its headers
(`include/`) and its licence.

## 2. Run a query

Python's built-in `sqlite3` module is a quick way to try it. Point it at the
library and ask which build answers:

```sh
# Linux
LD_LIBRARY_PATH=$PWD/potluckdb-sqlite-<version>-linux-x64-gnu/lib \
  python3 -c "import sqlite3; print(sqlite3.connect(':memory:').execute('select potluckdb_version(), sqlite_version()').fetchone())"
```

```sh
# macOS, with Homebrew's Python (python.org's builds have SQLite built in)
DYLD_LIBRARY_PATH=$PWD/potluckdb-sqlite-<version>-macos-arm64/lib \
  /opt/homebrew/bin/python3 -c "import sqlite3; print(sqlite3.connect(':memory:').execute('select potluckdb_version(), sqlite_version()').fetchone())"
```

It prints the PotluckDB and SQLite versions, for example
`('0.8.0-dev.1', '3.54.1')`. A plain SQLite has no `potluckdb_version()`
function, so the query fails if the program still uses its usual library.

## Next

- [Use the drop-in library](/guides/drop-in/) with your own program, on
  Linux, macOS and Windows.
- [What works today](/start/status/), and what comes next.
