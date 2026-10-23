# PotluckDB for Go: design

How the Go package is laid out, why, and the evidence for it. The decisions
it builds on are PRD D7: one Go module per platform, in a distribution
repository that only the release writes; `go get` must not download other
platforms' binaries; PotluckDB's C library is linked statically.

## What users change

One of:

- the import path: `github.com/mattn/go-sqlite3` becomes
  `github.com/potluckdb/potluckdb-go/sqlite3`; `sql.Open("sqlite3", ...)`
  and everything else stays;
- or nothing in the code, and one line in `go.mod`:
  `replace github.com/mattn/go-sqlite3 => github.com/potluckdb/potluckdb-go/sqlite3 v0.8.0-dev.1`.
  This also covers go-sqlite3 imported by a dependency, such as GORM's
  SQLite driver.

On Alpine and other musl systems, builds add `-tags musl`.

## Layout

The distribution repository, `github.com/potluckdb/potluckdb-go`:

```
README.md                    what the repository is (generated)
.gitattributes               "* -text": every file stays byte for byte
sqlite3/                     module github.com/potluckdb/potluckdb-go/sqlite3: the driver
  *.go, *.c                  go-sqlite3 1.14.52 without its SQLite, plus potluckdb*.go
  sqlite3-binding.h          the release's sqlite3.h, under go-sqlite3's name for it
  potluckdb.h                the release's potluckdb.h
  potluckdb_lib_<target>.go  generated: imports lib/<target> on its platform
  potluckdb_lib_none.go      generated: on any other platform, a build error that says so
  go.mod                     generated: requires every lib module at the same version
  LICENSE, THIRD_PARTY_NOTICES.md, README.md
lib/<target>/                module github.com/potluckdb/potluckdb-go/lib/<target>, one per platform
  libsqlite3.a               the core archive's static library, byte for byte
  lib.go                     #cgo LDFLAGS: ${SRCDIR}/libsqlite3.a (+ -lm -ldl -lpthread on Linux)
  doc.go                     package documentation, and the version marker (below)
  go.mod, LICENSE.txt, THIRD_PARTY_NOTICES.txt, BUILD-INFO.json
```

Targets are named like the core archives: `linux-{x64,arm64}-{gnu,musl}`,
`macos-{arm64,x64}`, `windows-{x64,arm64}`. Each release is one commit on
`main` and one tag per module: `sqlite3/v<version>` and
`lib/<target>/v<version>`.

How a build finds the library:

1. The program imports the driver. Of the driver's `potluckdb_lib_*.go`
   files, the build constraints keep exactly one, which imports that
   platform's library package: `linux && !android && amd64 && !musl` picks
   `lib/linux-x64-gnu`, the same with `musl` picks `lib/linux-x64-musl`,
   `darwin && !ios && arm64` picks `lib/macos-arm64`, and so on.
