// sqlite-net-pcl: the call at startup keeps it from setting up its own SQLite.
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
