// PotluckDB's own checks of the .NET packages, one scenario per process (the
// order in which native libraries load matters, and only a new process starts
// afresh). test/run.py runs every scenario.
//
// Usage: dotnet run -- <scenario> <potluckdb version> <sqlite version>
//   api              Microsoft.Data.Sqlite runs on PotluckDB's SQLite, and its features work
//   freeze           once set up, SQLitePCLRaw stays on PotluckDB's SQLite
//   e_sqlite3-first  e_sqlite3 (SQLitePCLRaw's own SQLite) is used by another component
//   e_sqlite3-after    in the same process, before or after PotluckDB's
//   system-first     the system's SQLite (libsqlite3.so.0, /usr/lib/libsqlite3.dylib,
//   system-after       winsqlite3.dll) is used by another component, before or after
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
using Microsoft.Data.Sqlite;
using SQLitePCL;

internal static class Program
{
    private static string _potluckdbVersion = "";
    private static string _sqliteVersion = "";
    private static int _checks;

    private static int Main(string[] args)
    {
        if (args.Length != 3)
        {
            Console.Error.WriteLine("usage: PotluckDB.Tests <scenario> <potluckdb version> <sqlite version>");
            return 2;
        }

        (_potluckdbVersion, _sqliteVersion) = (args[1], args[2]);
        string scenario = args[0];
        Console.WriteLine($"{scenario} ({RuntimeInformation.RuntimeIdentifier}, .NET {Environment.Version})");
        switch (scenario)
        {
            case "api": Api(); break;
            case "freeze": Freeze(); break;
            case "e_sqlite3-first": Coexist(OpenESqlite3, potluckdbFirst: false); break;
            case "e_sqlite3-after": Coexist(OpenESqlite3, potluckdbFirst: true); break;
            case "system-first": Coexist(OpenSystemSqlite, potluckdbFirst: false); break;
            case "system-after": Coexist(OpenSystemSqlite, potluckdbFirst: true); break;
            default: Console.Error.WriteLine($"unknown scenario {scenario}"); return 2;
        }

        Console.WriteLine($"ok: {_checks} checks");
        return 0;
    }

    private static void Check(bool condition, string what)
    {
        _checks++;
        if (!condition)
        {
            throw new Exception($"check failed: {what}");
        }
    }

    private static void Equal<T>(T expected, T actual, string what)
        => Check(EqualityComparer<T>.Default.Equals(expected, actual), $"{what}: expected {expected}, got {actual}");

    private static object? Scalar(SqliteConnection connection, string sql, params (string Name, object? Value)[] parameters)
    {
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = sql;
        foreach ((string name, object? value) in parameters)
        {
            command.Parameters.AddWithValue(name, value ?? DBNull.Value);
        }

        return command.ExecuteScalar();
    }

    private static void Execute(SqliteConnection connection, string sql)
    {
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = sql;
        command.ExecuteNonQuery();
    }

    private static SqliteConnection Open(string connectionString = "Data Source=:memory:")
    {
        var connection = new SqliteConnection(connectionString);
        connection.Open();
        return connection;
    }

    // Microsoft.Data.Sqlite answers with PotluckDB's versions.
    private static void CheckPotluckDB()
    {
        using SqliteConnection connection = Open();
        Equal(_potluckdbVersion, Scalar(connection, "select potluckdb_version()"), "potluckdb_version()");
        Equal(_sqliteVersion, Scalar(connection, "select sqlite_version()"), "sqlite_version()");
        Equal(_sqliteVersion, connection.ServerVersion, "SqliteConnection.ServerVersion");
        Equal("potluckdb", raw.GetNativeLibraryName(), "raw.GetNativeLibraryName()");
        Console.WriteLine($"  Microsoft.Data.Sqlite: potluckdb_version() {_potluckdbVersion}, sqlite_version() {_sqliteVersion}");
    }

