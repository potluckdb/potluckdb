type: fixed

Python on macOS: the `potluckdb` package's compiled module now exports only its init function. In 0.8.0-dev.3 it also exported `potluckdb_vfs_register`, which could clash with another copy of PotluckDB's library in the same program.
