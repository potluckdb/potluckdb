# PotluckDB for Go

`github.com/potluckdb/potluckdb-go/sqlite3` is a drop-in replacement for
[go-sqlite3](https://github.com/mattn/go-sqlite3) (`github.com/mattn/go-sqlite3`)
that runs on PotluckDB's own build of SQLite. Your code stays the same; only
the import path changes.

> **Status: pre-release.** It does not sync yet; that comes in later releases.

## Quickstart

```sh
go get github.com/potluckdb/potluckdb-go/sqlite3
```

```go
import (
	"database/sql"

	_ "github.com/potluckdb/potluckdb-go/sqlite3" // was: _ "github.com/mattn/go-sqlite3"
)

db, err := sql.Open("sqlite3", "app.db")
// ...
var potluckdb, sqlite string
err = db.QueryRow("SELECT potluckdb_version(), sqlite_version()").Scan(&potluckdb, &sqlite)
// potluckdb = "0.8.0-dev.1", sqlite = "3.54.1"
```

As with go-sqlite3, cgo must be on and a C compiler installed (gcc or clang;
on Windows, MinGW-w64). Unlike go-sqlite3, nothing of SQLite is compiled: the
library comes ready-made, so the first build takes seconds instead of a
minute.

## Switching from go-sqlite3

Either change the import path, as above, or keep your code and add one line
to `go.mod` (with the version you want):

```sh
go mod edit -replace github.com/mattn/go-sqlite3=github.com/potluckdb/potluckdb-go/sqlite3@v0.8.0-dev.1
go mod tidy
```

With the `replace` line, every import of `github.com/mattn/go-sqlite3` uses
PotluckDB, including those inside your dependencies (for example GORM's
SQLite driver, `gorm.io/driver/sqlite`). Use it whenever a dependency imports
go-sqlite3: a program cannot hold both go-sqlite3 and PotluckDB, since both
register the driver name `sqlite3`.

## API

The same as go-sqlite3 1.14.52: the driver name `sqlite3`, the same
connection string options, types, errors and build tags; see its
[documentation](https://pkg.go.dev/github.com/mattn/go-sqlite3@v1.14.52).
PotluckDB adds one function:

- `sqlite3.CoreVersion()`: the PotluckDB build in use, for example
  `"0.8.0-dev.1"` (the same as `SELECT potluckdb_version()`).

## Platforms

Go downloads only the library for the platform it builds for (one module of
about 1 MB per platform).

| Platform | Go platform | Needs |
| --- | --- | --- |
| Linux x64, arm64 | linux/amd64, linux/arm64 | glibc 2.28 or later |
| Linux x64, arm64 on Alpine and other musl systems | the same, built with `-tags musl` | musl |
| macOS Apple silicon, Intel | darwin/arm64, darwin/amd64 | macOS 11 or later |
| Windows x64, arm64 | windows/amd64, windows/arm64 | not yet: see below |

On Alpine, build with `go build -tags musl`: Go cannot tell glibc from
musl by itself. A build with the wrong setting stops with a message that
says which one to use.

Windows needs a build of the library that MinGW can link, which PotluckDB's
releases do not have yet. Until they do, building for Windows stops with a
message that lists the platforms that work.

## Build tags

go-sqlite3's build tags still work:

- Features PotluckDB's library always has: FTS5, math functions, R-Tree,
  dbstat, percentile, column metadata, the pre-update hook and unlock notify.
  Their tags (`sqlite_fts5`, `sqlite_math_functions`, ...) are not needed for
  SQL. The Go functions behind some of them still need their tag, as with
  go-sqlite3: `sqlite_preupdate_hook`, `sqlite_unlock_notify`,
  `sqlite_column_metadata`, `sqlite_vtable`, `sqlite_trace`.
- `sqlite_foreign_keys`, `sqlite_secure_delete` and
  `sqlite_secure_delete_fast` turn their setting on for every new
  connection, as in go-sqlite3.
- Tags that change other compile-time options of SQLite have no effect, since
  the library is already built: `sqlite_vacuum_full`, `sqlite_vacuum_incr`,
  `sqlite_stat4`, `sqlite_icu`, `sqlite_allow_uri_authority`,
  `sqlite_app_armor`, `sqlite_introspect`, `sqlite_os_trace`. For the vacuum
  modes, use the `_auto_vacuum` connection string option.
  `PRAGMA compile_options` lists the library's options.
- `libsqlite3` (link the system's SQLite) is not supported: the driver always
  uses PotluckDB's library.

## Differences from go-sqlite3

go-sqlite3 compiles SQLite with its own options; PotluckDB's library has its
own. Defaults such as foreign keys (off), double-quoted strings and the page
cache are the same. What differs:

- In WAL mode, `synchronous` stays `FULL` (go-sqlite3: `NORMAL`). For
  go-sqlite3's behaviour, add `_synchronous=NORMAL` to the connection string.
- `DELETE ... LIMIT` and `UPDATE ... LIMIT` are not available.
- FTS3 and FTS4 queries use SQLite's standard syntax, without `AND`, `NOT`
  and parentheses (FTS5 is the same in both).
- Expanded SQL (as seen by the `sqlite_trace` hook) holds bound values in
  full, not cut at 15 bytes.

## Licence

Apache-2.0. Parts come from go-sqlite3 (MIT); see `THIRD_PARTY_NOTICES.md`.
The library modules (`github.com/potluckdb/potluckdb-go/lib/<platform>`)
contain the PotluckDB library, which has its own licence (`LICENSE.txt` in
each).

## Developing

The source is the `go/` folder of
[potluckdb/potluckdb](https://github.com/potluckdb/potluckdb). The release
writes the Go modules from it into
[potluckdb/potluckdb-go](https://github.com/potluckdb/potluckdb-go), which is
never edited by hand. `go/DESIGN.md` explains the layout.

```sh
cd go
# Every check for this machine, as users run Go: go get, go build, vendoring,
# the replace line, the program's SQLite and go-sqlite3's own tests.
POTLUCKDB_CORE_DIR=/path/to/core-archives go run ./tools test -version 0.8.0-dev.1
# The distribution repository for a release.
go run ./tools dist -version 0.8.0-dev.1 -out dist/potluckdb-go
```

Without `POTLUCKDB_CORE_DIR`, the tools download the release's archives from
GitHub. `sqlite3/` is go-sqlite3 1.14.52 without its bundled SQLite, plus
`potluckdb*.go`; `test/known-failures.txt` lists go-sqlite3's tests that are
not run, and why.
