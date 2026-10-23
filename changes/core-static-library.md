type: added

A static build of the same library in lib/static (libsqlite3.a, or sqlite3.lib on Windows), for programs that link SQLite into themselves. Its symbols stay private to the program, so it never clashes with another SQLite loaded in the same process.
