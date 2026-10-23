// PotluckDB's tests of the driver; the other _test.go files are
// go-sqlite3's own.

//go:build cgo

package sqlite3

import (
	"database/sql"
	"testing"
)

// What PRAGMA foreign_keys and secure_delete return on a new connection;
// the potluckdb_tag_*_test.go files change them for their build tags.
var wantForeignKeys, wantSecureDelete = 0, 0

func TestPotluckDBVersion(t *testing.T) {
	db, err := sql.Open("sqlite3", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	var core, sqlite string
	if err := db.QueryRow("SELECT potluckdb_version(), sqlite_version()").Scan(&core, &sqlite); err != nil {
		t.Fatal(err)
	}
	if core == "" || core != CoreVersion() {
		t.Fatalf("potluckdb_version() = %q, CoreVersion() = %q", core, CoreVersion())
	}
	if lib, _, _ := Version(); lib != sqlite {
		t.Fatalf("Version() = %q, sqlite_version() = %q", lib, sqlite)
	}
}

// go-sqlite3's sqlite_foreign_keys and sqlite_secure_delete build tags set
// SQLite's compile-time defaults; the driver applies them per connection,
// and the DSN still overrides them.
func TestPotluckDBTagDefaults(t *testing.T) {
	for _, c := range []struct {
		dsn                       string
		foreignKeys, secureDelete int
	}{
		{"file::memory:", wantForeignKeys, wantSecureDelete},
		{"file::memory:?_foreign_keys=0&_secure_delete=off", 0, 0},
		{"file::memory:?_foreign_keys=1&_secure_delete=on", 1, 1},
	} {
		db, err := sql.Open("sqlite3", c.dsn)
		if err != nil {
			t.Fatal(err)
		}
		var foreignKeys, secureDelete int
		if err := db.QueryRow("PRAGMA foreign_keys").Scan(&foreignKeys); err != nil {
			t.Fatal(err)
		}
		if err := db.QueryRow("PRAGMA secure_delete").Scan(&secureDelete); err != nil {
			t.Fatal(err)
		}
		db.Close()
		if foreignKeys != c.foreignKeys || secureDelete != c.secureDelete {
			t.Errorf("%s: foreign_keys = %d, secure_delete = %d; want %d, %d",
				c.dsn, foreignKeys, secureDelete, c.foreignKeys, c.secureDelete)
		}
	}
}
