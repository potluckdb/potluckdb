// Fails the build unless libsqlite3-sys is PotluckDB's, for the same PotluckDB
// version as this crate. PotluckDB's libsqlite3-sys (rust/libsqlite3-sys/)
// says so through its build script's `potluckdb_version` value, which Cargo
// passes here as DEP_SQLITE3_POTLUCKDB_VERSION. Without this check, a missing
// or mismatched [patch.crates-io] entry would only make Cargo print a warning,
// and the app would quietly run on another SQLite.
use std::env;

const REPOSITORY: &str = "https://github.com/potluckdb/potluckdb";

fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-env-changed=DOCS_RS");
    if env::var_os("DOCS_RS").is_some() {
        return; // docs.rs builds the documentation with the standard libsqlite3-sys
    }
    let version = env::var("CARGO_PKG_VERSION").expect("CARGO_PKG_VERSION");
    match env::var("DEP_SQLITE3_POTLUCKDB_VERSION") {
        Ok(core) if core == version => {}
        Ok(core) => fail(&format!(
            "potluckdb {version} needs PotluckDB's libsqlite3-sys for {version}, but this build's \
             is for PotluckDB {core}.\nIn [patch.crates-io], change the tag to \"rust-v{version}\", \
             or require potluckdb = \"={core}\"."
        )),
        Err(_) => fail(&format!(
            "this build has the standard libsqlite3-sys, so your app would not run on PotluckDB's \
             SQLite. Add this to the Cargo.toml at the root of your workspace:\n\n\
             [patch.crates-io]\n\
             libsqlite3-sys = {{ git = \"{REPOSITORY}\", tag = \"rust-v{version}\", version = \"0.38\" }}\n\n\
             Use version = \"0.37\" instead if `cargo tree -i libsqlite3-sys` shows 0.37 \
             (rusqlite 0.39, sqlx 0.9)."
        )),
    }
}

fn fail(message: &str) -> ! {
    eprintln!("error: potluckdb: {message}");
    std::process::exit(1);
}
