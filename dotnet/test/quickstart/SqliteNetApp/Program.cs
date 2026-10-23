// sqlite-net-base, with the one call it needs at startup.
using SQLite;

SQLitePCL.Batteries_V2.Init();

using var db = new SQLiteConnection(":memory:");
db.CreateTable<Note>();
db.Insert(new Note { Body = "one" });
if (db.Table<Note>().Count() != 1) throw new Exception("sqlite-net lost a row");
Console.WriteLine($"{db.ExecuteScalar<string>("SELECT potluckdb_version()")} {db.ExecuteScalar<string>("SELECT sqlite_version()")}");

public class Note
{
    [PrimaryKey, AutoIncrement] public int Id { get; set; }
    public string Body { get; set; } = "";
}
