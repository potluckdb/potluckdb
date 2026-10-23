# PotluckDB for .NET

Run Microsoft.Data.Sqlite, Dapper, EF Core and sqlite-net on PotluckDB's own
build of SQLite. Your code stays the same; only a package reference changes.

> **Status: pre-release.** It does not sync yet; that comes in later releases.

## Quickstart

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
| SQLitePCLRaw directly | `SQLitePCLRaw.bundle_e_sqlite3` | `PotluckDB.SQLitePCLRaw` | none (`Batteries_V2.Init()` as before) |

`sqlite-net-pcl` also works, with `PotluckDB.SQLitePCLRaw` and the same
`SQLitePCL.Batteries_V2.Init();` before sqlite-net is first used; the build
warns about it (POTLUCKDB002) until you add `POTLUCKDB002` to `<NoWarn>`.

Check that your app runs on PotluckDB: `SELECT potluckdb_version()` returns
the PotluckDB version (any other SQLite says "no such function").

The build stops with error POTLUCKDB001 if the project also gets another
SQLite bundle, for example by keeping `Microsoft.Data.Sqlite` next to
`PotluckDB.Data.Sqlite`: then the app might quietly run on that SQLite instead.
Remove the other package as the table says. (To build anyway, set the
property `PotluckDBCheckBundles` to `false`.)

Another SQLite in the same process, such as e_sqlite3 or the system's
SQLite used by another component, doesn't get in the way: each keeps to its
own library.

## Platforms

.NET 8 or later. The package has the native library for each platform;
nothing is compiled when you install it.

| Platform | Runtime identifier | Needs |
| --- | --- | --- |
| Linux x64, arm64 | `linux-x64`, `linux-arm64` | glibc 2.28 or later |
| Linux x64, arm64 (Alpine) | `linux-musl-x64`, `linux-musl-arm64` | musl |
| macOS Apple silicon, Intel | `osx-arm64`, `osx-x64` | macOS 11 or later |
| Windows x64 | `win-x64` | Windows 10 or later |
| Windows ARM64 | `win-arm64` | Windows 11 |

Self-contained and single-file apps work too. Not yet: .NET Framework, iOS,
Android, WebAssembly, 32-bit systems, and NativeAOT (untested).

## Differences from Microsoft.Data.Sqlite's default SQLite

`Microsoft.Data.Sqlite` comes with e_sqlite3, a SQLite built with its own
options; PotluckDB's library has its own. Foreign keys are on, as with
e_sqlite3 (`Foreign Keys=False` in the connection string turns them off).
What differs:

- `Password=` in the connection string has no effect: PotluckDB's library
  doesn't encrypt, and Microsoft.Data.Sqlite doesn't refuse it as it does for
  e_sqlite3.
- Double-quoted strings are allowed as string literals (`"text"`), as in
  SQLite's default build; e_sqlite3 rejects them.
- File names starting with `file:` are [URIs](https://sqlite.org/uri.html).
- `LIKE` matches BLOBs.
- FTS3 and FTS4 queries use SQLite's standard syntax, without `AND`, `NOT`
  and parentheses (FTS5 is the same in both).
- SQLite's snapshot functions (`sqlite3_snapshot_*`) are not available.

## Licence

The code here is Apache-2.0. The packages contain PotluckDB's native library,
which has its own licence; it contains SQLite, which is in the public domain.
Each package's `LICENSE.txt` has all three. The packages depend on SQLitePCLRaw
(Apache-2.0) and Microsoft.Data.Sqlite.Core (MIT).

## Developing

Needs the .NET 10 SDK and Python 3.9 or later; on Linux and macOS also a C
compiler. How it works and why: [DESIGN.md](DESIGN.md).

```sh
cd dotnet
export POTLUCKDB_CORE_DIR=/path/to/core-archives   # or leave it out to download the release
python3 scripts/native.py --target linux-x64-gnu   # the native library -> artifacts/native/<rid>/
python3 scripts/pack.py                            # the packages -> artifacts/packages/
python3 test/run.py                                # PotluckDB's tests and Microsoft.Data.Sqlite's own
python3 test/quickstart/run.py                     # the quickstart apps
```

The version is `PotluckDBVersion` in `Directory.Build.props` (or
`POTLUCKDB_VERSION`); the packages get the version of the PotluckDB release
they are made from. On Linux, build the native library in a manylinux_2_28
container (glibc) or on Alpine (musl), as `.github/workflows/dotnet.yml` does,
so that it runs on the oldest supported systems; `native.py` checks that.

`test/Microsoft.Data.Sqlite.Tests` is Microsoft.Data.Sqlite's own test suite,
copied unmodified from [efcore v10.0.12](https://github.com/dotnet/efcore/tree/v10.0.12/test/Microsoft.Data.Sqlite.Tests)
(MIT, see its `LICENSE.txt`); tests that may fail on PotluckDB are listed,
with the reason, in its `known-failures.json` (none so far).
