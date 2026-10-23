using System;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using SQLitePCL;

namespace PotluckDB.Interop
{
    /// <summary>
    /// Loads PotluckDB's native library and hands its SQLite API to
    /// SQLitePCLRaw's dynamic provider (SQLitePCLRaw.provider.dynamic_cdecl).
    /// </summary>
    /// <remarks>
    /// The library is <c>potluckdb_dotnet</c> (libpotluckdb_dotnet.so,
    /// libpotluckdb_dotnet.dylib, potluckdb_dotnet.dll) from this package's
    /// runtimes/&lt;rid&gt;/native folder. On Linux and macOS it exports one
    /// function, <c>potluckdb_dotnet_symbol</c>, that returns the address of an
    /// API function by name; on Windows it exports the API itself. See DESIGN.md.
    /// </remarks>
    internal static unsafe class NativeLibrary
    {
        internal const string Name = "potluckdb_dotnet";

        /// <summary>The name SQLitePCLRaw reports for this library (raw.GetNativeLibraryName()).</summary>
        internal const string ProviderName = "potluckdb";

        private const string Platforms = "linux-x64, linux-arm64, linux-musl-x64, linux-musl-arm64, osx-arm64, osx-x64, win-x64 and win-arm64";

        private static readonly object Gate = new object();
        private static readonly byte[] ForeignKeysOn = Encoding.UTF8.GetBytes("PRAGMA foreign_keys = ON\0");
        private static bool _loaded;
        private static delegate* unmanaged[Cdecl]<IntPtr, byte*, IntPtr, IntPtr, IntPtr, int> _exec;

        internal static void SetProvider()
        {
            lock (Gate)
            {
                if (!_loaded)
                {
                    IGetFunctionPointer api = Load();
                    SQLite3Provider_dynamic_cdecl.Setup(ProviderName, api);
                    EnableForeignKeysByDefault(api);
                    _loaded = true;
                }

                raw.SetProvider(new SQLite3Provider_dynamic_cdecl());
                raw.FreezeProvider();
                string name = raw.GetNativeLibraryName();
                if (name != ProviderName)
                {
                    throw new InvalidOperationException(
                        $"PotluckDB can't set up SQLitePCLRaw: another component already fixed it to the SQLite library '{name}' (with raw.FreezeProvider). Remove that component, or make sure SQLitePCL.Batteries_V2.Init() runs first.");
                }
            }
        }

        private static IGetFunctionPointer Load()
        {
            IntPtr handle;
            try
            {
                handle = System.Runtime.InteropServices.NativeLibrary.Load(Name, typeof(NativeLibrary).Assembly, null);
            }
            catch (DllNotFoundException e)
            {
                throw new DllNotFoundException(
                    $"PotluckDB's SQLite library ({Name}) wasn't found for this platform ({RuntimeInformation.RuntimeIdentifier}). The PotluckDB.SQLitePCLRaw package has it for {Platforms}. {e.Message}",
                    e);
            }

            IGetFunctionPointer api = System.Runtime.InteropServices.NativeLibrary.TryGetExport(handle, "potluckdb_dotnet_symbol", out IntPtr lookup)
                ? new SymbolTable((delegate* unmanaged[Cdecl]<byte*, IntPtr>)lookup)
                : new Exports(handle);
            if (api.GetFunctionPointer("potluckdb_version") == IntPtr.Zero)
            {
                throw new DllNotFoundException($"The library loaded as {Name} is not PotluckDB's: it has no potluckdb_version().");
            }

            return api;
        }

        // e_sqlite3, the SQLite that Microsoft.Data.Sqlite and sqlite-net come
        // with, is built with foreign keys on, and apps (EF Core's among them)
        // count on it. PotluckDB's library keeps SQLite's default, off, so each
        // new connection turns them on. "Foreign Keys=False" in a connection
        // string still turns them off, as with e_sqlite3.
        private static void EnableForeignKeysByDefault(IGetFunctionPointer api)
        {
            _exec = (delegate* unmanaged[Cdecl]<IntPtr, byte*, IntPtr, IntPtr, IntPtr, int>)api.GetFunctionPointer("sqlite3_exec");
            var autoExtension = (delegate* unmanaged[Cdecl]<IntPtr, int>)api.GetFunctionPointer("sqlite3_auto_extension");
            delegate* unmanaged[Cdecl]<IntPtr, IntPtr, IntPtr, int> onOpen = &OnOpen;
            int rc = autoExtension((IntPtr)onOpen);
            if (rc != 0)
            {
                throw new InvalidOperationException($"PotluckDB: sqlite3_auto_extension failed with error {rc}.");
            }
        }

        // Runs for every new connection, inside sqlite3_open (an SQLite auto-extension).
        [UnmanagedCallersOnly(CallConvs = new[] { typeof(CallConvCdecl) })]
        private static int OnOpen(IntPtr db, IntPtr errorMessage, IntPtr api)
        {
            fixed (byte* sql = ForeignKeysOn)
            {
                _exec(db, sql, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
            }

            return 0;
        }

        /// <summary>The API of the Linux and macOS library, through its lookup function.</summary>
        private sealed class SymbolTable : IGetFunctionPointer
        {
            private readonly delegate* unmanaged[Cdecl]<byte*, IntPtr> _lookup;

            internal SymbolTable(delegate* unmanaged[Cdecl]<byte*, IntPtr> lookup) => _lookup = lookup;

            public IntPtr GetFunctionPointer(string name)
            {
                byte[] utf8 = Encoding.UTF8.GetBytes(name + "\0");
                fixed (byte* p = utf8)
                {
                    return _lookup(p);
                }
            }
        }

        /// <summary>The API of the Windows library, which exports it.</summary>
        private sealed class Exports : IGetFunctionPointer
        {
            private readonly IntPtr _handle;

            internal Exports(IntPtr handle) => _handle = handle;

            public IntPtr GetFunctionPointer(string name)
                => System.Runtime.InteropServices.NativeLibrary.TryGetExport(_handle, name, out IntPtr address) ? address : IntPtr.Zero;
        }
    }
}
