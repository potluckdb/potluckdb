# PotluckDB for Node.js

`potluckdb` is a drop-in replacement for
[better-sqlite3](https://github.com/WiseLibs/better-sqlite3) that runs on
PotluckDB's own build of SQLite. Your code stays the same; only the `require`
changes.

> **Status: pre-release.** It does not sync yet; that comes in later releases.

## Quickstart

```sh
npm install potluckdb
```

```js
const Database = require('potluckdb');   // was: require('better-sqlite3')
const db = new Database('app.db');
db.prepare('select potluckdb_version() as p, sqlite_version() as s').get(); // { p: '0.8.0-dev.1', s: '3.54.1' }
```

ES modules work too (`import Database from 'potluckdb'`), and TypeScript types
are included. They match `@types/better-sqlite3`, so code typed against
better-sqlite3 compiles unchanged.

## API

The same as better-sqlite3 13: see its
[API documentation](https://github.com/WiseLibs/better-sqlite3/blob/v13.0.3/docs/api.md).
PotluckDB adds one property:

- `Database.coreVersion`: the PotluckDB build in use, for example `'0.8.0-dev.1'`
  (the same as `select potluckdb_version()`).

## Platforms

Node.js 20 or later. `npm install` picks a ready-made binary for your platform;
nothing is compiled.

| Platform | Package | Needs |
| --- | --- | --- |
| Linux x64, arm64 | `@potluckdb/linux-x64-gnu`, `@potluckdb/linux-arm64-gnu` | glibc 2.28 or later |
| Linux x64, arm64 (Alpine) | `@potluckdb/linux-x64-musl`, `@potluckdb/linux-arm64-musl` | musl |
| macOS Apple silicon, Intel | `@potluckdb/macos-arm64`, `@potluckdb/macos-x64` | macOS 11 or later |
| Windows x64 | `@potluckdb/windows-x64` | Windows 10 or later |
| Windows ARM64 | `@potluckdb/windows-arm64` | Windows 11 |

If you install with optional dependencies turned off (`--omit=optional`), the
platform package is missing and `potluckdb` says so when it loads.

## Differences from better-sqlite3

better-sqlite3 compiles SQLite with its own build options; PotluckDB's library
has its own. Foreign keys are on and double-quoted string literals are off, as in
better-sqlite3. What differs:

- `DELETE ... LIMIT` and `UPDATE ... LIMIT` are not available.
- The page cache is SQLite's default, 2 MB, not 16 MB. For 16 MB:
  `db.pragma('cache_size = -16000')`.
- In WAL mode, `synchronous` stays `FULL` (better-sqlite3: `NORMAL`). For
  better-sqlite3's behaviour: `db.pragma('synchronous = NORMAL')`.
- File names starting with `file:` are [URIs](https://sqlite.org/uri.html).
- The `verbose` logger receives bound values in full, not cut at 32 bytes.
- `LIKE` matches BLOBs, and `soundex()` is not available.

## Licence

Apache-2.0. Parts come from better-sqlite3 and @types/better-sqlite3 (both MIT);
see `THIRD_PARTY_NOTICES.md`. The platform packages contain the PotluckDB
library, which has its own licence (`LICENSE.txt` in each).

## Developing

```sh
cd node
npm ci
POTLUCKDB_CORE_DIR=/path/to/core-archives npm run build   # or omit it to download the release for package.json's version
npm test
```

`npm run build` builds `build/Release/potluckdb.node` against a PotluckDB core
archive and copies it to `prebuilds/<platform>/`; `node scripts/package.js`
makes the npm packages from there. `npm test` runs better-sqlite3's own test
suite (with the failures listed in `test/known-failures.json`) and the tests in
`test/`.
