# PotluckDB for Python

A drop-in replacement for Python's built-in `sqlite3` module that runs on
PotluckDB's own build of SQLite.

> **Pre-release.** This first version runs queries exactly like `sqlite3`;
> sync arrives in later releases. Not for production use before 1.0.

## Quickstart

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
`Cursor`, `Row`, `Blob`, the exceptions, `PARSE_DECLTYPES`, adapters and
converters, `sqlite3.dbapi2`, and the behaviour of the Python version you run.
Two extra names:

| Name | What |
| --- | --- |
| `potluckdb.__version__` | This package's version, e.g. `0.8.0.dev1` |
| `potluckdb.core_version` | The PotluckDB library's version, e.g. `0.8.0-dev.1` |

`python -m potluckdb` opens the same shell as `python -m sqlite3` (Python 3.12+).

### Differences from `sqlite3`

- Database names starting with `file:` are always read as URIs (PotluckDB's
  library is built that way), even without `uri=True`.
- The classes are PotluckDB's own: `isinstance(x, sqlite3.Connection)` with the
  standard library's module is `False` for a PotluckDB connection.

## Platforms

Wheels for CPython 3.10 to 3.14 on Linux (x86-64 and ARM64, glibc 2.28+ and
musl), macOS 11+ (Apple silicon and Intel) and Windows (x64 and ARM64). The
library is linked into the package: it never loads or changes the system's
SQLite, and the standard `sqlite3` module keeps working next to it.

## Building from source

The build links the PotluckDB library from its release archive
(`potluckdb-sqlite-<version>-<platform>.tar.gz` or `.zip`):

```sh
cd python
POTLUCKDB_CORE_DIR=/path/to/archives pip wheel .   # archives you have
pip wheel .                                         # downloads the CORE_VERSION release
```

Without an archive for the platform, the build stops and says what is missing.

## Tests

```sh
python tests/test_package.py                 # quickstart, names, isolation from sqlite3
python tests/run_cpython_tests.py            # CPython's own sqlite3 test suite
```

`run_cpython_tests.py` runs the test suite of the CPython release you are
running against `potluckdb` (as `sqlite3`). Failures that are understood are
listed with their reason in `tests/cpython_known_failures.txt`; any other
failure fails the run.

## Licence

This package's code is Apache-2.0. It includes pysqlite3's C sources (zlib
licence, modified; see `vendor/pysqlite3/README.md`) and the PotluckDB library
(binary licence in `licenses/LICENSE-potluckdb-binary.txt`; SQLite itself is
public domain, `licenses/THIRD_PARTY_NOTICES.txt`). All of these ship in the
wheel.
