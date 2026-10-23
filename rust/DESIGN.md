# Design: how a Rust app gets PotluckDB's SQLite

**Decision:** PotluckDB ships its own `libsqlite3-sys` in this repository, and
an app switches to it with one `[patch.crates-io]` entry in `Cargo.toml`. The
optional `potluckdb` crate on crates.io turns a missing or wrong entry into a
build error.

## The constraint

rusqlite, sqlx and diesel all link SQLite through one crate,
`libsqlite3-sys`, which declares `links = "sqlite3"`: only one crate in a
build may link SQLite. So whatever we ship has to replace `libsqlite3-sys`
itself, or steer its build script; adding a second SQLite crate next to it is
a build error.

## Options compared

All prototyped with rusqlite 0.40.2 (and sqlx 0.9.0 for the chosen one) on
Linux x64, against the 0.8.0-dev.0 archives.

| Option | What the app changes | `bundled` on (rusqlite, sqlx default) | Offline | Cross-compiling, all 8 targets | Result |
| --- | --- | --- | --- | --- | --- |
| **A. `[patch.crates-io]` to PotluckDB's `libsqlite3-sys` (git)** | 2 lines in `Cargo.toml` | works | `POTLUCKDB_CORE_DIR`, or after the first build | picks the target's archive by itself | **chosen** |
| B. libsqlite3-sys's own variables in `.cargo/config.toml` `[env]` | 5 lines in another file, plus download and unpack the archive by hand | works, with `LIBSQLITE3_SYS_USE_PKG_CONFIG=1` | yes | `[env]` can't differ per target: one config per target | works, but easy to get silently wrong |
| C. A build-time helper (`cargo potluckdb setup`) writing B's config | install a tool, run it | as B | as B | as B | B's problems remain |
| D. Our own crate on crates.io in place of `libsqlite3-sys` | — | — | — | — | impossible (below) |
| E. A fork of rusqlite on crates.io (`rusqlite = { package = "potluckdb-rusqlite" }`) | 1 line | works | yes | yes | breaks every crate built on rusqlite; no sqlx, diesel |
| F. A crate that only puts our library first on the linker's search path | 1 line | **fails silently** (bundled SQLite wins) | yes | yes | rejected |

Why the others lose:

