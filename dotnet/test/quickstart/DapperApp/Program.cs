// Dapper on Microsoft.Data.Sqlite, unchanged.
using Dapper;
using Microsoft.Data.Sqlite;

using var connection = new SqliteConnection("Data Source=:memory:");
connection.Open(); // one in-memory database for all the queries
connection.Execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)");
connection.Execute("INSERT INTO notes (body) VALUES (@Body)", new[] { new { Body = "one" }, new { Body = "two" } });
var bodies = string.Join(",", connection.Query<string>("SELECT body FROM notes ORDER BY id"));
if (bodies != "one,two") throw new Exception($"Dapper read {bodies}");
var versions = connection.QuerySingle<(string, string)>("SELECT potluckdb_version(), sqlite_version()");
Console.WriteLine($"{versions.Item1} {versions.Item2}");
