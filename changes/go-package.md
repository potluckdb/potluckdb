type: added

Go: `go get github.com/potluckdb/potluckdb-go/sqlite3` adds a drop-in replacement for go-sqlite3 (`github.com/mattn/go-sqlite3`) that runs on PotluckDB's SQLite. Change the import path, or add one `replace` line to `go.mod`, and your code keeps working, on Linux and macOS; Windows follows once the release has a library that MinGW can link.
