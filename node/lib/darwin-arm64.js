'use strict';
module.exports = require('./database')(() => require('@potluckdb/macos-arm64/potluckdb.node'), false);
module.exports.SqliteError = require('./sqlite-error');
