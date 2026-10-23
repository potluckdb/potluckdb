// ES module entry point: the same Database as require('potluckdb').
import Database from './lib/index.js';

export const SqliteError = Database.SqliteError;
export default Database;
