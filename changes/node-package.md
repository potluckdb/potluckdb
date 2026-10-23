type: added

Node.js: `npm install potluckdb` installs a drop-in replacement for better-sqlite3 that runs on PotluckDB's SQLite. Change `require('better-sqlite3')` to `require('potluckdb')` and your code keeps working, on Node.js 20 and later, on Linux, macOS and Windows.
