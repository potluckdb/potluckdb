// The quickstart in dotnet/README.md: Microsoft.Data.Sqlite, unchanged.
using Microsoft.Data.Sqlite;

using var connection = new SqliteConnection("Data Source=app.db");
connection.Open();
var command = connection.CreateCommand();
command.CommandText = "SELECT potluckdb_version(), sqlite_version()";
using var reader = command.ExecuteReader();
reader.Read();
Console.WriteLine($"{reader.GetString(0)} {reader.GetString(1)}");
