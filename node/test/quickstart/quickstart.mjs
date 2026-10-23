// The README's quickstart as an ES module, run where potluckdb was installed with npm.
import assert from 'assert';
import { createRequire } from 'module';
import Database, { SqliteError } from 'potluckdb';

const db = new Database('app.db');
const row = db.prepare('select potluckdb_version() as p, sqlite_version() as s').get();

console.log(row);
assert.strictEqual(row.p, Database.coreVersion);
assert.strictEqual(SqliteError, Database.SqliteError);
// The same Database as require('potluckdb'), not a second copy.
assert.strictEqual(createRequire(import.meta.url)('potluckdb'), Database);
assert.throws(() => db.exec('not sql'), SqliteError);
db.close();
