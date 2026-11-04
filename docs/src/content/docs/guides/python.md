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
behaviour of the Python version you run, except two details where Python 3.10
differs from 3.11 and later: potluckdb fetches rows as they are read, and
keeps cursors usable after a rollback, as 3.11 does. CPython's own sqlite3
tests pass against it on every version and platform, apart from the four 3.10
tests of those details
([the list](https://github.com/potluckdb/potluckdb/blob/main/python/tests/cpython_known_failures.txt)).

Two names are added: `potluckdb.__version__` (this package) and
`potluckdb.core_version` (the PotluckDB library inside it).

## Good to know

- Databases sync in a later pre-release; for now it is SQLite with no sync.
- Database names starting with `file:` are always read as URIs.
- It never clashes with the standard `sqlite3` in the same program: each
  uses its own SQLite.
- `PRAGMA secure_delete` is off, as in sqlite.org's SQLite, python.org's Python
  and Homebrew's Python. Some Python builds turn it on: Ubuntu's system Python
  (on) and Apple's `/usr/bin/python3` on macOS ("fast" mode, which overwrites
  deleted content when that costs no extra disk writes). With PotluckDB,
  deleted content stays readable in the database file until its space is
  reused. Run `PRAGMA secure_delete = ON` (or `FAST`) on each connection to get
  that back.
