# PotluckDB for Rust

Your Rust app runs on PotluckDB's build of SQLite after a change to
`Cargo.toml` only. rusqlite, sqlx and diesel all get SQLite through the
`libsqlite3-sys` crate. PotluckDB provides its own `libsqlite3-sys`, which
links PotluckDB's library instead of the bundled or system SQLite. Your code
stays the same.

> **Status: pre-release.** It does not sync yet; that comes in later releases.

## Quickstart

Add the `[patch.crates-io]` entry (and, optionally, the `potluckdb` crate) to
the `Cargo.toml` at the root of your workspace:

```toml
[dependencies]
rusqlite = { version = "0.40", features = ["bundled"] }  # as before; `bundled` can stay on
potluckdb = "=0.8.0-dev.2"  # optional: fails the build if the entry below is missing

[patch.crates-io]
libsqlite3-sys = { git = "https://github.com/potluckdb/potluckdb", tag = "rust-v0.8.0-dev.2", version = "0.38" }
```

```rust
let db = rusqlite::Connection::open("app.db")?;
let (p, s): (String, String) =
    db.query_row("SELECT potluckdb_version(), sqlite_version()", [], |r| Ok((r.get(0)?, r.get(1)?)))?;
// p = "0.8.0-dev.1", s = "3.54.1"
```

The first build downloads PotluckDB's library for your platform (about 2 MB)
from the GitHub release and checks its SHA-256. Nothing is compiled, so the
build is faster than with `bundled`.

## Which `version` to write

`version` picks the `libsqlite3-sys` line that your other crates need.
`cargo tree -i libsqlite3-sys` shows yours.

| Your app uses | `version =` |
| --- | --- |
| rusqlite 0.40, and crates built on it (r2d2_sqlite 0.35, tokio-rusqlite 0.8, rusqlite_migration 2.6, deadpool-sqlite 0.14); diesel 2.3 | `"0.38"` |
| sqlx 0.9 (and SeaORM 2), rusqlite 0.39 | `"0.37"` |

If the line doesn't match, Cargo only warns that the patch "was not used in
the crate graph" and builds with the usual SQLite. The `potluckdb` crate turns
that into a build error that says what to change.

## sqlx

```toml
[dependencies]
sqlx = { version = "0.9", features = ["runtime-tokio", "sqlite"] }
potluckdb = "=0.8.0-dev.2"

[patch.crates-io]
libsqlite3-sys = { git = "https://github.com/potluckdb/potluckdb", tag = "rust-v0.8.0-dev.2", version = "0.37" }
```

```rust
let db = sqlx::SqlitePool::connect("sqlite:app.db").await?;
let (p, s): (String, String) = sqlx::query_as("SELECT potluckdb_version(), sqlite_version()").fetch_one(&db).await?;
```

## The C API

`libsqlite3-sys` is SQLite's C API for Rust; with the entry above it is
PotluckDB's. Use it directly, or as `potluckdb::ffi`.

## The potluckdb crate

Optional, and for now small:

- `potluckdb::version()`: the PotluckDB version of the linked library, for
  example `"0.8.0-dev.1"` (the same as `SELECT potluckdb_version()`).
- `potluckdb::sqlite_version()`: its SQLite version, for example `"3.54.1"`.
- `potluckdb::ffi`: the `libsqlite3-sys` crate.
- The build fails unless `libsqlite3-sys` is PotluckDB's, for the same
  version as the crate.

Write pre-release versions with `=` (`potluckdb = "=0.8.0-dev.2"`): Cargo
otherwise updates to a newer pre-release, which then no longer matches the
`tag`.

## Platforms

| Rust target | Needs |
| --- | --- |
| `x86_64-unknown-linux-gnu`, `aarch64-unknown-linux-gnu` | glibc 2.28 or later |
| `x86_64-unknown-linux-musl`, `aarch64-unknown-linux-musl` | |
| `aarch64-apple-darwin`, `x86_64-apple-darwin` | macOS 11 or later |
| `x86_64-pc-windows-msvc` | Windows 10 or later |
| `aarch64-pc-windows-msvc` | Windows 11 |

