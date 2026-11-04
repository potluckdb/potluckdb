type: fixed

The library now exports every function that sqlite.org's own `sqlite3.dll` for the same SQLite version exports: 0.8.0-dev.3 lacked `sqlite3_carray_bind`, `sqlite3_carray_bind_v2` and the RBU extension's `sqlite3rbu_*` functions. SQL can now use the `carray()` table-valued function, and `PRAGMA compile_options` lists `ENABLE_CARRAY` and `ENABLE_RBU`.
