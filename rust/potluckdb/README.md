# potluckdb

PotluckDB for Rust. Your app runs on PotluckDB's build of SQLite through one
entry in `[patch.crates-io]`, which replaces `libsqlite3-sys`, the crate that
rusqlite, sqlx and diesel get SQLite through. This crate is optional: it
fails the build if that entry is missing or for another version, and it says
which build is running.

> **Status: pre-release.** It does not sync yet; that comes in later releases.

```toml
[dependencies]
rusqlite = { version = "0.40", features = ["bundled"] }
potluckdb = "=0.8.0-dev.2"

[patch.crates-io]
libsqlite3-sys = { git = "https://github.com/potluckdb/potluckdb", tag = "rust-v0.8.0-dev.2", version = "0.38" }
```

Use `version = "0.37"` with sqlx 0.9 or rusqlite 0.39.

```rust
assert_eq!(potluckdb::version(), "0.8.0-dev.1"); // as SELECT potluckdb_version()
println!("SQLite {}", potluckdb::sqlite_version());
```

`potluckdb::ffi` is SQLite's C API (the `libsqlite3-sys` crate).

Platforms, offline builds and the differences from rusqlite's bundled SQLite:
[rust/README.md](https://github.com/potluckdb/potluckdb/tree/main/rust#readme).

## Licence

This crate is Apache-2.0. The SQLite library that PotluckDB's
`libsqlite3-sys` links into your program comes with the PotluckDB binary
licence (`LICENSE.txt` in each release archive) and SQLite's public-domain
notice.
