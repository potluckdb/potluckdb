'use strict';
// Runs better-sqlite3's own test suite against potluckdb: the files in
// test/better-sqlite3/test/, unmodified from better-sqlite3 (the version is in
// known-failures.json). Tests listed in known-failures.json may fail, each for
// the reason given there. Any other failure fails the run, and so does a listed
// test that passes now (then remove it from the list).
//
// Usage: node test/run-better-sqlite3.js [--grep <pattern>]
// Needs a build first (npm run build); it tests build/Release/potluckdb.node.
const fs = require('fs');
const path = require('path');

const STANDIN = path.join(__dirname, 'better-sqlite3');
const KNOWN = require('./known-failures.json');

function knownFailures() {
	const known = new Map();
	for (const entry of KNOWN.failures) {
		if (!entry.platforms || entry.platforms.includes(process.platform)) known.set(entry.test, entry.reason);
	}
	return known;
}

// The tests run from better-sqlite3's package root and expect its build there:
// build/Release/better_sqlite3.node (the default addon) and test_extension.node.
// The stand-in gets copies of potluckdb's, and the copy of the addon is an
// alias of potluckdb's default one, as a symlink would be.
function placeBuild() {
	const configuration = ['Debug', 'Release'].find(c => fs.existsSync(path.join(__dirname, '..', 'build', c, 'potluckdb.node')));
	if (!configuration) throw new Error('build/Release/potluckdb.node is missing: build first (npm run build)');
	const built = path.join(__dirname, '..', 'build', configuration);
	const destination = path.join(STANDIN, 'build', configuration);
	fs.rmSync(path.join(STANDIN, 'build'), { recursive: true, force: true });
	fs.mkdirSync(destination, { recursive: true });
	fs.copyFileSync(path.join(built, 'test_extension.node'), path.join(destination, 'test_extension.node'));
	const alias = path.join(destination, 'better_sqlite3.node');
	fs.copyFileSync(path.join(built, 'potluckdb.node'), alias);
	require(path.join(built, 'potluckdb.node'));
	require.cache[alias] = require.cache[path.join(built, 'potluckdb.node')];
}

async function main() {
	// mocha is an ES module, which Node.js 20 can't require().
	const { default: Mocha } = await import('mocha');
	placeBuild();
	process.chdir(STANDIN);
	const args = process.argv.slice(2);
	const grep = args[0] === '--grep' ? args[1] : undefined;
	const mocha = new Mocha({ timeout: 5000, slow: 75, reporter: 'dot', grep });
	const dir = path.join(STANDIN, 'test');
	for (const file of fs.readdirSync(dir).filter(f => f.endsWith('.js')).sort()) mocha.addFile(path.join(dir, file));

	const known = knownFailures();
	const failed = new Map();
	let passed = 0;
	let pending = 0;
	const runner = mocha.run(() => {
		const total = runner.total;
		const unexpected = [...failed].filter(([title]) => !known.has(title));
		const fixed = grep ? [] : [...known.keys()].filter(title => !failed.has(title));
		const ran = total - pending;
		console.log(`\nbetter-sqlite3 ${KNOWN['better-sqlite3']} test suite on potluckdb (${process.platform}-${process.arch}, Node.js ${process.version}):`);
		console.log(`  ${passed} of ${ran} tests pass (${(100 * passed / ran).toFixed(1)}%); ${pending} skipped by the suite on this platform`);
		console.log(`  ${failed.size} failures (tests and hooks), ${failed.size - unexpected.length} of them known`);
		for (const [title, message] of unexpected) console.log(`\nNEW FAILURE: ${title}\n  ${message}`);
		for (const title of fixed) console.log(`\nNOW PASSES (remove it from known-failures.json): ${title}`);
		process.exit(unexpected.length || fixed.length ? 1 : 0);
	});
	runner.on('pass', () => { passed += 1; });
	runner.on('pending', () => { pending += 1; });
	runner.on('fail', (test, err) => {
		failed.set(test.fullTitle(), String(err && err.message).split('\n')[0]);
	});
}

main().catch((err) => {
	console.error(err);
	process.exit(1);
});
