---
title: SQLite build
description: The SQLite version, options and extensions in PotluckDB's library.
---

PotluckDB ships **SQLite 3.54.1, unmodified**, built the same way on every
platform.

## Built in

- Full-text search: FTS3, FTS4 and FTS5
- R*Tree and Geopoly
- JSON functions
- Math and percentile functions
- The session extension, `sqlite_dbpage`, `dbstat` and `sqlite_stmt`
- URI filenames, on by default
- Thread safety: serialized (SQLite's default)

## What PotluckDB adds

| Name | Where | Returns |
| --- | --- | --- |
| `potluckdb_version()` | SQL function | The PotluckDB version, for example `0.8.0-dev.1` |
| `potluckdb_version(void)` | C function, in `potluckdb.h` | The same, as a C string |

Everything else behaves as in SQLite itself.

## Same results everywhere

Every platform computes bit-identical results. That matters once devices
replay each other's changes.

- Floating-point code is compiled without fused multiply-add.
- SQLite's math functions (`sin`, `exp`, `pow`, `ln` and the others) come
  from a copy of [musl](https://musl.libc.org)'s math code built into the
  library, not from the system's math library, whose results differ in the
  last bit between Linux, macOS and Windows.
- Every release is checked against thousands of frozen results, bit for
  bit, on every platform
  ([`tests/vectors`](https://github.com/potluckdb/potluckdb/tree/main/tests/vectors)).

So a result can differ in the last digit from another SQLite on the same
machine, but not between devices running the same PotluckDB version.
