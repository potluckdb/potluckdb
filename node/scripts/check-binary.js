'use strict';
// Checks a built potluckdb.node:
// - it exports only the Node-API entry points, so none of SQLite's symbols
//   (sqlite3_*) or PotluckDB's (potluckdb_*): the library is linked in with
//   hidden symbols and can't clash with another SQLite in the same process;
// - it is built for the target's CPU (on Linux, as a 64-bit little-endian ELF);
// - it runs on the oldest systems PotluckDB supports: macOS 11, and on Linux
//   - it needs only libraries every such system has: on glibc, glibc's own,
//     libstdc++ and libgcc_s; on musl, musl's C library alone (libstdc++ and
//     libgcc are linked in);
//   - every symbol it needs (bar weak ones) is Node-API's, from Node.js, or
//     comes from those libraries: on glibc it has a symbol version, on musl
//     musl 1.2.5's C library defines it (so on musl, the check needs a musl
//     system with musl 1.2.5 or older: musl only adds symbols);
//   - on glibc, every symbol version it needs is one this check knows, and at
//     most glibc 2.28 and the libstdc++ and libgcc_s of that generation
//     (AlmaLinux 8's); on musl, which has no symbol versions, it needs none.
//
// Usage: node scripts/check-binary.js [--target <target>] [<file>]
// (default: this machine's target and prebuilds/<target>/potluckdb.node)
// Needs readelf and objdump on Linux, nm and otool on macOS; nothing on Windows.
const fs = require('fs');
const path = require('path');
const { execFileSync, spawnSync } = require('child_process');
const { TARGETS, currentTarget } = require('../lib/targets');

const NODE_API_EXPORTS = ['napi_register_module_v1', 'node_api_module_get_api_version_v1'];
// GCC: the newest version AlmaLinux 8's libgcc_s.so.1 has, on x64 and arm64.
// musl: Alpine 3.20's.
const MAX = { GLIBC: '2.28', GLIBCXX: '3.4.25', CXXABI: '1.3.11', GCC: '7.0.0', musl: '1.2.5', macos: '11.0' };
// Node.js itself needs libstdc++ and libgcc_s, so every system it runs on has them.
const GLIBC_LIBRARIES = ['libc.so.6', 'libm.so.6', 'libpthread.so.0', 'libdl.so.2', 'libstdc++.so.6', 'libgcc_s.so.1'];
const LIBRARIES = {
	'linux-x64-gnu': [...GLIBC_LIBRARIES, 'ld-linux-x86-64.so.2'],
	'linux-arm64-gnu': [...GLIBC_LIBRARIES, 'ld-linux-aarch64.so.1'],
	'linux-x64-musl': ['libc.musl-x86_64.so.1'],
	'linux-arm64-musl': ['libc.musl-aarch64.so.1'],
};

// In the C locale: binutils translates the headings parsed below.
function run(command, args) {
	return execFileSync(command, args, { encoding: 'utf8', maxBuffer: 64 << 20, env: { ...process.env, LC_ALL: 'C' } });
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

// CPU of a Linux shared library, read from its ELF header: 64-bit (class 2),
// little-endian (data 1), and e_machine.
function elfCpu(file) {
	const b = fs.readFileSync(file);
	if (b.readUInt32BE(0) !== 0x7f454c46) throw new Error(`${file} is not an ELF file`);
	if (b[4] !== 2 || b[5] !== 1) return `ELF class ${b[4]}, data ${b[5]}`;
	const machine = b.readUInt16LE(18);
	return { 62: 'x64', 183: 'arm64' }[machine] || `ELF machine ${machine}`;
}

// The non-local dynamic symbols of a Linux shared library, from readelf's
// "Num: Value Size Type Bind Vis Ndx Name[@version]" lines.
function dynamicSymbols(file) {
	const symbols = [];
	for (const line of run('readelf', ['--dyn-syms', '-W', file]).split('\n')) {
		const [, bind, ndx, name, version] = line.match(/^\s*\d+:\s+\S+\s+\S+\s+\S+\s+(\S+)\s+\S+(?: \[[^\]]*\])?\s+(\S+)\s+([^\s@]+)(?:@+(\S+))?/) || [];
		if (bind && bind !== 'LOCAL') symbols.push({ name, version, defined: ndx !== 'UND', weak: bind === 'WEAK' });
	}
	return symbols;
}

