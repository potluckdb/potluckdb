// Code typed against @types/better-sqlite3 accepts potluckdb's Database.
import type BetterSqlite3 = require('better-sqlite3');
import Database = require('potluckdb');

function useDatabase(db: BetterSqlite3.Database): BetterSqlite3.Statement<[], unknown> {
	return db.prepare('select 1');
}
const Constructor: typeof BetterSqlite3 = Database;
const db = new Constructor(':memory:');
const stmt = useDatabase(new Database(':memory:'));
const options: BetterSqlite3.Options = { readonly: true };
const fromOptions = new Database('app.db', options);
export { db, stmt, fromOptions };
