#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), sqlx::Error> {
    let db = sqlx::SqlitePool::connect("sqlite::memory:").await?;
    let (potluckdb, sqlite): (String, String) =
        sqlx::query_as("SELECT potluckdb_version(), sqlite_version()").fetch_one(&db).await?;
    println!("{potluckdb} {sqlite}");
    assert_eq!(potluckdb, potluckdb::version());
    Ok(())
}
