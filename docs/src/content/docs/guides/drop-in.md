---
title: Use the drop-in library
description: Make an existing program load PotluckDB instead of its usual SQLite.
---

PotluckDB's library is unmodified SQLite plus PotluckDB, under SQLite's own
file names: `libsqlite3.so.0` on Linux, `libsqlite3.0.dylib` on macOS and
`sqlite3.dll` on Windows. A program that loads SQLite as a shared library
loads PotluckDB instead when it finds ours first. Nothing in the program
changes.

## Linux

Put the archive's `lib` folder first on the library path:

```sh
export LD_LIBRARY_PATH=/path/to/potluckdb-sqlite-<version>-linux-x64-gnu/lib
```

The `gnu` builds run on glibc 2.28 and newer (RHEL 8, Debian 10, Ubuntu
20.04 and later); the `musl` builds run on Alpine and other musl systems.

## macOS

Put the archive's `lib` folder first on the library path:

```sh
export DYLD_LIBRARY_PATH=/path/to/potluckdb-sqlite-<version>-macos-arm64/lib
```

macOS ignores `DYLD_LIBRARY_PATH` for its own programs (System Integrity
Protection), and some programs build SQLite in instead of loading it. Both
keep their own SQLite.

## Windows

Windows loads `sqlite3.dll` from the program's own folder first. Copy the
archive's `bin\sqlite3.dll` next to the program, or next to the module that
loads SQLite (for Python, `DLLs\_sqlite3.pyd`). The DLL needs nothing beyond
Windows itself.

## Linking it in

Programs that link SQLite into themselves can use the static library in
`lib/static` (`libsqlite3.a`, or `sqlite3.lib` on Windows) with the headers
in `include`. Its symbols stay private to your program, so it never clashes
with another SQLite in the same process.

## Check which library answers

```sql
SELECT potluckdb_version(), sqlite_version();
```

A plain SQLite has no `potluckdb_version()`, so this fails if the program
still uses its usual library.
