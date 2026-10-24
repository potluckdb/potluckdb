---
title: Node.js
description: Use PotluckDB from Node.js, in place of better-sqlite3.
---

`potluckdb` for Node.js is a drop-in replacement for
[better-sqlite3](https://github.com/WiseLibs/better-sqlite3) that runs on
PotluckDB's build of SQLite, on Node.js 20 and later, on Linux (glibc 2.28+
and musl), macOS 11+ and Windows, x64 and ARM64.

```js
const Database = require('potluckdb');   // was: require('better-sqlite3')
const db = new Database('app.db');
db.prepare('select potluckdb_version() as p, sqlite_version() as s').get();
// { p: '0.8.0-dev.1', s: '3.54.1' }
```

It is built and tested on every platform, and arrives on npm in a coming
pre-release. better-sqlite3's own test suite passes against it, apart from a
few cases listed in the package's README.

## Good to know

- Databases sync too: `potluckdb attach app.db s3://my-bucket/app` once,
  with no code change ([Sync a database](/guides/sync-a-database/)). One
  device writes at a time for now.
- One prebuilt binary per platform works on every Node.js version from 20 on
  (it uses Node-API), with no compiling at install time.
