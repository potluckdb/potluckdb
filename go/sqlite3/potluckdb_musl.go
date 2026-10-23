// With -tags musl, the driver links the musl build of PotluckDB's library
// (see potluckdb.go).

//go:build cgo && linux && musl

package sqlite3

// #cgo CFLAGS: -DPOTLUCKDB_MUSL
import "C"
