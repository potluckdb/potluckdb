// PotluckDB's additions to go-sqlite3: the driver uses PotluckDB's build of
// SQLite, linked in from the library module of the platform it is built
// for (github.com/potluckdb/potluckdb-go/lib/<platform>, imported by the
// generated potluckdb_lib_*.go files), instead of compiling SQLite itself.

//go:build cgo

package sqlite3

/*
#cgo CFLAGS: -I${SRCDIR}
#include <stdlib.h>
#ifndef USE_LIBSQLITE3
#include "sqlite3-binding.h"
#else
#include <sqlite3.h>
#endif
#include "potluckdb.h"

// Linux has two builds of the library, for glibc and for musl, chosen with
// the musl build tag. Linking the wrong one fails with a long list of
// missing symbols, so say what to do instead.
#if defined(__linux__) && !defined(__ANDROID__)
# if defined(POTLUCKDB_MUSL) && defined(__GLIBC__)
#  error "PotluckDB: the C compiler uses glibc, but the build has -tags musl. Build without -tags musl."
# elif !defined(POTLUCKDB_MUSL) && !defined(__GLIBC__)
#  error "PotluckDB: the C compiler does not use glibc. On Alpine and other musl systems, build with -tags musl, e.g. go build -tags musl"
# endif
#endif

#define POTLUCKDB_STR2(x) #x
#define POTLUCKDB_STR(x) POTLUCKDB_STR2(x)

// go-sqlite3's build tags that change SQLite's compile-time defaults
// (they define the macros below) do nothing to a library that is already
// built. For those whose default is a per-connection setting, apply it
// when a connection opens.
static int potluckdb_connection_defaults(sqlite3 *db) {
	int rv = SQLITE_OK;
#if defined(SQLITE_DEFAULT_FOREIGN_KEYS) && SQLITE_DEFAULT_FOREIGN_KEYS
	rv = sqlite3_db_config(db, SQLITE_DBCONFIG_ENABLE_FKEY, 1, (int *)0);
	if (rv != SQLITE_OK) return rv;
#endif
#if defined(SQLITE_SECURE_DELETE)
	rv = sqlite3_exec(db, "PRAGMA secure_delete = " POTLUCKDB_STR(SQLITE_SECURE_DELETE), 0, 0, 0);
#endif
	return rv;
}
*/
import "C"

// CoreVersion returns the version of the PotluckDB library the program
// is linked with, for example "0.8.0-dev.1". SQL reads the same with
// SELECT potluckdb_version().
func CoreVersion() string {
	return C.GoString(C.potluckdb_version())
}

// applyConnectionDefaults applies the build tags' SQLite defaults to a
// new connection, before the DSN's settings.
func applyConnectionDefaults(db *C.sqlite3) error {
	if C.potluckdb_connection_defaults(db) != C.SQLITE_OK {
		return lastError(db)
	}
	return nil
}
