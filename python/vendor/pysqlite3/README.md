# Vendored pysqlite3 sources

The C sources of the `potluckdb._sqlite3` extension come from pysqlite3.

| | |
| --- | --- |
| Project | pysqlite3, https://github.com/coleifer/pysqlite3 (https://pypi.org/project/pysqlite3/) |
| Version | 0.6.0 |
| Taken from | https://files.pythonhosted.org/packages/fa/84/6e586bef5f6337dee60066eef752c73fa6fcb93c1e7997b550d3105ed4f9/pysqlite3-0.6.0.tar.gz |
| sha256 of that file | `ecf5112b62a4e6c04438957e343fe9672707bd3191f789ecae6c95b226aa6bb6` (matches PyPI) |
| Files taken | `src/*.c`, `src/*.h` and `LICENSE` |
| Licence | zlib (`LICENSE`; the same text heads every source file) |

pysqlite3's `pyproject.toml` says `license = "MIT"`, but its `LICENSE` file and
every source file carry the zlib licence text; the zlib text is what applies.

## Modifications

These sources are altered (zlib licence, clause 2): every changed file says
so at the end of its licence comment, and the first commit that added this
folder holds the files exactly as released. The changes, written for
PotluckDB (no code copied from CPython):

- **Built as `potluckdb._sqlite3`** (`MODULE_NAME` is `potluckdb`), so it never
  clashes with the standard library's `_sqlite3` or with pysqlite3 in the same
  process. It also exposes `core_version` (PotluckDB's `potluckdb_version()`)
  and `__version__` (the package version).
- **Behaves like the `sqlite3` module of the Python it is built for** (3.10 to
  3.14; one wheel per version, so differences are chosen at compile time in
  `compat.h`): connection, cursor, row and blob behaviour, error classes and
  messages, deprecation warnings, and the constants of that version.
- **Features added** to match Python 3.11 to 3.14: `Connection.blobopen()` and
  the `Blob` type (replacing pysqlite3's `open_blob()`), `serialize()` /
  `deserialize()`, `setlimit()` / `getlimit()`, `setconfig()` / `getconfig()`,
  the `autocommit` attribute and `LEGACY_TRANSACTION_CONTROL`, `iterdump()`
  (with `filter=`), `create_window_function()` with the standard signature,
  `load_extension(entrypoint=)`, extended error codes on exceptions
  (`sqlite_errorcode`, `sqlite_errorname`), all result-code, limit and
  configuration constants, `threadsafety` from SQLite's threading mode.
- **Rewritten internals**: rows are read as the statement is stepped (no
  prefetching), statements are cached with `functools.lru_cache` (`cache.c`
  and `cache.h` removed), parameter binding moved from `statement.c` to
  `cursor.c`, callbacks (functions, aggregates, collations, trace, progress,
  authorizer) use reference-counted contexts that SQLite releases, objects
  support the garbage collector, and unclosed connections warn (3.13+).
- **Safer than the standard module** where callbacks interfere with a running
  statement: a function or converter that closes the connection, reuses the
  cursor it runs in, or replaces the text factory gets a `ProgrammingError`
  instead of a crash; window functions work over empty frames. The statement
  cache refers to its connection weakly, so a connection nobody refers to is
  closed at once (as in Python 3.10) rather than at the next garbage
  collection.
- **Removed pysqlite3-only extras**: `Connection(flags=, vfs=)`,
  `open_blob()`, `set_busy_handler()`, `set_busy_timeout()`, `set_key()`,
  `reset_key()`.
- **New file `compat.h`**: helpers so the same sources build for CPython 3.10
  to 3.14 (same zlib licence as the rest of this folder).
