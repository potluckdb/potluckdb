//! PotluckDB for Rust.
//!
//! Your app gets PotluckDB's build of SQLite through one entry in
//! `[patch.crates-io]`, which replaces `libsqlite3-sys`, the crate that
//! rusqlite, sqlx and diesel link SQLite through (see the README). This crate
//! is optional: it fails the build if that entry is missing or is for another
//! PotluckDB version, and it says which build is running. Sync comes in later
//! releases.
//!
//! ```
//! assert_eq!(potluckdb::version(), potluckdb::VERSION);
//! assert!(potluckdb::sqlite_version().starts_with("3."));
//! ```

use core::ffi::{c_char, CStr};

/// SQLite's C API: the `libsqlite3-sys` crate, here PotluckDB's.
pub use libsqlite3_sys as ffi;

/// The PotluckDB version this crate is for, for example `"0.8.0-dev.1"`. The
/// build fails unless the linked library has the same version, so this equals
/// [`version()`].
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

extern "C" {
    // From potluckdb.h: the PotluckDB build the library comes from.
    fn potluckdb_version() -> *const c_char;
}

/// The PotluckDB version of the SQLite library in this program, for example
/// `"0.8.0-dev.1"`: the same as `SELECT potluckdb_version()`.
pub fn version() -> &'static str {
    // SAFETY: potluckdb_version() returns a static, NUL-terminated string.
    unsafe { CStr::from_ptr(potluckdb_version()) }.to_str().unwrap_or_default()
}

/// The SQLite version of that library, for example `"3.54.1"`: the same as
/// `SELECT sqlite_version()`.
pub fn sqlite_version() -> &'static str {
    // SAFETY: sqlite3_libversion() returns a static, NUL-terminated string.
    unsafe { CStr::from_ptr(ffi::sqlite3_libversion()) }.to_str().unwrap_or_default()
}
