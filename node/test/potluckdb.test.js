'use strict';
// What potluckdb adds to or changes from better-sqlite3 (tests of the local build).
const assert = require('assert');
const { test } = require('node:test');
const Database = require('..');

test('Database.coreVersion is the version of the PotluckDB library', () => {
	const db = new Database(':memory:');
	assert.match(Database.coreVersion, /^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/);
	assert.strictEqual(db.prepare('select potluckdb_version()').pluck().get(), Database.coreVersion);
	db.close();
});

test('the quickstart query returns both versions', () => {
	const db = new Database(':memory:');
	const row = db.prepare('select potluckdb_version() as p, sqlite_version() as s').get();
	assert.deepStrictEqual(row, { p: Database.coreVersion, s: row.s });
	assert.match(row.s, /^3\.\d+\.\d+$/);
	db.close();
});

test('connections behave like better-sqlite3: foreign keys on, no double-quoted strings', () => {
	const db = new Database(':memory:');
	assert.strictEqual(db.pragma('foreign_keys', { simple: true }), 1);
	db.exec('create table parent (id integer primary key); create table child (p references parent(id))');
	assert.throws(() => db.prepare('insert into child values (1)').run(), { code: 'SQLITE_CONSTRAINT_FOREIGNKEY' });
	assert.throws(() => db.prepare('select "no such column"'), /no such column/);
	db.close();
});

test('the library is PotluckDB\'s, not another SQLite in the process', { skip: !hasNodeSqlite() && 'node:sqlite is not available' }, () => {
	// Node.js has its own SQLite built in; both work side by side.
	const { DatabaseSync } = require('node:sqlite');
	const other = new DatabaseSync(':memory:');
	assert.throws(() => other.prepare('select potluckdb_version()').get(), /no such function/);
	const db = new Database(':memory:');
	assert.strictEqual(db.prepare('select potluckdb_version()').pluck().get(), Database.coreVersion);
	other.close();
	db.close();
});

function hasNodeSqlite() {
	try {
		require('node:sqlite');
		return true;
	} catch (_) {
		return false;
	}
}
