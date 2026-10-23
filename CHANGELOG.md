# Changelog

Every PotluckDB release, newest first. Versions with `-dev` or `-rc` are
pre-releases.

## 0.8.0-dev.1 (2026-10-23)

The first pre-release of the new PotluckDB: our build of SQLite as a drop-in library, for Linux, macOS and Windows. It does not sync yet.

### Highlights

- The potluckdb command syncs a folder between devices through Amazon S3, Cloudflare R2, Google Cloud Storage, Azure Blob Storage or a shared folder, keeps 7 days of history, and restores any version from it. When a file changed on two devices, both versions are kept. Try `potluckdb sync <folder> <bucket>`.
- A drop-in SQLite library (SQLite 3.54.1, unmodified) for Linux (x64 and ARM64, glibc 2.28 or newer, or musl), macOS (Apple silicon and Intel) and Windows (x64 and ARM64). It keeps SQLite's own file names (libsqlite3.so.0, libsqlite3.0.dylib, sqlite3.dll), so existing programs load it in place of their usual SQLite.
- Optional encryption: `potluckdb key new` makes a key file, and `potluckdb sync <folder> <bucket> --key-file <file>` encrypts everything stored in the bucket. Keys can be rotated with `potluckdb key rotate`; the bucket owner still sees object counts, sizes and timing.
- Built in: full-text search (FTS3, FTS4, FTS5), R*Tree and Geopoly, JSON, math and percentile functions, and the session extension. URI filenames are on by default.
- The macOS library loads on macOS 11 and newer, and the Windows library needs nothing beyond Windows itself (no Visual C++ runtime to install).
- SELECT potluckdb_version() tells any program which PotluckDB build it is running on.
- A static build of the same library in lib/static (libsqlite3.a, or sqlite3.lib on Windows), for programs that link SQLite into themselves. Its symbols stay private to the program, so it never clashes with another SQLite loaded in the same process.
- Node.js: `npm install potluckdb` installs a drop-in replacement for better-sqlite3 that runs on PotluckDB's SQLite. Change `require('better-sqlite3')` to `require('potluckdb')` and your code keeps working, on Node.js 20 and later, on Linux, macOS and Windows.
- Python: `pip install potluckdb` installs a drop-in replacement for the standard `sqlite3` module that runs on PotluckDB's SQLite. Change `import sqlite3` to `import potluckdb as sqlite3` and your code keeps working, on Python 3.10 to 3.14, on Linux, macOS and Windows.

### Changes

- SQLite's math functions (sin, exp, pow, ln and the others) now return exactly the same result, to the last bit, on every platform: the library builds in its own copy of musl's math code instead of using the system's. A result can differ in the last digit from another SQLite on the same machine.

### Known issues

- potluckdb sync skips files larger than 1 GB for now.
- No sync yet, and no language packages yet: this pre-release is the library on its own. Files are signed with Sigstore but not yet with Apple or Windows code signing.