2. The library package's `#cgo LDFLAGS: ${SRCDIR}/libsqlite3.a` reaches the
   final link (cgo passes every package's LDFLAGS to the external linker).
   `${SRCDIR}` is the package's folder wherever Go put it: the module cache,
   `vendor/`, or a folder named by a `replace`.
3. The driver's C code includes `"sqlite3-binding.h"`, the release's
   `sqlite3.h`. go-sqlite3's sources already include it under that name, so
   they stay unchanged, and a `sqlite3.h` elsewhere on the include path (from
   `CGO_CFLAGS`, Homebrew and so on) is never picked by mistake.
4. Versions stay together: the driver's `go.mod` requires each library
   module at its own version, and each library package defines
   `IsVersion0_8_0_dev_1` (for 0.8.0-dev.1), which the driver of that
   version uses. If a `go.mod` asks for a library of another version, the
   build stops at that line, whose comment says what to do (protobuf's
   generated code checks its runtime the same way).

The core archives' libraries have hidden symbols, so a program exports none
of SQLite's functions and never clashes with another SQLite that a shared
library brings in.

## Evidence

Everything below was run with Go 1.27.2 against the modules generated from
the 0.8.0-dev.0 archives, served by a module proxy on disk exactly as
proxy.golang.org will serve them once tagged (`go run ./tools test` does
all of it on each platform).

| Question | Result |
| --- | --- |
| `go build`, `go run`, `go test` with `go.mod`/`go.sum` done and an empty module cache | download the driver and only this platform's library module. Checked on every platform tested ("fresh module cache"). |
| `go get github.com/potluckdb/potluckdb-go/sqlite3@...` | downloads every library module (8 x about 1 MB) |
| `go mod tidy`, `go mod download`, `go mod vendor` | the same: all library modules |
| Library in the read-only module cache, via `${SRCDIR}` | links and runs |
| `go mod vendor`, then a build with `GOPROXY=off` and an empty module cache | links and runs: vendoring copies every file of a package's own folder, so `libsqlite3.a` next to `lib.go` is kept (files in sub-folders that are not packages would be dropped, so modules are flat) |
| `-trimpath` | links and runs |
| `replace github.com/mattn/go-sqlite3 => .../sqlite3 v...` | works, also when go-sqlite3 is imported by a dependency; the replacement module may declare its own path |
| `CGO_ENABLED=0` | builds; the program fails at `sql.Open` saying it needs cgo (go-sqlite3's behaviour) |
| Wrong libc (`-tags musl` on glibc, or none on Alpine) | the build stops with a message naming the fix |
| Library module of another version in `go.mod` | the build stops at the version marker |
| Platform without a library (for example Windows today) | the build stops: "PotluckDB has no SQLite library for this platform. It has one for ..." |
| The tree published with `scripts/publish.sh` into a git repository, then fetched by Go itself from git (`GOPROXY=direct`, as proxy.golang.org fetches) | the tags resolve, the quickstart runs, and `go.sum` is identical to the one from the proxy on disk |

Sizes: a library module is 0.96 to 1.06 MB zipped, 2.1 to 2.3 MB unpacked
(the libraries have no debug information); the driver module is 314 KB. For
comparison, go-sqlite3's module is 2.9 MB and its first build compiles a
9.5 MB C file; PotluckDB's first build only links, in about 2 seconds.

### Why `go get` downloads every platform's library

`go get <package>`, `go mod tidy`, `go mod download` and `go mod vendor`
look at a package's imports for all platforms and build tags at once,
because they write a `go.sum` and `vendor/` that must work on every
platform. To read a package's imports, Go downloads its module. So any
layout in which a plain `go build` works on every platform, with no extra
step, has every platform's library downloaded by these commands. The only
ways around it make users name their platform themselves (import a
platform module, or pass a flag), which breaks cross-compiling and the
`replace` route, and changes far more than an import path.

So D7's rule holds for building, running and testing (`go build`, `go run`,
`go test`, `go run pkg@version` and `go install pkg@version`, and CI from a
`go.sum`), and not for `go get` and `go mod`: those fetch about 8 MB once,
into the module cache. Other layouts considered:

- One module with all eight libraries: every build would download all of
  them; worse in every case.
- The driver in this repository (`github.com/potluckdb/potluckdb/go/sqlite3`):
  needs tags here and the SQLite header committed; D7 puts the modules in
  the distribution repository.
- The driver at the repository root (`import "github.com/potluckdb/potluckdb-go"`):
  the path would not end in the package name `sqlite3`, and leaves no room
  beside it for, say, a DuckDB driver.
- Linking the shared library: not static (D7), and programs would need the
  library next to them at run time.

### Musl

Go has no build constraint for the C library, so Linux has the `musl` tag:
without it the glibc library is used, with it the musl library. The driver
checks the C compiler's libc (`__GLIBC__`) and stops a mismatched build with
a message, instead of a long list of missing symbols at link time.

## Windows: the MSVC library does not link with MinGW

cgo on Windows uses MinGW-w64 (gcc, or clang from llvm-mingw); it cannot
use MSVC. The archives' static library, `lib/static/sqlite3.lib` (MSVC,
`/MT /Zl`), does not link with MinGW. It needs parts of the MSVC C runtime
that MinGW does not have:

