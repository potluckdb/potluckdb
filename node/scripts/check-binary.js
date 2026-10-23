'use strict';
// Checks a built potluckdb.node:
// - it exports only the Node-API entry points, so none of SQLite's symbols
//   (sqlite3_*) or PotluckDB's (potluckdb_*): the library is linked in with
//   hidden symbols and can't clash with another SQLite in the same process;
// - it runs on the oldest systems PotluckDB supports: glibc 2.28 (and the
//   libstdc++ of that generation), macOS 11, and the right Windows CPU.
//
// Usage: node scripts/check-binary.js [--target <target>] [<file>]
// (default: this machine's target and prebuilds/<target>/potluckdb.node)
// Needs nm and objdump on Linux, nm and otool on macOS; nothing on Windows.
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { TARGETS, currentTarget } = require('../lib/targets');

const NODE_API_EXPORTS = ['napi_register_module_v1', 'node_api_module_get_api_version_v1'];
const MAX = { GLIBC: '2.28', GLIBCXX: '3.4.25', CXXABI: '1.3.11', macos: '11.0' };

function run(command, args) {
	return execFileSync(command, args, { encoding: 'utf8', maxBuffer: 64 << 20 });
}

function compareVersions(a, b) {
	const x = a.split('.').map(Number);
	const y = b.split('.').map(Number);
	for (let i = 0; i < Math.max(x.length, y.length); ++i) {
		if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) - (y[i] || 0);
	}
	return 0;
}

// Exported names and CPU of a Windows DLL, read from its PE headers.
function peInfo(file) {
	const b = fs.readFileSync(file);
	const pe = b.readUInt32LE(0x3c);
	if (b.readUInt32LE(pe) !== 0x4550) throw new Error(`${file} is not a PE file`);
	const machine = b.readUInt16LE(pe + 4);
	const sections = b.readUInt16LE(pe + 6);
	const optional = pe + 24;
	const optionalSize = b.readUInt16LE(pe + 20);
	const exportRva = b.readUInt32LE(optional + (b.readUInt16LE(optional) === 0x20b ? 112 : 96));
	const toOffset = (rva) => {
		for (let i = 0, s = optional + optionalSize; i < sections; ++i, s += 40) {
			const va = b.readUInt32LE(s + 12);
			if (rva >= va && rva < va + b.readUInt32LE(s + 16)) return rva - va + b.readUInt32LE(s + 20);
		}
		throw new Error(`RVA ${rva} is in no section`);
	};
	const names = [];
	if (exportRva) {
		const dir = toOffset(exportRva);
		const count = b.readUInt32LE(dir + 24);
		const table = toOffset(b.readUInt32LE(dir + 32));
		for (let i = 0; i < count; ++i) {
			const at = toOffset(b.readUInt32LE(table + 4 * i));
			names.push(b.toString('latin1', at, b.indexOf(0, at)));
		}
	}
	return { names, machine: { 0x8664: 'x64', 0xaa64: 'arm64' }[machine] || `0x${machine.toString(16)}` };
}

function check(file, target) {
	const t = TARGETS[target];
	const problems = [];
	let exported;
	if (t.os === 'linux') {
		exported = run('nm', ['-D', '--defined-only', file]).split('\n').map(l => l.trim().split(/\s+/).pop()).filter(Boolean);
		const needs = {};
		for (const [, name, version] of run('objdump', ['-T', file]).matchAll(/\b(GLIBC|GLIBCXX|CXXABI)_(\d+(?:\.\d+)*)\b/g)) {
			if (!needs[name] || compareVersions(version, needs[name]) > 0) needs[name] = version;
		}
		console.log(`needs: ${Object.entries(needs).map(([n, v]) => `${n} ${v}`).join(', ') || 'no versioned glibc symbols'}`);
		if (t.libc === 'musl' && needs.GLIBC) problems.push(`musl build needs glibc ${needs.GLIBC}`);
		// libstdc++ (GLIBCXX, CXXABI) has the same versions on glibc and musl.
		for (const [name, version] of Object.entries(needs)) {
			if (compareVersions(version, MAX[name]) > 0) problems.push(`needs ${name} ${version}, more than ${MAX[name]}`);
		}
	} else if (t.os === 'darwin') {
		exported = run('nm', ['-gU', file]).split('\n').map(l => l.trim().split(/\s+/).pop()).filter(Boolean).map(s => s.replace(/^_/, ''));
		const minos = run('otool', ['-l', file]).match(/minos (\S+)|version (\d+\.\d+)/);
		const version = minos && (minos[1] || minos[2]);
		console.log(`minimum macOS: ${version}`);
		if (!version || compareVersions(version, MAX.macos) > 0) problems.push(`needs macOS ${version}, more than ${MAX.macos}`);
		const archs = run('lipo', ['-archs', file]).trim();
		if (archs !== { x64: 'x86_64', arm64: 'arm64' }[t.cpu]) problems.push(`built for ${archs}, not ${t.cpu}`);
	} else {
		const info = peInfo(file);
		exported = info.names;
		if (info.machine !== t.cpu) problems.push(`built for ${info.machine}, not ${t.cpu}`);
	}
	console.log(`exports: ${exported.join(', ')}`);
	const leaked = exported.filter(name => /^(sqlite3|potluckdb)/i.test(name));
	if (leaked.length) problems.push(`exports ${leaked.length} library symbols, e.g. ${leaked.slice(0, 5).join(', ')}`);
	const unexpected = exported.filter(name => !NODE_API_EXPORTS.includes(name) && !leaked.includes(name));
	if (unexpected.length) problems.push(`exports unexpected symbols: ${unexpected.slice(0, 10).join(', ')}`);
	if (!exported.includes('napi_register_module_v1')) problems.push('does not export napi_register_module_v1');
	return problems;
}

function main() {
	const args = process.argv.slice(2);
	let target = currentTarget();
	let file;
	for (let i = 0; i < args.length; ++i) {
		if (args[i] === '--target') target = args[++i];
		else file = args[i];
	}
	if (!TARGETS[target]) throw new Error(`unknown target ${target}`);
	file = file || path.join(__dirname, '..', 'prebuilds', target, 'potluckdb.node');
	console.log(`checking ${file} (${target})`);
	const problems = check(file, target);
	for (const problem of problems) console.error(`problem: ${problem}`);
	if (problems.length) process.exit(1);
	console.log('ok: exports no SQLite symbols and fits the oldest supported systems');
}

main();
