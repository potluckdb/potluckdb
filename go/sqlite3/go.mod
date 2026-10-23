// The driver module. The release writes its own go.mod for it, with the
// library modules of its version (go run ./tools dist); this one only marks
// the folder as a module of its own.
module github.com/potluckdb/potluckdb-go/sqlite3

go 1.21
