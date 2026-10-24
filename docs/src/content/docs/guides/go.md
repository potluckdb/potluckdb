---
title: Go
description: Use PotluckDB from Go, in place of go-sqlite3.
---

`github.com/potluckdb/potluckdb-go/sqlite3` is a drop-in replacement for
[go-sqlite3](https://github.com/mattn/go-sqlite3) that runs on PotluckDB's
build of SQLite. It works on Linux (glibc 2.28+ and musl) and macOS 11+, x64
and ARM64; Windows follows in a later pre-release.

```sh
go get github.com/potluckdb/potluckdb-go/sqlite3
```

```go
import (
	"database/sql"

	_ "github.com/potluckdb/potluckdb-go/sqlite3" // was: _ "github.com/mattn/go-sqlite3"
)

db, err := sql.Open("sqlite3", "app.db")
```

The rest of your code stays the same: the driver name `sqlite3`, connection
string options, types, errors and build tags are go-sqlite3's (1.14.52). As
with go-sqlite3, cgo must be on and a C compiler installed, but nothing of
SQLite is compiled: the first build takes seconds instead of a minute.

## Without changing imports

To keep your code, and to switch dependencies that import go-sqlite3 too
(for example GORM's SQLite driver), add one `replace` line to `go.mod`:

```sh
go mod edit -replace github.com/mattn/go-sqlite3=github.com/potluckdb/potluckdb-go/sqlite3@v0.8.0-dev.2
go mod tidy
```

## Good to know

- On Alpine and other musl systems, build with `-tags musl`; a build with the
  wrong setting stops with a message saying what to do.
- `go mod tidy` and `go mod download` fetch the library for every platform;
  `go build` and `go test` use only your platform's.
- Databases sync too: `potluckdb attach app.db s3://my-bucket/app` once,
  with no code change ([Sync a database](/guides/sync-a-database/)). One
  device writes at a time for now.

All the details: [go/README.md](https://github.com/potluckdb/potluckdb/tree/main/go).
