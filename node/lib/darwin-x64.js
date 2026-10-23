'use strict';
module.exports = require('./database')(() => require('@potluckdb/macos-x64/potluckdb.node'), false);
module.exports.SqliteError = require('./sqlite-error');
