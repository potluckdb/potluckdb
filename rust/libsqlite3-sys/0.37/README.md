# libsqlite3-sys 0.37.0, linking PotluckDB's SQLite

This folder is [libsqlite3-sys 0.37.0](https://crates.io/crates/libsqlite3-sys/0.37.0)
from crates.io, changed to link PotluckDB's build of SQLite instead of its
bundled or the system SQLite. Apps use it through `[patch.crates-io]`; see
[rust/README.md](../../README.md).

It is written by `rust/scripts/vendor_libsqlite3_sys.py`; don't edit it by
hand. What changed from the published crate:

- `build.rs`: libsqlite3-sys's `main` is renamed `upstream_main`; the new
  `main` at the end runs `potluckdb_core::configure()` first, which finds or
  downloads PotluckDB's library and points libsqlite3-sys's own build logic
  at it.
- `potluckdb_core.rs`, `potluckdb_release.rs`: added.
- `Cargo.toml`: `publish = false`, description, licence and links.
- The bundled SQLite and SQLCipher sources are left out.

## Licence

- Files from libsqlite3-sys: MIT, see `LICENSE-MIT`.
- `potluckdb_core.rs`, `potluckdb_release.rs` and the end of `build.rs`:
  Apache-2.0, see the repository's `LICENSE`.
- The SQLite library linked at build time is not part of this folder. It
  comes with the PotluckDB binary licence (`LICENSE.txt` in its archive) and
  SQLite's public-domain notice (`THIRD_PARTY_NOTICES.txt`).
