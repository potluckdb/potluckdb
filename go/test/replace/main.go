// A program that uses github.com/mattn/go-sqlite3 (directly here; through
// a library such as GORM's SQLite driver works the same). With
//
//	replace github.com/mattn/go-sqlite3 => github.com/potluckdb/potluckdb-go/sqlite3 v0.8.0-dev.1
//
// in go.mod it runs on PotluckDB's SQLite without any change to the code.
package main

import (
	"database/sql"
	"fmt"
	"log"

	_ "github.com/mattn/go-sqlite3"
)

func main() {
	db, err := sql.Open("sqlite3", "file:app.db?_foreign_keys=1")
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()

	var potluckdb, sqlite string
	err = db.QueryRow("SELECT potluckdb_version(), sqlite_version()").Scan(&potluckdb, &sqlite)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(potluckdb, sqlite)
}
