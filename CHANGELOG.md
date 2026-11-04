# Changelog

Every PotluckDB release, newest first. Versions with `-dev` or `-rc` are
pre-releases.

## 0.8.0-dev.4 (2026-11-04)

The Windows archives also hold a MinGW static library, `lib/static/libsqlite3.a`, built with llvm-mingw from the same sources and options, which Go's cgo can link (the MSVC library `lib/static/sqlite3.lib` stays for everything else).

### Highlights

- Go: Windows x64 and ARM64. Build with a MinGW-w64 C compiler for the UCRT runtime, for example llvm-mingw.

### Changes

- This release is the SQLite drop-in library only: the sync engine of 0.8.0-dev.1 to 0.8.0-dev.3, the `?potluckdb=` address parameter, the `app.db.potluckdb` side file and the `potluckdb` command are removed, so databases and folders do not sync in this release. Sync comes back, rebuilt, in later releases.

### Fixes

- Every release archive's `BUILD-INFO.json` now records the commit it was built from. In 0.8.0-dev.3, the Linux archives had "unknown" or an empty value there.
- The default VFS is SQLite's own again: `sqlite3_vfs_find(NULL)` returns "unix" on Linux and macOS and "win32" on Windows, as with sqlite.org's SQLite, and the list of registered VFSes holds only SQLite's own. In 0.8.0-dev.3 the default was named "potluckdb", with an extra "potluckdb" entry in the list.
- The library now exports every function that sqlite.org's own `sqlite3.dll` for the same SQLite version exports: 0.8.0-dev.3 lacked `sqlite3_carray_bind`, `sqlite3_carray_bind_v2` and the RBU extension's `sqlite3rbu_*` functions. SQL can now use the `carray()` table-valued function, and `PRAGMA compile_options` lists `ENABLE_CARRAY` and `ENABLE_RBU`.
- On macOS, modules and programs that link the static library (`lib/static/libsqlite3.a`) now export no PotluckDB-internal name; with 0.8.0-dev.3 they exported one. Linux and macOS builds now check that no name in the static library is visible outside the module that links it.
- The npm package and both NuGet packages no longer list "sync" among their search tags, since this release has no sync yet.
- Python on macOS: the `potluckdb` package's compiled module now exports only its init function. In 0.8.0-dev.3 it also exported `potluckdb_vfs_register`, which could clash with another copy of PotluckDB's library in the same program.

## 0.8.0-dev.3 (2026-10-24)

Databases sync: add `?potluckdb=<bucket>` to a database's address (for example `file:app.db?potluckdb=s3://my-bucket/app`), or put a file `app.db.potluckdb` next to it, and every program running on PotluckDB's library keeps that database the same on all devices that open it. Changes reach the other devices in about a second, and a device without the database gets it from the bucket.

### Highlights

- `potluckdb attach app.db s3://my-bucket/app` makes a database sync without changing any program: it writes `app.db.potluckdb` next to the database, which every program on PotluckDB's library reads. `potluckdb detach app.db` stops it.

### Known issues

- A synced database takes changes from one device at a time for now; several writing devices come in 0.8.3. When two devices write at the same time, one device's changes are not merged: they are kept in a copy next to its database (`app.db.conflict-<time>.db`).

## 0.8.0-dev.2 (2026-10-23)

.NET: the NuGet package `PotluckDB.Data.Sqlite` runs Microsoft.Data.Sqlite on PotluckDB's SQLite. Use it in place of `Microsoft.Data.Sqlite` and your code, and Dapper or EF Core on top, keeps working, on .NET 8 and later, on Linux, macOS and Windows. For sqlite-net, add `PotluckDB.SQLitePCLRaw` and call `SQLitePCL.Batteries_V2.Init()` once at startup.

### Highlights

- Go: `go get github.com/potluckdb/potluckdb-go/sqlite3` adds a drop-in replacement for go-sqlite3 (`github.com/mattn/go-sqlite3`) that runs on PotluckDB's SQLite. Change the import path, or add one `replace` line to `go.mod`, and your code keeps working, on Linux and macOS; Windows follows once the release has a library that MinGW can link.
- Rust: apps that use rusqlite, sqlx or diesel run on PotluckDB's SQLite after adding one `[patch.crates-io]` entry to `Cargo.toml`, on Linux, macOS and Windows; the code stays the same. The optional `potluckdb` crate on crates.io stops the build if the entry is missing.

## 0.8.0-dev.1 (2026-10-23)

The first pre-release of the new PotluckDB: our build of SQLite as a drop-in library for Linux, macOS and Windows, a drop-in `sqlite3` for Python, and a first taste of sync: the `potluckdb` command keeps a folder the same on several devices. Databases don't sync yet.

### Highlights

- The potluckdb command syncs a folder between devices through Amazon S3, Cloudflare R2, Google Cloud Storage, Azure Blob Storage or a shared folder, keeps 7 days of history, and restores any version from it. When a file changed on two devices, both versions are kept. Try `potluckdb sync <folder> <bucket>`.
- A drop-in SQLite library (SQLite 3.54.1, unmodified) for Linux (x64 and ARM64, glibc 2.28 or newer, or musl), macOS (Apple silicon and Intel) and Windows (x64 and ARM64). It keeps SQLite's own file names (libsqlite3.so.0, libsqlite3.0.dylib, sqlite3.dll), so existing programs load it in place of their usual SQLite.
- Optional encryption: `potluckdb key new` makes a key file, and `potluckdb sync <folder> <bucket> --key-file <file>` encrypts everything stored in the bucket. Keys can be rotated with `potluckdb key rotate`; the bucket owner still sees object counts, sizes and timing.
- Built in: full-text search (FTS3, FTS4, FTS5), R*Tree and Geopoly, JSON, math and percentile functions, and the session extension. URI filenames are on by default.
- The macOS library loads on macOS 11 and newer, and the Windows library needs nothing beyond Windows itself (no Visual C++ runtime to install).
- SELECT potluckdb_version() tells any program which PotluckDB build it is running on.
- A static build of the same library in lib/static (libsqlite3.a, or sqlite3.lib on Windows), for programs that link SQLite into themselves. Its symbols stay private to the program, so it never clashes with another SQLite loaded in the same process.
- Node.js: a drop-in replacement for better-sqlite3 that runs on PotluckDB's SQLite (change `require('better-sqlite3')` to `require('potluckdb')`), for Node.js 20 and later on Linux, macOS and Windows. Built and tested; it arrives on npm in a coming pre-release.
- Python: `pip install --pre potluckdb` installs a drop-in replacement for the standard `sqlite3` module that runs on PotluckDB's SQLite. Change `import sqlite3` to `import potluckdb as sqlite3` and your code keeps working, on Python 3.10 to 3.14, on Linux, macOS and Windows.

### Changes

- SQLite's math functions (sin, exp, pow, ln and the others) now return exactly the same result, to the last bit, on every platform: the library builds in its own copy of musl's math code instead of using the system's. A result can differ in the last digit from another SQLite on the same machine.

### Known issues

- potluckdb sync skips files larger than 1 GB for now.
- Databases don't sync yet (that comes in 0.8.2); this pre-release syncs folders, with the `potluckdb` command. Files are signed with Sigstore but not yet with Apple or Windows code signing.