- x64: `__security_cookie`, `__security_check_cookie`, `__GSHandlerCheck`
  and `__report_rangecheckfailure` (MSVC's `/GS` buffer checks), `__chkstk`
  (MSVC's stack probe) and `__isa_available`; GNU ld also warns about the
  library's `/alternatename` directive;
- arm64: as well `__security_push_cookie`, `__security_pop_cookie` and
  `__GSHandlerCheck_SEH`.

A small file defining the x64 helpers makes the library link and run (tried:
`0.8.0-dev.0 3.54.1`), but it re-implements MSVC runtime internals, the
arm64 helpers have conventions that are not documented, and every build
would print a linker warning. It is not used.

**Proposed change to the core build:** add a MinGW-built static library to
both Windows archives, as `lib/static/libsqlite3.a` (listed in
`BUILD-INFO.json`), next to the MSVC one. The core's `CMakeLists.txt` needs
no change: its non-MSVC branch already builds `sqlite3_static` with the same
options and hidden symbols. For example, with llvm-mingw (one toolchain for
both CPUs):

```sh
cmake -S . -B build-mingw-x64 -G Ninja -DCMAKE_SYSTEM_NAME=Windows \
  -DCMAKE_C_COMPILER=x86_64-w64-mingw32-clang -DCMAKE_BUILD_TYPE=Release -DPOTLUCKDB_VERSION=<version>
cmake --build build-mingw-x64 --target sqlite3_static     # static/libsqlite3.a
# arm64: the same with aarch64-w64-mingw32-clang
```

Tested with what works: built that way from core commit `bcb76b4` (the
0.8.0-dev.0 source) with llvm-mingw 20260922, added to copies of the two
Windows archives, the generated Windows modules

- link with MinGW-w64 gcc 13 (msvcrt) and with llvm-mingw clang (UCRT);
- run on Windows 11 x64, with Go and llvm-mingw installed as the CI job
  installs them: every check of `tools test` passes (the quickstart prints
  `0.8.0-dev.0 3.54.1` built normally, with `-trimpath`, from `vendor/` and
  through `replace`; go-sqlite3's tests pass);
- link for windows/arm64 (not run: no arm64 Windows machine here).

The generator uses `lib/static/libsqlite3.a` from a Windows archive when it
is there. Until then it writes no Windows modules: the driver does not
require them, and a Windows build stops with the message above. The CI
matrix skips Windows with a notice until a release has the library.

## Checks of the program

`go run ./tools check-binary` (also run on every platform by `tools test`)
proves that a program holds PotluckDB's SQLite and no other:

- the program holds exactly one SQLite source id (every SQLite build embeds
  the date and hash of its source), and it is the one in the release's
  `sqlite3.h`;
- SQLite's file header string occurs no more often than in the library
  itself (a second SQLite adds more);
- on Linux, `sqlite3_open_v2`, `sqlite3_libversion` and `potluckdb_version`
  are each defined once in the symbol table (on macOS: where the symbol
  table has them);
- no SQLite shared library is loaded (ELF `NEEDED`, Mach-O load commands,
  PE imports), and none of `sqlite3_*`/`potluckdb_*` is exported.

A program built with go-sqlite3 itself fails it ("does not hold PotluckDB's
SQLite", and no `potluckdb_version`). On AlmaLinux 8's older linker, Go
exports every global symbol of the program; the library's still stay
hidden.

## go-sqlite3's tests

`tools test` runs go-sqlite3's own test suite (its `_test.go` files, kept in
`sqlite3/`) against PotluckDB's library, three times: without tags; with
the tags of features the library has (`sqlite_vtable`,
`sqlite_preupdate_hook`, `sqlite_unlock_notify`, `sqlite_column_metadata`,
`sqlite_math_functions`, `sqlite_fts5`, `sqlite_serialize`); and with
`sqlite_foreign_keys sqlite_secure_delete`, whose defaults the driver applies
per connection. Results (including PotluckDB's two tests in
`potluckdb_test.go`):

| Platform | Where | No tags | Feature tags | `sqlite_foreign_keys sqlite_secure_delete` |
| --- | --- | --- | --- | --- |
| linux-x64-gnu | Ubuntu 24.04 (gcc 13); AlmaLinux 8 (glibc 2.28, gcc 8.5) | 100/100 | 111/111 | 100/100 |
| linux-arm64-gnu | cross gcc 13, run under QEMU | 100/100 | 111/111 | 100/100 |
| linux-x64-musl | Alpine 3.22 | 99/99 + 1 not run | 110/110 + 1 | 99/99 + 1 |
| linux-arm64-musl | Alpine 3.22 arm64 gcc, under QEMU | 99/99 + 1 not run | 110/110 + 1 | 99/99 + 1 |
| macos-arm64 | macOS 26.6, Apple silicon | 100/100 | 111/111 | 100/100 |
| macos-x64 | the same Mac, under Rosetta | 100/100 | 111/111 | 100/100 |
| windows-x64 | Windows 11, llvm-mingw clang (with the proposed MinGW library) | 100/100 | 111/111 | 100/100 |

The one test not run on musl, `TestRowsContextPanicClearsActiveRows`
(`test/known-failures.txt`), panics inside an SQL function. The panic
unwinds through `sqlite3_step` and leaves the connection's lock held when
the connection is freed; musl keeps every held lock in a per-thread list,
so later locking writes into freed memory and later tests in the same
process fail or crash. go-sqlite3's own build crashes the same way on musl
(one full run in three here). It passes by itself.

## Release

`.github/workflows/go.yml`, against a published release (all 8 core
archives, checked against `SHA256SUMS`):

1. `test`: every check above, per platform (Linux x64 for changes under
   `go/`; all 8 nightly, by hand, and from the release).
2. `dist`: `go run ./tools dist` writes the distribution repository's
   content; it is uploaded as the artifact `potluckdb-go-<version>`.
3. `publish` (only with `publish: true`), with `scripts/publish.sh`: one
   commit on `main` of `potluckdb/potluckdb-go` with exactly that content,
   and the tags `sqlite3/v<version>` and `lib/<target>/v<version>`. An
   existing tag is never moved, since Go's checksum database makes a module
   version permanent once fetched: if all tags exist with the same content
   it does nothing, otherwise it fails. Then it asks proxy.golang.org for
   each new version. (Tried against a local repository: first publish, a
   re-run, a refused second content for the same version, the next
   version.)

`release.yml` starts `go.yml` with `publish: true` once the repository
variable `GO_PUBLISHING` is `true`.

What publishing needs, to set up once:

- the repository `potluckdb/potluckdb-go` (public, may be empty);
- a deploy key on it with write access; its private key as the secret
  `GO_DIST_DEPLOY_KEY` in an environment `go` of `potluckdb/potluckdb`,
  limited to the `main` branch (a deploy key reaches only that one
  repository, and needs no user account);
- the repository variable `GO_PUBLISHING=true` in `potluckdb/potluckdb`.

## Not verified yet

- Anything in CI against a real release: none exists yet, so `go.yml`'s
  test, dist and publish jobs have not run. Their test commands are the ones
  run by hand above (on Windows with Go and llvm-mingw set up as the job
  sets them up); the job steps around them, and the publish job, have not
  run anywhere.
- Windows with the archives as they are: no Go module until the core build
  adds a MinGW library. windows/arm64 has been linked but not run.
- `go get` through the real proxy.golang.org and sum.golang.org, and pushing
  to GitHub with the deploy key: tested with a proxy on disk and a local git
  repository, which give the same module checksums.
