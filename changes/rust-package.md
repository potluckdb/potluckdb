type: added

Rust: apps that use rusqlite, sqlx or diesel run on PotluckDB's SQLite after adding one `[patch.crates-io]` entry to `Cargo.toml`, on Linux, macOS and Windows; the code stays the same. The optional `potluckdb` crate on crates.io stops the build if the entry is missing.
