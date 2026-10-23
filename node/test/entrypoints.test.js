'use strict';
// How potluckdb finds its binary when installed: the platform package
// @potluckdb/<target>, through the default entry point or a static one
// (potluckdb/linux-x64 and so on, as in better-sqlite3). Uses the local build
// in a node_modules layout like npm's.
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { test, before, after } = require('node:test');
const { TARGETS, currentTarget } = require('../lib/targets');

const ROOT = path.join(__dirname, '..');
const target = currentTarget();
let project;

function install(dir, withPlatformPackage) {
	const pkg = path.join(dir, 'node_modules', 'potluckdb');
	fs.mkdirSync(pkg, { recursive: true });
	fs.cpSync(path.join(ROOT, 'lib'), path.join(pkg, 'lib'), { recursive: true });
	for (const file of ['package.json', 'index.mjs']) fs.copyFileSync(path.join(ROOT, file), path.join(pkg, file));
	if (!withPlatformPackage) return;
	const platform = path.join(dir, 'node_modules', '@potluckdb', target);
	fs.mkdirSync(platform, { recursive: true });
	fs.copyFileSync(path.join(ROOT, 'build', 'Release', 'potluckdb.node'), path.join(platform, 'potluckdb.node'));
	fs.writeFileSync(path.join(platform, 'package.json'), JSON.stringify({ name: `@potluckdb/${target}`, main: 'potluckdb.node' }));
}

function run(dir, script) {
	return execFileSync(process.execPath, ['-e', script], { cwd: dir, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
}

before(() => {
	project = fs.mkdtempSync(path.join(os.tmpdir(), 'potluckdb-entrypoints-'));
	install(path.join(project, 'installed'), true);
	install(path.join(project, 'missing'), false);
});

after(() => {
	fs.rmSync(project, { recursive: true, force: true });
});

test('the default entry point loads the platform package', () => {
	const out = run(path.join(project, 'installed'), `
		const Database = require('potluckdb');
		const db = new Database(':memory:');
		process.stdout.write(JSON.stringify([db.prepare('select potluckdb_version() v').get().v, Database.coreVersion,
			Object.keys(require.cache).some(f => f.includes('@potluckdb'))]));`);
	const [version, coreVersion, fromPackage] = JSON.parse(out);
	assert.strictEqual(version, coreVersion);
	assert.strictEqual(fromPackage, true);
});

test('the static entry point for this platform loads the platform package directly', () => {
	const entrypoint = TARGETS[target].entrypoint;
	const out = run(path.join(project, 'installed'), `
		const Database = require('potluckdb/${entrypoint}');
		const db = new Database(':memory:');
		let rejected = false;
		try { new Database(':memory:', { nativeBinding: {} }); } catch (err) { rejected = err instanceof TypeError; }
		process.stdout.write(JSON.stringify([db.prepare('select 1 as value').get(), rejected, typeof Database.SqliteError,
			Object.keys(require.cache).some(f => /[\\\\/]lib[\\\\/](binding|targets)\\.js$/.test(f))]));`);
	assert.deepStrictEqual(JSON.parse(out), [{ value: 1 }, true, 'function', false]);
});

test('every static entry point names the right platform package', () => {
	const exportsMap = require('../package.json').exports;
	for (const [name, t] of Object.entries(TARGETS)) {
		const source = fs.readFileSync(path.join(ROOT, 'lib', `${t.entrypoint}.js`), 'utf8');
		assert.ok(source.includes(`require('@potluckdb/${name}/potluckdb.node')`), `lib/${t.entrypoint}.js`);
		assert.ok(!source.includes('./binding'), `lib/${t.entrypoint}.js`);
		assert.deepStrictEqual(exportsMap[`./${t.entrypoint}`], { types: './index.d.ts', default: `./lib/${t.entrypoint}.js` });
	}
});

test('a missing platform package gives a clear error', () => {
	assert.throws(() => run(path.join(project, 'missing'), `new (require('potluckdb'))(':memory:')`),
		(err) => err.stderr.includes(`the package @potluckdb/${target} is not installed`));
});
