'use strict';
// scripts/check-binary.js on this machine's build: it passes for this
// machine's target, and finds the other CPU, the other C library, a
// patched-in glibc version it doesn't know, and a symbol needed from no listed
// library (in a library compiled with this machine's cc). Linux only.
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync, spawnSync } = require('child_process');
const { test } = require('node:test');
const { TARGETS, currentTarget } = require('../lib/targets');

const ROOT = path.join(__dirname, '..');
const target = currentTarget();
const file = path.join(ROOT, 'prebuilds', String(target), 'potluckdb.node');
const skip = process.platform !== 'linux' && 'Linux only';
const otherCpu = String(target).replace(/x64|arm64/, cpu => (cpu === 'x64' ? 'arm64' : 'x64'));
const otherLibc = String(target).replace(/gnu|musl/, libc => (libc === 'gnu' ? 'musl' : 'gnu'));

function check(as, f = file) {
	const r = spawnSync(process.execPath, [path.join(ROOT, 'scripts', 'check-binary.js'), '--target', as, f], { encoding: 'utf8' });
	return { status: r.status, out: r.stdout + r.stderr };
}

test('passes for its own target', { skip }, () => {
	const r = check(target);
	assert.strictEqual(r.status, 0, r.out);
});

test('finds the other CPU', { skip }, () => {
	const r = check(otherCpu);
	assert.strictEqual(r.status, 1, r.out);
	assert.match(r.out, new RegExp(`^problem: built for ${TARGETS[target].cpu}, not ${TARGETS[otherCpu].cpu}$`, 'm'));
});

test('finds the other C library', { skip }, () => {
	const r = check(otherLibc);
	assert.strictEqual(r.status, 1, r.out);
	const libc = TARGETS[target].libc === 'musl' ? 'libc\\.musl-\\S+' : 'libc\\.so\\.6';
	assert.match(r.out, new RegExp(`^problem: needs libraries that ${otherLibc} systems may lack: .*\\b${libc}`, 'm'));
});

// The check on a temp copy of the build with text written at byte at.
function checkPatched(at, text) {
	const b = fs.readFileSync(file);
	b.write(text, at, 'latin1');
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'potluckdb-check-'));
	try {
		fs.writeFileSync(path.join(dir, 'potluckdb.node'), b);
		return check(target, path.join(dir, 'potluckdb.node'));
	} finally {
		fs.rmSync(dir, { recursive: true, force: true });
	}
}

test('finds a glibc version it does not know', { skip: skip || (TARGETS[target].libc !== 'glibc' && 'glibc only') }, () => {
	// The same name with its number replaced by letters, in the dynamic string table.
	const found = fs.readFileSync(file, 'latin1').match(/(?<=\0)GLIBC_2\.[\d.]+(?=\0)/);
	const patched = `GLIBC_${'X'.repeat(found[0].length - 6)}`;
	const r = checkPatched(found.index, patched);
	assert.strictEqual(r.status, 1, r.out);
	assert.match(r.out, new RegExp(`^problem: needs ${patched} from \\S+, a version this check doesn't know$`, 'm'));
});

test('finds a symbol no listed library gives', { skip: skip || (spawnSync('cc', ['--version']).status !== 0 && 'no cc') }, () => {
	// A library that needs strlen (the C library's), __dynamic_cast (libstdc++'s,
	// not linked) and a weak symbol nothing defines, which may stay.
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'potluckdb-check-'));
	try {
		fs.writeFileSync(path.join(dir, 'lib.c'), [
			'#include <string.h>',
			'void *__dynamic_cast(const void *, const void *, const void *, long);',
			'void potluckdb_absent(void) __attribute__((weak));',
			'void *napi_register_module_v1(void *env, void *exports) {',
			'\tif (potluckdb_absent) potluckdb_absent();',
			'\treturn __dynamic_cast(exports, env, env, strlen(exports));',
			'}',
		].join('\n'));
		execFileSync('cc', ['-shared', '-fPIC', '-O0', '-o', path.join(dir, 'lib.node'), path.join(dir, 'lib.c')]);
		const r = check(target, path.join(dir, 'lib.node'));
		assert.strictEqual(r.status, 1, r.out);
		const line = TARGETS[target].libc === 'musl' ? "needs 1 symbols musl's C library doesn't define" : 'needs 1 unversioned symbols';
		assert.match(r.out, new RegExp(`^problem: ${line}, e\\.g\\. __dynamic_cast$`, 'm'));
	} finally {
		fs.rmSync(dir, { recursive: true, force: true });
	}
});
