# PotluckDB.SQLitePCLRaw

PotluckDB's build of SQLite for [SQLitePCLRaw](https://github.com/ericsink/SQLitePCL.raw),
the native layer under Microsoft.Data.Sqlite, EF Core and sqlite-net. It takes
the place of `SQLitePCLRaw.bundle_e_sqlite3`.

> **Pre-release.** It does not sync yet; that comes in later releases.

- **Microsoft.Data.Sqlite or Dapper:** use the package `PotluckDB.Data.Sqlite`
  in place of `Microsoft.Data.Sqlite`. No code changes.
- **EF Core:** use `Microsoft.EntityFrameworkCore.Sqlite.Core` (in place of
  `Microsoft.EntityFrameworkCore.Sqlite`) and `PotluckDB.Data.Sqlite`. No code changes.
- **sqlite-net:** use `sqlite-net-base` (in place of `sqlite-net-pcl`) and this
  package, and call `SQLitePCL.Batteries_V2.Init();` once at startup.

Check that your app runs on PotluckDB: `SELECT potluckdb_version()` returns
the PotluckDB version.

Platforms: Linux x64 and arm64 (glibc 2.28 or later, or musl), macOS 11 or
later (Apple silicon and Intel), Windows 10 or later (x64) and Windows 11 (ARM64);
.NET 8 or later.

More: https://github.com/potluckdb/potluckdb/tree/main/dotnet

Licence: the managed code is Apache-2.0; the native library is under the
PotluckDB binary licence and contains SQLite (public domain). See `LICENSE.txt`.
