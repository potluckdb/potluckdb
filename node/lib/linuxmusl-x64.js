'use strict';
const Database = require('./database')(() => require('@potluckdb/linux-x64-musl/potluckdb.node'), false);
Database.SqliteError = require('./sqlite-error');
module.exports = Database;
