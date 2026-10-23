//go:build cgo && sqlite_foreign_keys

package sqlite3

func init() { wantForeignKeys = 1 }