    private static void Api()
    {
        CheckPotluckDB();
        string dir = Path.Combine(Path.GetTempPath(), "potluckdb-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        try
        {
            using (SqliteConnection db = Open())
            {
                // Values of every type, through parameters.
                Execute(db, "create table t (i integer, r real, s text, b blob, n)");
                using (SqliteCommand insert = db.CreateCommand())
                {
                    insert.CommandText = "insert into t values ($i, $r, $s, $b, $n)";
                    insert.Parameters.AddWithValue("$i", long.MaxValue);
                    insert.Parameters.AddWithValue("$r", 0.5);
                    insert.Parameters.AddWithValue("$s", "Grüße, 世界");
                    insert.Parameters.AddWithValue("$b", new byte[] { 0, 1, 2, 255 });
                    insert.Parameters.AddWithValue("$n", DBNull.Value);
                    Equal(1, insert.ExecuteNonQuery(), "rows inserted");
                }

                using (SqliteCommand select = db.CreateCommand())
                {
                    select.CommandText = "select i, r, s, b, n, typeof(n) from t";
                    using SqliteDataReader reader = select.ExecuteReader();
                    Check(reader.Read(), "a row");
                    Equal(long.MaxValue, reader.GetInt64(0), "integer");
                    Equal(0.5, reader.GetDouble(1), "real");
                    Equal("Grüße, 世界", reader.GetString(2), "text");
                    Check(((byte[])reader[3]).SequenceEqual(new byte[] { 0, 1, 2, 255 }), "blob");
                    Check(reader.IsDBNull(4), "null");
                    Equal("null", reader.GetString(5), "typeof(null)");
                    Equal("t", reader.GetSchemaTable().Rows[0]["BaseTableName"], "column metadata");
                }

                // Transactions.
                using (SqliteTransaction transaction = db.BeginTransaction())
                {
                    Execute(db, "insert into t (i) values (2)");
                    transaction.Rollback();
                }

                Equal(1L, Scalar(db, "select count(*) from t"), "rows after rollback");

                // Functions, aggregates and collations written in C#: SQLite calls back into .NET.
                db.CreateFunction("twice", (long x) => 2 * x);
                Equal(42L, Scalar(db, "select twice(21)"), "scalar function");
                db.CreateAggregate("joined", "", (string acc, string s) => acc + s);
                Equal("abc", Scalar(db, "select joined(x) from (select 'a' x union all select 'b' union all select 'c')"), "aggregate");
                db.CreateCollation("reverse", (x, y) => string.CompareOrdinal(y, x));
                Equal("b", Scalar(db, "select x from (select 'a' x union all select 'b') order by x collate reverse limit 1"), "collation");

                // Blob I/O.
                Execute(db, "create table blobs (data blob); insert into blobs values (zeroblob(4))");
                using (var blob = new SqliteBlob(db, "blobs", "data", 1))
                {
                    blob.Write(new byte[] { 9, 8, 7, 6 }, 0, 4);
                }

                Check(((byte[])Scalar(db, "select data from blobs")!).SequenceEqual(new byte[] { 9, 8, 7, 6 }), "blob write");

                // Built in: JSON, FTS5, R*Tree, math functions.
                Equal(2L, Scalar(db, "select json_extract('{\"a\": [1, 2]}', '$.a[1]')"), "JSON");
                Execute(db, "create virtual table docs using fts5(body); insert into docs values ('local first sync')");
                Equal(1L, Scalar(db, "select count(*) from docs where docs match 'sync'"), "FTS5");
                Execute(db, "create virtual table boxes using rtree(id, x0, x1)");
                Equal(3.0, Scalar(db, "select sqrt(9)"), "math functions");

                // Errors.
                SqliteException error = Expect<SqliteException>(() => Execute(db, "select from"));
                Equal(1, error.SqliteErrorCode, "SQLITE_ERROR");

                // Backup.
                using SqliteConnection copy = Open();
                db.BackupDatabase(copy);
                Equal(1L, Scalar(copy, "select count(*) from t"), "rows in the backup");

                // Foreign keys: on, as with e_sqlite3, unless the connection string says otherwise.
                Equal(1L, Scalar(db, "pragma foreign_keys"), "foreign keys by default");
                Execute(db, "create table parent (id integer primary key); create table child (p references parent (id))");
                Equal(19, Expect<SqliteException>(() => Execute(db, "insert into child values (1)")).SqliteErrorCode, "SQLITE_CONSTRAINT");
            }

            using (SqliteConnection fk = Open("Data Source=:memory:;Foreign Keys=False"))
            {
                Equal(0L, Scalar(fk, "pragma foreign_keys"), "Foreign Keys=False");
            }

            // A file in WAL mode, written from several threads, each with its own connection.
            string file = Path.Combine(dir, "app.db");
            using (SqliteConnection db = Open($"Data Source={file}"))
            {
                Equal("wal", Scalar(db, "pragma journal_mode = wal"), "WAL mode");
                Execute(db, "create table log (thread integer, n integer)");
            }

            Parallel.For(0, 4, thread =>
            {
                using SqliteConnection db = Open($"Data Source={file};Default Timeout=30");
                for (int n = 0; n < 50; n++)
                {
                    Scalar(db, "insert into log values ($t, $n)", ("$t", thread), ("$n", n));
                }
            });
            using (SqliteConnection db = Open($"Data Source={file};Mode=ReadOnly"))
            {
                Equal(200L, Scalar(db, "select count(*) from log"), "rows from 4 threads");
            }
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            Directory.Delete(dir, recursive: true);
        }
    }

    private static T Expect<T>(Action action) where T : Exception
    {
        try
        {
            action();
        }
        catch (T e)
        {
            _checks++;
            return e;
        }

        throw new Exception($"check failed: expected {typeof(T).Name}");
    }

    private static void Freeze()
    {
        CheckPotluckDB();
        // sqlite-net-pcl, for example, does this when first used.
        raw.SetProvider(new SQLite3Provider_e_sqlite3());
        Batteries_V2.Init();
        CheckPotluckDB();
    }

    // Runs queries on PotluckDB's SQLite and on another one, interleaved, with
    // the other one loaded first or last.
    private static void Coexist(Func<OtherSqlite> openOther, bool potluckdbFirst)
    {
        if (potluckdbFirst)
        {
            CheckPotluckDB();
        }

        OtherSqlite other = openOther();
        other.Check();
        CheckPotluckDB();
        other.Check();
        CheckNotPotluckDB(other);
        using SqliteConnection db = Open();
        Execute(db, "create table t (x)");
        other.Query("create table t (x)");
        for (int i = 0; i < 100; i++)
        {
            Execute(db, $"insert into t values ({i})");
            other.Query($"insert into t values ({i})");
        }

        Equal(4950L, Scalar(db, "select sum(x) from t"), "sum in PotluckDB's database");
        Equal("4950", other.Query("select sum(x) from t"), $"sum in {other.Name}'s database");
        CheckPotluckDB();
        other.Close();
    }

    // The other library is not ours: loading it by its name didn't return
    // PotluckDB's library (as it would if ours had SQLite's own file name or
    // SONAME), and it knows nothing of PotluckDB.
    private static void CheckNotPotluckDB(OtherSqlite other)
    {
        IntPtr ours = System.Runtime.InteropServices.NativeLibrary.Load("potluckdb_dotnet", typeof(Batteries_V2).Assembly, null);
        Check(ours != other.Handle, $"{other.Name} is a different library than PotluckDB's");
        Check(!System.Runtime.InteropServices.NativeLibrary.TryGetExport(other.Handle, "potluckdb_version", out _), $"{other.Name} has no potluckdb_version()");
        Check(other.Query("select potluckdb_version()").StartsWith("error: no such function"), $"{other.Name} runs no PotluckDB code");
    }

    private static OtherSqlite OpenESqlite3()
        => new OtherSqlite("e_sqlite3", System.Runtime.InteropServices.NativeLibrary.Load("e_sqlite3", typeof(Program).Assembly, null));

    private static OtherSqlite OpenSystemSqlite()
    {
        string name = OperatingSystem.IsWindows() ? "winsqlite3.dll" : OperatingSystem.IsMacOS() ? "/usr/lib/libsqlite3.dylib" : "libsqlite3.so.0";
        if (!System.Runtime.InteropServices.NativeLibrary.TryLoad(name, out IntPtr handle))
        {
            throw new Exception($"the system's SQLite ({name}) is not installed; install it to run this scenario (Alpine: apk add sqlite-libs)");
        }

        return new OtherSqlite($"the system's SQLite ({name})", handle);
    }
}

// Another component's own use of a SQLite library, through its C API.
internal sealed unsafe class OtherSqlite
{
    private readonly delegate* unmanaged[Cdecl]<byte*> _libversion;
    private readonly delegate* unmanaged[Cdecl]<IntPtr, byte*, int, IntPtr*, IntPtr, int> _prepare;
    private readonly delegate* unmanaged[Cdecl]<IntPtr, int> _step;
    private readonly delegate* unmanaged[Cdecl]<IntPtr, int, byte*> _columnText;
    private readonly delegate* unmanaged[Cdecl]<IntPtr, int> _finalize;
    private readonly delegate* unmanaged[Cdecl]<IntPtr, byte*> _errmsg;
    private readonly delegate* unmanaged[Cdecl]<IntPtr, int> _close;
    private readonly IntPtr _db;

