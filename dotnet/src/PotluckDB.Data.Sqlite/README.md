# PotluckDB.Data.Sqlite

[Microsoft.Data.Sqlite](https://learn.microsoft.com/dotnet/standard/data/sqlite/)
on PotluckDB's build of SQLite. Use it in place of `Microsoft.Data.Sqlite`:
your code, and Dapper on top, keep working unchanged.

> **Pre-release.** It does not sync yet; that comes in later releases.

```xml
<PackageReference Include="PotluckDB.Data.Sqlite" Version="0.8.0-dev.1" />
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

For EF Core, use `Microsoft.EntityFrameworkCore.Sqlite.Core` (in place of
`Microsoft.EntityFrameworkCore.Sqlite`) with this package.

Platforms: Linux x64 and arm64 (glibc 2.28 or later, or musl), macOS 11 or
later (Apple silicon and Intel), Windows 10 or later (x64) and Windows 11 (ARM64);
.NET 8 or later.

More: https://github.com/potluckdb/potluckdb/tree/main/dotnet

Licence: this package only brings `Microsoft.Data.Sqlite.Core` and
`PotluckDB.SQLitePCLRaw`; the latter holds PotluckDB's native library, under
the PotluckDB binary licence. See `LICENSE.txt`.
