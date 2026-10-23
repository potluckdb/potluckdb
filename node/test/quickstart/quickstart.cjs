'use strict';
// The README's quickstart, run where potluckdb was installed with npm.
const assert = require('assert');

const Database = require('potluckdb');   // was: require('better-sqlite3')
const db = new Database('app.db');
const row = db.prepare('select potluckdb_version() as p, sqlite_version() as s').get();

console.log(row);
assert.deepStrictEqual(Object.keys(row), ['p', 's']);
assert.strictEqual(row.p, Database.coreVersion);
assert.match(row.p, /^\d+\.\d+\.\d+/);
assert.match(row.s, /^3\.\d+\.\d+$/);
assert.ok(new Database.SqliteError('x', 'SQLITE_ERROR') instanceof Error);
db.close();
