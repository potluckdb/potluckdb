namespace SQLitePCL
{
    /// <summary>
    /// Sets up SQLitePCLRaw to use PotluckDB's build of SQLite.
    /// </summary>
    /// <remarks>
    /// This assembly takes the place of the one in SQLitePCLRaw's own bundles
    /// (such as SQLitePCLRaw.bundle_e_sqlite3), with the same name and API.
    /// Microsoft.Data.Sqlite.Core calls <see cref="Init"/> by itself, before it
    /// opens the first connection, so apps using it need no code. Libraries that
    /// expect the app to set up SQLitePCLRaw, such as sqlite-net, need one call
    /// at startup.
    /// </remarks>
    public static class Batteries_V2
    {
        /// <summary>
        /// Makes PotluckDB's SQLite the one SQLitePCLRaw uses in this process and
        /// keeps it so: later calls to <c>raw.SetProvider</c>, for example by
        /// sqlite-net-pcl, are ignored. Safe to call more than once and from any
        /// thread.
        /// </summary>
        /// <exception cref="System.DllNotFoundException">PotluckDB has no native
        /// library for this platform.</exception>
        /// <exception cref="System.InvalidOperationException">Another component
        /// already fixed SQLitePCLRaw to a different SQLite.</exception>
        public static void Init() => PotluckDB.Interop.NativeLibrary.SetProvider();
    }

    /// <summary>The same as <see cref="Batteries_V2"/>, under its older name.</summary>
    public static class Batteries
    {
        /// <inheritdoc cref="Batteries_V2.Init"/>
        public static void Init() => Batteries_V2.Init();
    }
}
