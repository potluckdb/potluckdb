'use strict';
// Builds the addon for one target and puts it, with the licence files of the
// core library it links in, into prebuilds/<target>/ (see scripts/package.js).
//
// Usage: node scripts/build.js [--target <target>] [--debug]
// The core archive comes from POTLUCKDB_CORE_DIR or the GitHub release (see
// scripts/core.js); its version is POTLUCKDB_CORE_VERSION or package.json's.
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { TARGETS, currentTarget } = require('../lib/targets');
const { getCore } = require('./core');

const ROOT = path.join(__dirname, '..');

function parseArgs(argv) {
	const args = { target: null, debug: false };
	for (let i = 0; i < argv.length; ++i) {
		if (argv[i] === '--target') args.target = argv[++i];
		else if (argv[i] === '--debug') args.debug = true;
		else throw new Error(`unknown argument ${argv[i]}`);
	}
	args.target = args.target || currentTarget();
	if (!TARGETS[args.target]) throw new Error(`unknown target ${args.target}; known: ${Object.keys(TARGETS).join(', ')}`);
	return args;
}

async function main() {
	const { target, debug } = parseArgs(process.argv.slice(2));
	const t = TARGETS[target];
	if (t.os !== process.platform) throw new Error(`${target} must be built on ${t.os}`);
	const core = await getCore({ target });
	console.log(`building ${target} against ${core}`);

	const nodeGyp = require.resolve('node-gyp/bin/node-gyp.js');
	execFileSync(process.execPath, [
		nodeGyp, 'rebuild', `--arch=${t.cpu}`, '--jobs=max', debug ? '--debug' : '--release',
		`--potluckdb_core=${core.replace(/\\/g, '/')}`,
	], { cwd: ROOT, stdio: 'inherit' });

	const out = path.join(ROOT, 'prebuilds', target);
	fs.rmSync(out, { recursive: true, force: true });
	fs.mkdirSync(out, { recursive: true });
	fs.copyFileSync(path.join(ROOT, 'build', debug ? 'Debug' : 'Release', 'potluckdb.node'), path.join(out, 'potluckdb.node'));
	for (const file of ['LICENSE.txt', 'THIRD_PARTY_NOTICES.txt', 'BUILD-INFO.json']) {
		fs.copyFileSync(path.join(core, file), path.join(out, file));
	}
	console.log(`built ${path.relative(ROOT, path.join(out, 'potluckdb.node'))}`);
}

main().catch((err) => {
	console.error(err.message);
	process.exit(1);
});
