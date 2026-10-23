# Design of PotluckDB's .NET packages

Goal: a .NET app that uses SQLite through Microsoft.Data.Sqlite (and Dapper,
EF Core or sqlite-net on top) moves to PotluckDB's build of SQLite by changing
one package reference, with at most one call at startup.

## How .NET reaches SQLite

```
Microsoft.Data.Sqlite / EF Core / sqlite-net
        |  calls SQLitePCL.raw (package SQLitePCLRaw.core)
        v
   a "provider": the class that calls into a native SQLite library
        |
        v
   the native library, from the package's runtimes/<rid>/native/ folder
```

SQLitePCLRaw ships "bundles". Each one holds an assembly named
`SQLitePCLRaw.batteries_v2` whose `SQLitePCL.Batteries_V2.Init()` picks the
provider and its native library. `Microsoft.Data.Sqlite` is
`Microsoft.Data.Sqlite.Core` plus the bundle for e_sqlite3, and
Microsoft.Data.Sqlite.Core calls `Batteries_V2.Init()` by name, by itself,
before the first connection. Other bundles use the same name; SQLite3 Multiple
Ciphers' `SQLite3MC.PCLRaw.bundle` is a third-party one.

## The packages

- **PotluckDB.SQLitePCLRaw**: PotluckDB's bundle. It holds
  `SQLitePCLRaw.batteries_v2.dll` (our code) and the native library for 8
  platforms, and depends on SQLitePCLRaw.core and
  SQLitePCLRaw.provider.dynamic_cdecl.
- **PotluckDB.Data.Sqlite**: no code; it brings Microsoft.Data.Sqlite.Core and
  PotluckDB.SQLitePCLRaw. It replaces `Microsoft.Data.Sqlite` one for one,
  as `Microsoft.Data.Sqlite` itself is Microsoft.Data.Sqlite.Core plus a bundle.

So Microsoft.Data.Sqlite, Dapper and EF Core apps change a package reference
and nothing else: Microsoft.Data.Sqlite.Core finds our `Batteries_V2` and calls
it. sqlite-net expects the app to set up SQLitePCLRaw, so it needs the one call
`SQLitePCL.Batteries_V2.Init()` at startup.

## The native library: a small library of our own (Linux, macOS), the core's DLL renamed (Windows)

The file is `libpotluckdb_dotnet.so`, `libpotluckdb_dotnet.dylib` or
`potluckdb_dotnet.dll`: a name no other SQLite uses, unlike `e_sqlite3`,
`sqlite3` or `libsqlite3`.

**Linux and macOS: a small native library, built from the core's static
library.** `native/potluckdb_dotnet.c` links in `lib/static/libsqlite3.a`,
whose symbols are hidden, and exports one function,
`potluckdb_dotnet_symbol(name)`, which returns the address of an API function
by name (the list of names comes from what the core's shared library exports,
so new PotluckDB functions appear by themselves). Its SONAME (install name on
macOS) is its own file name. Renaming the core's shared library instead isn't
enough, as tried on AlmaLinux 8 with its system SQLite 3.26:

- Renamed only: the library keeps its SONAME `libsqlite3.so.0`, and glibc
  matches already-loaded libraries by SONAME. A later
  `dlopen("libsqlite3.so.0")` by any other component got PotluckDB's library
  instead of the system's.
- Renamed and the SONAME patched (patchelf): that is fixed, but the library
  still reaches about 200 of its own functions and variables through the
  symbol table (x64 and arm64 alike). With another libsqlite3 in the process's
  global symbol scope (preloaded, linked into the host program, or loaded with
  RTLD_GLOBAL), those went to the other SQLite: PotluckDB's
  `sqlite3_libversion()` answered the system's 3.26.0, and the first
  `sqlite3_open` crashed (segmentation fault).
- The small library: both cases work. Ours keeps answering
  `potluckdb_version()`, and the system's SQLite keeps its own version and
  doesn't know `potluckdb_version()`. Its calls to SQLite are fixed when it is
  linked, and it exports nothing that could take the place of another
  SQLite's functions.

On macOS, the core's dylib has the install name `@rpath/libsqlite3.0.dylib`,
which dyld can share with another library of that name; changing it means
editing and re-signing the binary. The small library avoids both.

**Windows: the core's `bin/sqlite3.dll`, renamed.** Windows binds each import
to a named DLL and identifies loaded DLLs by file name, so a renamed DLL can't
be confused with another `sqlite3.dll`, `e_sqlite3.dll` or `winsqlite3.dll`.
It is the release's file byte for byte, needs only kernel32, and no compiler.

`scripts/native.py` builds or copies the library and checks it: what it
exports, its SONAME or install name, what it needs (only the C library,
libSystem or kernel32), the oldest system it runs on (glibc 2.28, macOS 11)
and its CPU. Linux builds run in manylinux_2_28 (glibc) and Alpine 3.22 (musl).

## The provider: SQLitePCLRaw's own dynamic provider

`Batteries_V2.Init()` loads `potluckdb_dotnet` with `NativeLibrary.Load`
(which finds the file through the app's dependency list, also in
self-contained and single-file apps), and gives SQLitePCLRaw's
`SQLite3Provider_dynamic_cdecl` a function that returns each API function's
address: through `potluckdb_dotnet_symbol` on Linux and macOS, through the
DLL's exports on Windows.