    internal OtherSqlite(string name, IntPtr handle)
    {
        Name = name;
        Handle = handle;
        _libversion = (delegate* unmanaged[Cdecl]<byte*>)Export("sqlite3_libversion");
        _prepare = (delegate* unmanaged[Cdecl]<IntPtr, byte*, int, IntPtr*, IntPtr, int>)Export("sqlite3_prepare_v2");
        _step = (delegate* unmanaged[Cdecl]<IntPtr, int>)Export("sqlite3_step");
        _columnText = (delegate* unmanaged[Cdecl]<IntPtr, int, byte*>)Export("sqlite3_column_text");
        _finalize = (delegate* unmanaged[Cdecl]<IntPtr, int>)Export("sqlite3_finalize");
        _errmsg = (delegate* unmanaged[Cdecl]<IntPtr, byte*>)Export("sqlite3_errmsg");
        _close = (delegate* unmanaged[Cdecl]<IntPtr, int>)Export("sqlite3_close");
        var open = (delegate* unmanaged[Cdecl]<byte*, IntPtr*, int>)Export("sqlite3_open");
        IntPtr db;
        fixed (byte* path = Encoding.UTF8.GetBytes(":memory:\0"))
        {
            if (open(path, &db) != 0)
            {
                throw new Exception($"{name}: sqlite3_open failed");
            }
        }

        _db = db;
        Version = Marshal.PtrToStringUTF8((IntPtr)_libversion())!;
    }

