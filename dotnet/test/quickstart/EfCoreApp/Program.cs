// EF Core on Microsoft.Data.Sqlite, unchanged.
using Microsoft.EntityFrameworkCore;

using var db = new NotesContext();
db.Database.EnsureDeleted();
db.Database.EnsureCreated();
db.Notes.Add(new Note { Body = "one" });
db.Notes.Add(new Note { Body = "two" });
db.SaveChanges();
var count = db.Notes.Count(n => n.Body.StartsWith("t"));
if (count != 1) throw new Exception($"EF Core counted {count}");
// Foreign keys are on, as with Microsoft.EntityFrameworkCore.Sqlite's e_sqlite3.
var foreignKeys = db.Database.SqlQueryRaw<long>("SELECT foreign_keys AS Value FROM pragma_foreign_keys").AsEnumerable().Single();
if (foreignKeys != 1) throw new Exception("foreign keys are off");
var potluckdb = db.Database.SqlQueryRaw<string>("SELECT potluckdb_version() AS Value").AsEnumerable().Single();
var sqlite = db.Database.SqlQueryRaw<string>("SELECT sqlite_version() AS Value").AsEnumerable().Single();
Console.WriteLine($"{potluckdb} {sqlite}");

public class Note
{
    public int Id { get; set; }
    public string Body { get; set; } = "";
}

public class NotesContext : DbContext
{
    public DbSet<Note> Notes => Set<Note>();

    protected override void OnConfiguring(DbContextOptionsBuilder options) => options.UseSqlite("Data Source=notes.db");
}
