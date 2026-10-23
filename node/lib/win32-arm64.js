'use strict';
module.exports = require('./database')(() => require('@potluckdb/windows-arm64/potluckdb.node'), false);
module.exports.SqliteError = require('./sqlite-error');
