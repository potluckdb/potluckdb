type: added

.NET: the NuGet package `PotluckDB.Data.Sqlite` runs Microsoft.Data.Sqlite on PotluckDB's SQLite. Use it in place of `Microsoft.Data.Sqlite` and your code, and Dapper or EF Core on top, keeps working, on .NET 8 and later, on Linux, macOS and Windows. For sqlite-net, add `PotluckDB.SQLitePCLRaw` and call `SQLitePCL.Batteries_V2.Init()` once at startup.
