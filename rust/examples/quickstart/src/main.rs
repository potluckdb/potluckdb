use rusqlite::Connection;

fn main() -> rusqlite::Result<()> {
    let db = Connection::open_in_memory()?;
    let (potluckdb, sqlite): (String, String) =
        db.query_row("SELECT potluckdb_version(), sqlite_version()", [], |row| Ok((row.get(0)?, row.get(1)?)))?;
    println!("{potluckdb} {sqlite}"); // 0.8.0-dev.1 3.54.1
    assert_eq!(potluckdb, potluckdb::version());
    Ok(())
}
