// potluckdb's types from an ES module (index.d.mts).
import Database, { SqliteError } from 'potluckdb';
import DatabaseLinux from 'potluckdb/linux-x64';

const db: Database.Database = new Database(':memory:');
const stmt: Database.Statement<[number]> = db.prepare('select ?');
const value: unknown = stmt.pluck().get(1);
const version: string = Database.coreVersion;
const error = new SqliteError('message', 'SQLITE_ERROR');
const sameClass: typeof Database.SqliteError = SqliteError;
const other: Database.Database = new DatabaseLinux(':memory:');
export { value, version, error, sameClass, other };
