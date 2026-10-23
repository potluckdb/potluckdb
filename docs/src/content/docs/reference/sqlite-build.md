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

Floating-point code is compiled without fused multiply-add, so every
platform computes bit-identical results. That matters once devices replay
each other's changes.
