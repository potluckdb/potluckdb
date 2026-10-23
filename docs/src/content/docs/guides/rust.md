---
title: Rust
description: Use PotluckDB from Rust with rusqlite, sqlx or diesel.
---

rusqlite, sqlx and diesel all get SQLite through the `libsqlite3-sys` crate.
PotluckDB has its own `libsqlite3-sys`, which links PotluckDB's library in
place of the bundled or system SQLite. Your code stays the same: you add one
entry to `Cargo.toml`. It works on Linux (glibc 2.28+ and musl), macOS 11+
and Windows, x64 and ARM64.

```toml
[dependencies]
rusqlite = { version = "0.40", features = ["bundled"] }  # as before
potluckdb = "=0.8.0-dev.2"  # optional: stops the build if the entry below is missing

[patch.crates-io]
libsqlite3-sys = { git = "https://github.com/potluckdb/potluckdb", tag = "rust-v0.8.0-dev.2", version = "0.38" }
```

```rust
let db = rusqlite::Connection::open("app.db")?;
let (p, s): (String, String) =
    db.query_row("SELECT potluckdb_version(), sqlite_version()", [], |r| Ok((r.get(0)?, r.get(1)?)))?;
// p = "0.8.0-dev.2", s = "3.54.1"
```

The first build downloads PotluckDB's library for your platform (about 2 MB)
and checks its SHA-256. Nothing is compiled. The library is linked in
statically, so your program needs no extra file at run time.

## Which `version` to write

`version` picks the `libsqlite3-sys` line your other crates need;
`cargo tree -i libsqlite3-sys` shows yours.

| Your app uses | `version =` |
| --- | --- |
| rusqlite 0.40 (and r2d2_sqlite, tokio-rusqlite, rusqlite_migration, deadpool-sqlite built on it), diesel 2.3 | `"0.38"` |
| sqlx 0.9 (and SeaORM 2), rusqlite 0.39 | `"0.37"` |

If the line doesn't match, Cargo only warns that the patch "was not used" and
builds with the usual SQLite. The `potluckdb` crate turns that into a build
error that says what to change.

## Good to know

- Databases sync in a later pre-release (0.8.2); for now it runs queries
  exactly like rusqlite's bundled SQLite, with a few differences in build
  options (foreign keys are off until `PRAGMA foreign_keys = ON`, no
  `soundex()`).
- rusqlite's own test suite passes against it on every platform.
- Write pre-release versions with `=`: Cargo otherwise moves to a newer
  pre-release, which no longer matches the `tag`.
- Offline builds and mirrors: set `POTLUCKDB_CORE_DIR` to a folder with the
  release's archives, or `POTLUCKDB_DOWNLOAD_URL` to a mirror.

All the details: [rust/README.md](https://github.com/potluckdb/potluckdb/tree/main/rust).