- **B** relies on five variables, and one missing variable gives no error:
  without `SQLITE3_NO_PKG_CONFIG=1`, an installed `libsqlite3-dev` is found
  by pkg-config and linked instead (tried: the query failed with "no such
  function: potluckdb_version"). Cargo reads `.cargo/config.toml` from the
  directory it runs in, so `cargo build --manifest-path` from elsewhere
  silently builds with the usual SQLite. The archive path is per platform,
  and `[env]` has no per-target form.
- **D**: `[patch]` replaces a crate by its *name*, and accepts only a source
  other than crates.io. Cargo refuses a crates.io package as a patch for a
  crates.io package ("points to the same source"), and a package with another
  name is "not used in the crate graph". Only the rusqlite developers can
  publish a crate named `libsqlite3-sys`.
- **E**: r2d2_sqlite, rusqlite_migration, tokio-rusqlite and the like depend
  on the real rusqlite, so the build then has two crates linking `sqlite3`
  and stops. It also means maintaining a fork of a 25,000-line crate.
- **F**: works only while `libsqlite3-sys` links a system library; with
  `bundled` (rusqlite's most common setup and sqlx's default) the bundled
  SQLite is used and nothing says so (tried).

## How A works

`rust/libsqlite3-sys/<line>/` is the published `libsqlite3-sys` (MIT),
downloaded from crates.io and checked against its index by
`scripts/vendor_libsqlite3_sys.py`. Changed: its build script first runs
`potluckdb_core.rs`, which finds the archive for the target (from
`POTLUCKDB_CORE_DIR`, or downloaded from the GitHub release with `curl` and
checked against the SHA-256 recorded for that release), then sets
libsqlite3-sys's own variables so that its unchanged code links
`lib/static` with the archive's headers. The name, version, `links`, features
and dependencies stay as published, so the folder stands in for exactly that
version. The build script needs no extra dependencies (SHA-256 is computed
in place), so it adds nothing that could clash with an app's own versions.

One folder per `libsqlite3-sys` line, because each consumer accepts only
some: rusqlite 0.40 needs 0.38, sqlx 0.9 needs 0.37 (or older). Both folders
are in one tag, so the entry names its line with `version = "0.38"`; with two
candidates and no `version`, Cargo stops and asks for one.

Measured on Linux x64 (16 cores), the quickstart from a clean target folder:

| | rusqlite `bundled` | PotluckDB |
| --- | --- | --- |
| Debug build | 7.0 s | 1.8 s |
| Release build | 32.7 s | 1.9 s |
| Release program | 2.5 MB | 2.3 MB |

### Static, not dynamic

The archive's static library is linked in. The program needs no extra file
at run time (single-file programs and `scratch` container images work), and
doesn't export SQLite's functions (symbols are
hidden), so it can't clash with another SQLite in the process. Dynamic
linking would need the shared library shipped next to the program and found
at run time; a dependency's build script cannot set the program's library
path (`rpath`), and if the wrong `libsqlite3.so` is found the program quietly
runs on it. It can be added later as an opt-in if someone needs it.

### Versions and tags

One version number: the `potluckdb` crate's version is the PotluckDB
version, and PotluckDB's `libsqlite3-sys` names the release it links in
`potluckdb_release.rs`. A git dependency builds exactly the files at its
tag, so those files must already name the release. After a release,
`rust.yml` writes the version and every archive's SHA-256 into the files
(`scripts/set_version.py`), commits that on top of the release's commit, tags
it `rust-v<version>`, and publishes the crate. Apps then accept only those
exact archives.

Simpler alternative, if wanted: `release.yml` runs `set_version.py` before
its release-notes commit. The release tag `v<version>` itself then works in
`[patch.crates-io]`, and `rust-v` tags go away. That is one more line in
`release.yml`.

### What A costs

- A copy of `libsqlite3-sys` per supported line. Adding a line (for example
  0.30 for sqlx 0.8) or a new upstream release is one entry in
  `VERSIONS` in `scripts/vendor_libsqlite3_sys.py`. CI checks that the
  folders match what the script writes.
- If the entry's line doesn't match the app's, Cargo only warns. The
  `potluckdb` crate makes that a build error; the README recommends it.
- `[patch]` applies only in the workspace root, so a library crate can't
  impose it on its users. That suits SQLite: the app decides which one runs.
- Builds download with `curl` and unpack with `tar` (both in macOS and
  Windows 10 and later) unless `POTLUCKDB_CORE_DIR` is set.

## Tested

| Platform | How | Result |
| --- | --- | --- |
| Linux x64 glibc | WSL (Ubuntu 24.04), and AlmaLinux 8 (glibc 2.28) in Docker | all checks pass |
| Linux x64 musl | Alpine 3.22 in Docker, and cross-built from glibc | all checks pass |
| Linux arm64 glibc, musl | cross-built from x64, run under QEMU | quickstarts pass |
| macOS arm64 | Apple silicon Mac | all checks pass |
| macOS x64 | cross-built on the Apple silicon Mac, run under Rosetta | all checks pass |
| Windows x64 | Windows 11, MSVC | all checks pass |
| Windows arm64 | not tested (no machine; CI runs it once a release exists) | |

"All checks" is `scripts/ci.py`: the potluckdb crate's tests, the rusqlite
and sqlx quickstarts, the binary check (exactly one SQLite in the program,
PotluckDB's, and no shared SQLite loaded), rusqlite 0.40.2's own test suite
with `bundled-full` (334 passed, 3 ignored, 0 failed), the build error
without the patch, and the download path (served locally) including a
changed archive being refused. rusqlite's suite also passes with
`modern-full`, with default features, and with `session` and
`preupdate_hook` (bindgen run on PotluckDB's header).

## For the core team

- When the static library starts to contain Rust code (the sync engine), it
  must keep only its C API global, for example by linking it into one
  relocatable object and making everything else local. Otherwise its copy of
  the Rust standard library clashes with the app's when a Rust program links
  it.
- Rust's default for `x86_64-apple-darwin` is macOS 10.12, so Intel Mac
  programs claim to run on systems older than the library supports. The
  README says to set `MACOSX_DEPLOYMENT_TARGET=11.0`.
