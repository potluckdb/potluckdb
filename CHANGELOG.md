# Changelog

Every PotluckDB release, newest first. Versions with `-dev` or `-rc` are
pre-releases.

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
