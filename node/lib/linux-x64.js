'use strict';
module.exports = require('./database')(() => require('@potluckdb/linux-x64-gnu/potluckdb.node'), false);
module.exports.SqliteError = require('./sqlite-error');
