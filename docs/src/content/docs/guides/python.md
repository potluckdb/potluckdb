---
title: Python
description: Use PotluckDB from Python, in place of the standard sqlite3 module.
---

`potluckdb` on PyPI is a drop-in replacement for Python's built-in `sqlite3`
module that runs on PotluckDB's build of SQLite. It works on Python 3.10 to
3.14, on Linux (glibc 2.28+ and musl), macOS 11+ and Windows, x64 and ARM64.

```sh
pip install --pre potluckdb
```

```python
import potluckdb as sqlite3          # the only change in an existing app

db = sqlite3.connect("app.db")
print(db.execute("select potluckdb_version(), sqlite_version()").fetchone())
# ('0.8.0-dev.1', '3.54.1')
```

Everything else is the standard library's `sqlite3`: `connect`, `Connection`,
`Cursor`, `Row`, `Blob`, the exceptions, adapters and converters, and the
behaviour of the Python version you run. CPython's own sqlite3 tests pass
against it on every version and platform.

Two names are added: `potluckdb.__version__` (this package) and
`potluckdb.core_version` (the PotluckDB library inside it).

## Good to know

- Databases sync too: `potluckdb attach app.db s3://my-bucket/app` once,
  with no code change ([Sync a database](/guides/sync-a-database/)). One
  device writes at a time for now.
- Database names starting with `file:` are always read as URIs.
- It never clashes with the standard `sqlite3` in the same program: each
  uses its own SQLite.
