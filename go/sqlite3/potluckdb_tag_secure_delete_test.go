//go:build cgo && sqlite_secure_delete && !sqlite_secure_delete_fast

package sqlite3

func init() { wantSecureDelete = 1 }
