type: changed

SQLite's math functions (sin, exp, pow, ln and the others) now return exactly the same result, to the last bit, on every platform: the library builds in its own copy of musl's math code instead of using the system's. A result can differ in the last digit from another SQLite on the same machine.
