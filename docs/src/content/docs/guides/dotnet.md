---
title: .NET
description: Use PotluckDB from .NET with Microsoft.Data.Sqlite, Dapper, EF Core or sqlite-net.
---

`PotluckDB.Data.Sqlite` on NuGet runs Microsoft.Data.Sqlite on PotluckDB's
build of SQLite. Dapper and EF Core on top keep working; only a package
reference changes. It works on .NET 8 and later, on Linux (glibc 2.28+ and
musl), macOS 11+ and Windows, x64 and ARM64.

```sh
dotnet add package PotluckDB.Data.Sqlite --prerelease
```

```csharp
using Microsoft.Data.Sqlite;

using var connection = new SqliteConnection("Data Source=app.db");
connection.Open();
var command = connection.CreateCommand();
command.CommandText = "SELECT potluckdb_version(), sqlite_version()";
using var reader = command.ExecuteReader();
reader.Read();
Console.WriteLine($"{reader.GetString(0)} {reader.GetString(1)}"); // 0.8.0-dev.1 3.54.1
```

## What to change

| You use | Replace | With | Code changes |
| --- | --- | --- | --- |
| Microsoft.Data.Sqlite, Dapper | `Microsoft.Data.Sqlite` | `PotluckDB.Data.Sqlite` | none |
| EF Core | `Microsoft.EntityFrameworkCore.Sqlite` | `Microsoft.EntityFrameworkCore.Sqlite.Core` and `PotluckDB.Data.Sqlite` | none |
| sqlite-net | `sqlite-net-pcl` | `sqlite-net-base` and `PotluckDB.SQLitePCLRaw` | call `SQLitePCL.Batteries_V2.Init();` once at startup |
| SQLitePCLRaw directly | `SQLitePCLRaw.bundle_e_sqlite3` | `PotluckDB.SQLitePCLRaw` | none |

The build stops with error POTLUCKDB001 if the project also gets another
SQLite bundle (for example `Microsoft.Data.Sqlite` kept next to
`PotluckDB.Data.Sqlite`), because the app might then quietly run on that
SQLite. Remove the other package as the table says.

## Good to know

- Databases sync in a later pre-release (0.8.2); for now it runs queries
  exactly like Microsoft.Data.Sqlite.
- Microsoft.Data.Sqlite's own test suite passes against it on every platform.
- Foreign keys are on, as with Microsoft.Data.Sqlite's default SQLite.
- `Password=` in the connection string has no effect: the library doesn't
  encrypt databases.
- File names starting with `file:` are read as [URIs](https://sqlite.org/uri.html).
- Not yet: .NET Framework, iOS, Android, WebAssembly and 32-bit systems.

All the details, including every difference from Microsoft.Data.Sqlite's
default SQLite: [dotnet/README.md](https://github.com/potluckdb/potluckdb/tree/main/dotnet).
