type: fixed

On macOS, modules and programs that link the static library (`lib/static/libsqlite3.a`) now export no PotluckDB-internal name; with 0.8.0-dev.3 they exported one. Linux and macOS builds now check that no name in the static library is visible outside the module that links it.