- No provider code of our own: SQLitePCLRaw's provider has about 150 methods
  that must match the SQLitePCLRaw.core the app ends up with; its own package
  always does.
- Cost: the dynamic provider calls through delegates. A quick benchmark
  (Windows x64, Microsoft.Data.Sqlite, reading 2 million rows) took about 10%
  longer than with e_sqlite3's own provider; e_sqlite3 through the same dynamic
  provider took just as long as PotluckDB's library, so the library itself
  costs nothing extra. Inserts were within 5%. If that matters later, a
  provider of our own (calls through function pointers) can replace it without
  apps changing anything.
- Functions that PotluckDB's build doesn't have (`sqlite3_snapshot_*`, and the
  encryption functions that e_sqlite3 lacks too) throw when called.

`Init()` also:

- **keeps SQLitePCLRaw on PotluckDB** (`raw.FreezeProvider()`): sqlite-net-pcl,
  for example, sets e_sqlite3 when first used; frozen, that does nothing, so
  sqlite-net-pcl runs on PotluckDB if `Init()` comes first. If another
  component froze SQLitePCLRaw on a different library first, `Init()` throws
  instead of running on that library.
- **turns foreign keys on for every connection** (an SQLite auto-extension
  running `PRAGMA foreign_keys = ON`), as e_sqlite3 is built with them on and
  apps, EF Core's among them, count on that. `Foreign Keys=False` in the
  connection string still turns them off. Other build options differ from
  e_sqlite3 and are listed in the README; none of them makes SQL that works on
  e_sqlite3 fail.

## Build checks

`PotluckDB.SQLitePCLRaw.targets` (in the package's `buildTransitive/`, so it
reaches the app also through PotluckDB.Data.Sqlite) checks the resolved
packages after restore:

- **POTLUCKDB001 (error):** another package also brings
  `SQLitePCLRaw.batteries_v2.dll`, typically `SQLitePCLRaw.bundle_e_sqlite3`
  through `Microsoft.Data.Sqlite`. The build would keep only one of the two
  assemblies, possibly not ours, and the app would quietly run on e_sqlite3.
- **POTLUCKDB002 (warning):** sqlite-net-pcl is referenced; it runs on PotluckDB
  only if `Batteries_V2.Init()` comes first.

## Versions

- The packages have the version of the PotluckDB release they are made from
  (0.8.0-dev.1 and so on); the native libraries' BUILD-INFO.json must match.
- SQLitePCLRaw 3.0.5: Microsoft.Data.Sqlite 11 and sqlite-net 1.11 use 3.0.x;
  Microsoft.Data.Sqlite 10 asks for 2.1.12 or later. The public API of 2.1.12
  and 3.0.5 is the same (compared member by member), and Microsoft.Data.Sqlite
  10.0.12's own test suite passes on 3.0.5.
- Microsoft.Data.Sqlite.Core 10.0.12 (in PotluckDB.Data.Sqlite), the newest at
  least two weeks old; .NET 8 and later (`lib/net8.0`).

## Licences

The packages name a licence file (`LICENSE.txt`), not a licence expression,
because they hold code under two licences. `scripts/pack.py` writes it from the
core archive: which part is under which licence, then the PotluckDB binary
licence (native library), SQLite's public-domain notice, and the Apache
License 2.0 (our code). SQLitePCLRaw (Apache-2.0) and Microsoft.Data.Sqlite.Core
(MIT) are dependencies, not included.

## Build, test and release

- `scripts/core.py`: finds the core archive in `POTLUCKDB_CORE_DIR`, or
  downloads it from the GitHub release `v<version>` of potluckdb/potluckdb;
  checks it against `SHA256SUMS`.
- `scripts/native.py`: makes and checks the native library for one platform.
- `scripts/pack.py`: makes both packages from the native libraries there are
  (`--all` requires all 8, for publishing).
- `test/run.py`: PotluckDB's checks (`test/PotluckDB.Tests`, one scenario per
  process: versions, features, the provider staying frozen, and e_sqlite3 or
  the system's SQLite used in the same process, loaded before or after ours;
  on Linux also with the system's SQLite preloaded), then Microsoft.Data.Sqlite's
  own test suite (efcore v10.0.12, unmodified, built with the name and public
  key that give it Microsoft.Data.Sqlite's internals, as in efcore).
- `test/quickstart/run.py`: small apps installed from the packages, as a user
  would: Microsoft.Data.Sqlite on .NET 10 and 8, self-contained and single
  file; Dapper; EF Core; sqlite-net-base; sqlite-net-pcl; and a project that
  must fail with POTLUCKDB001.
- `.github/workflows/dotnet.yml`: on pull requests Linux x64 only; nightly,
  by hand or from the release workflow all 8 platforms: the native library
  per platform, then on each platform the packages (with every library built)
  and all the tests, and on Linux the quickstart on AlmaLinux 8 (glibc 2.28).
  With `publish`, it pushes both packages to nuget.org with trusted publishing
  (NuGet/login, environment `nuget`). Before the first release it only
  compiles the managed code and leaves a notice.

## Not done yet

.NET Framework, Mono and Unity; iOS, Android and WebAssembly; 32-bit
platforms; NativeAOT (the dynamic provider uses delegates, which NativeAOT
warns about; untested); encryption. Sync comes in later releases.
