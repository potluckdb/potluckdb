type: added

The Windows archives also hold a MinGW static library, `lib/static/libsqlite3.a`, built with llvm-mingw from the same sources and options, which Go's cgo can link (the MSVC library `lib/static/sqlite3.lib` stays for everything else).