    internal string Name { get; }

    internal IntPtr Handle { get; }

    internal string Version { get; }

    private IntPtr Export(string symbol) => System.Runtime.InteropServices.NativeLibrary.GetExport(Handle, symbol);

    // The first column of the first row, or "error: <message>".
    internal string Query(string sql)
    {
        IntPtr stmt;
        fixed (byte* text = Encoding.UTF8.GetBytes(sql + "\0"))
        {
            if (_prepare(_db, text, -1, &stmt, IntPtr.Zero) != 0)
            {
                return "error: " + Marshal.PtrToStringUTF8((IntPtr)_errmsg(_db));
            }
        }

        try
        {
            int rc = _step(stmt);
            return rc == 100 ? Marshal.PtrToStringUTF8((IntPtr)_columnText(stmt, 0)) ?? "" : rc == 101 ? "" : "error: " + Marshal.PtrToStringUTF8((IntPtr)_errmsg(_db));
        }
        finally
        {
            _finalize(stmt);
        }
    }

    internal void Check()
    {
        if (Query("select sqlite_version()") != Version || Version == "")
        {
            throw new Exception($"check failed: {Name} answers sqlite_version() {Query("select sqlite_version()")}, but sqlite3_libversion() {Version}");
        }

        Console.WriteLine($"  {Name}: sqlite_version() {Version}");
    }

    internal void Close() => _close(_db);
}