function check(file, target) {
	const t = TARGETS[target];
	const problems = [];
	let exported;
	if (t.os === 'linux') {
		const cpu = elfCpu(file);
		if (cpu !== t.cpu) problems.push(`built for ${cpu}, not ${t.cpu}`);
		const symbols = dynamicSymbols(file);
		exported = symbols.filter(s => s.defined).map(s => s.name);
		// The libraries it needs (NEEDED) and the versions it needs from each:
		// the version references objdump -p lists under each library.
		const libraries = [];
		const refs = [];
		let from = '';
		for (const line of run('objdump', ['-p', file]).split('\n')) {
			const needed = line.match(/^\s+NEEDED\s+(\S+)/);
			if (needed) libraries.push(needed[1]);
			const library = line.match(/^\s+required from (\S+):/);
			if (library || /^\S/.test(line)) from = library ? library[1] : '';
			else if (from && line.trim()) refs.push([from, line.trim().split(/\s+/).pop()]);
		}
		const extra = libraries.filter(l => !LIBRARIES[target].includes(l));
		if (extra.length) problems.push(`needs libraries that ${target} systems may lack: ${extra.join(', ')}`);
		// Guards against output this parsing misses: every build needs its C
		// library and, on glibc, some GLIBC version.
		const libc = LIBRARIES[target].find(l => l.startsWith('libc.'));
		if (!libraries.includes(libc)) problems.push(`objdump -p lists no NEEDED ${libc}`);
		if (t.libc === 'musl' && refs.length) problems.push(`musl build needs ${refs.length} symbol versions (musl has none), e.g. ${refs.slice(0, 5).map(([l, v]) => `${v} from ${l}`).join(', ')}`);
		const needs = {};
		for (const [library, version] of refs) {
			const [, name, number] = version.match(/^(GLIBC|GLIBCXX|CXXABI|GCC)_(\d+(?:\.\d+)*)$/) || [];
			// GCC's versions are libgcc_s.so.1's, which has only those and, on
			// arm64, GLIBC_2.0 for its frame registration (crtbeginS.o may use it).
			const libgcc = library === 'libgcc_s.so.1';
			if (libgcc && version === 'GLIBC_2.0' && t.cpu === 'arm64') continue;
			if (!name || (name === 'GCC') !== libgcc) problems.push(`needs ${version} from ${library}, a version this check doesn't know`);
			else if (!needs[name] || compareVersions(number, needs[name]) > 0) needs[name] = number;
		}
		if (t.libc === 'glibc' && !needs.GLIBC) problems.push('objdump -p lists no GLIBC version');
		console.log(`needs: ${[...libraries, ...Object.entries(needs).map(([n, v]) => `${n} ${v}`)].join(', ')}`);
		for (const [name, version] of Object.entries(needs)) {
			if (compareVersions(version, MAX[name]) > 0) problems.push(`needs ${name} ${version}, more than ${MAX[name]}`);
		}
		// Who gives each symbol it needs, bar Node-API's (Node.js does): on glibc a
		// library that versions it, as glibc, libstdc++ and libgcc_s do all theirs
		// (an unversioned one binds to whatever the process has); on musl, musl's
		// C library. Weak ones may stay: they are null when absent, and their
		// users test for that.
		const imports = symbols.filter(s => !s.defined && !s.weak && !/^(napi|node_api)_/.test(s.name));
		const musl = `/lib/${libc}`;
		if (t.libc === 'glibc') {
			const unversioned = imports.filter(s => !s.version).map(s => s.name);
			if (unversioned.length) problems.push(`needs ${unversioned.length} unversioned symbols, e.g. ${unversioned.slice(0, 5).join(', ')}`);
		} else if (!fs.existsSync(musl)) {
			problems.push(`can't check the symbols it needs without ${musl}: run this check on a musl system`);
		} else {
			// musl's C library is its dynamic loader too: run alone, it prints
			// its version and exits 1.
			const version = ((spawnSync(musl, [], { encoding: 'utf8' }).stderr || '').match(/^Version (\S+)$/m) || [])[1];
			console.log(`musl: ${version}`);
			const why = `so the symbols checked against it might be missing from musl ${MAX.musl}`;
			if (!version) problems.push(`can't read the version of ${musl}, ${why}`);
			else if (compareVersions(version, MAX.musl) > 0) problems.push(`this system has musl ${version}, newer than ${MAX.musl}, ${why}`);
			const defined = new Set(dynamicSymbols(musl).filter(s => s.defined).map(s => s.name));
			const missing = imports.filter(s => !defined.has(s.name)).map(s => s.name);
			if (missing.length) problems.push(`needs ${missing.length} symbols musl's C library doesn't define, e.g. ${missing.slice(0, 5).join(', ')}`);
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
