// The quickstart of go/README.md: database/sql with the driver name
// "sqlite3", as with github.com/mattn/go-sqlite3.
package main

import (
	"database/sql"
	"fmt"
	"log"

	_ "github.com/potluckdb/potluckdb-go/sqlite3" // was: _ "github.com/mattn/go-sqlite3"
)

func main() {
	db, err := sql.Open("sqlite3", "app.db")
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()

	var potluckdb, sqlite string
	err = db.QueryRow("SELECT potluckdb_version(), sqlite_version()").Scan(&potluckdb, &sqlite)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(potluckdb, sqlite) // 0.8.0-dev.1 3.54.1
}
