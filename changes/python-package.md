type: added

Python: `pip install potluckdb` installs a drop-in replacement for the standard `sqlite3` module that runs on PotluckDB's SQLite. Change `import sqlite3` to `import potluckdb as sqlite3` and your code keeps working, on Python 3.10 to 3.14, on Linux, macOS and Windows.