The build picks the library for the target, not for the machine it runs on,
so cross-compiling works. For Intel Macs, set `MACOSX_DEPLOYMENT_TARGET=11.0`:
Rust's default (10.12) is older than the library supports. Other targets (for example `*-windows-gnu`, iOS,
Android, WebAssembly) stop the build with a message.

The library is linked in statically: your program needs no extra file at run
time, and does not export SQLite's functions, so it doesn't clash with another
SQLite that a plugin or system library loads into the same process.

## Offline builds, mirrors

The download needs `curl` and `tar`, which come with macOS and Windows 10 and
later (on Linux, `unzip` too for Windows archives). Environment variables
change where the library comes from; set them in your shell or in
`.cargo/config.toml` under `[env]`:

- `POTLUCKDB_CORE_DIR`: a folder with the release's archives
  (`potluckdb-sqlite-<version>-<platform>.tar.gz` or `.zip`, checked against
  `SHA256SUMS` if the folder has it), or one unpacked archive. Nothing is
  downloaded.
- `POTLUCKDB_DOWNLOAD_URL`: a mirror of the releases, laid out as
  `<url>/v<version>/<archive>`.

`cargo vendor` vendors the `git` entry like any other dependency.

## Differences from rusqlite's bundled SQLite

rusqlite's `bundled` feature (and sqlx's `sqlite`) compile SQLite with
libsqlite3-sys's build options. PotluckDB's library is SQLite 3.54.1 with its
own options ([SQLite build](https://docs.potluckdb.com/reference/sqlite-build/)).
What differs:

- Foreign keys are off until you turn them on: `PRAGMA foreign_keys = ON`
  (bundled: on; sqlx turns them on itself).
- `soundex()` is not available.
- FTS3 and FTS4 queries use SQLite's standard syntax, without `AND`, `NOT`
  and parentheses (FTS5 is the same in both).
- No `sqlite_stat4` statistics; SQLite's API armor and memory management
  options are off.
- In addition, the session extension, pre-update hooks and unlock notify are
  built in, so rusqlite's `session`, `preupdate_hook` and `unlock_notify`
  features work.

## Licence

- The Rust code in this folder is Apache-2.0, except
  `libsqlite3-sys/<line>/`, which is libsqlite3-sys (MIT, the rusqlite
  developers) with the changes listed in its README.
- The library linked into your program is not open source: it comes with the
  PotluckDB binary licence (`LICENSE.txt` in each archive; pre-releases may be
  used for evaluation and development) and SQLite's public-domain notice
  (`THIRD_PARTY_NOTICES.txt`).

## Developing

```sh
cd rust
POTLUCKDB_CORE_DIR=/path/to/core-archives cargo test   # or leave it out to download the release
python3 scripts/ci.py --version 0.8.0-dev.1 --core-dir /path/to/core-archives  # all CI checks
python3 scripts/vendor_libsqlite3_sys.py   # write libsqlite3-sys/<line>/ again from crates.io
```

- `potluckdb/`: the `potluckdb` crate, published on crates.io.
- `libsqlite3-sys/0.38/`, `libsqlite3-sys/0.37/`: PotluckDB's libsqlite3-sys
  for each line, written by `scripts/vendor_libsqlite3_sys.py` from the
  published crate plus `libsqlite3-sys/potluckdb_core.rs`.
- `examples/quickstart/`: the quickstart; `tests/`: the sqlx quickstart, an
  app without the patch, and rusqlite's test suite (`scripts/rusqlite_suite.py`).

A release runs `.github/workflows/rust.yml`: it records the release's version
and SHA-256s in `potluckdb_release.rs` (`scripts/set_version.py`), tests on
all 8 platforms, tags that commit `rust-v<version>`, and publishes the
`potluckdb` crate. [DESIGN.md](DESIGN.md) explains why it works this way.
