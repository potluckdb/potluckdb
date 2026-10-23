// Type declarations for the ES module entry point (index.mjs): the same
// Database as require('potluckdb'), plus SqliteError as a named export.
import Database = require('./index.js');

export default Database;
export declare const SqliteError: Database.SqliteError;
