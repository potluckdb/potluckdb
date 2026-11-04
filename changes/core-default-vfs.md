type: fixed

The default VFS is SQLite's own again: `sqlite3_vfs_find(NULL)` returns "unix" on Linux and macOS and "win32" on Windows, as with sqlite.org's SQLite, and the list of registered VFSes holds only SQLite's own. In 0.8.0-dev.3 the default was named "potluckdb", with an extra "potluckdb" entry in the list.
