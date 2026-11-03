'use strict';
// scripts/check-binary.js on this machine's build: it passes for this
// machine's target, and finds the other CPU, the other C library and a
// patched-in import it must reject (on glibc a symbol version it doesn't know,
// on musl a C++ runtime symbol). Linux only.
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

test('finds a C++ runtime symbol musl lacks', { skip: skip || (TARGETS[target].libc !== 'musl' && 'musl only') }, () => {
	// One C library import renamed to a C++ name of the same length, in the dynamic string table.
	const b = fs.readFileSync(file, 'latin1');
	const imports = execFileSync('nm', ['-D', '--undefined-only', file], { encoding: 'utf8' }).match(/(?<= U )[a-z]\w{3,}$/gm);
	const name = imports.find(n => b.includes(`\0${n}\0`));
	const patched = `_Z${'X'.repeat(name.length - 2)}`;
	const r = checkPatched(b.indexOf(`\0${name}\0`) + 1, patched);
	assert.strictEqual(r.status, 1, r.out);
	assert.match(r.out, new RegExp(`^problem: needs 1 C\\+\\+ runtime symbols musl lacks, e\\.g\\. ${patched}$`, 'm'));
});
