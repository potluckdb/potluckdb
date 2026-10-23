'use strict';
const fs = require('fs');

// The platforms PotluckDB ships, named like the core archives
// (potluckdb-sqlite-<version>-<target>). Each one is an npm package,
// @potluckdb/<target>, that holds potluckdb.node for that platform.
// `entrypoint` is better-sqlite3's name for the same platform (see lib/linux-x64.js).
const TARGETS = {
	'linux-x64-gnu': { os: 'linux', cpu: 'x64', libc: 'glibc', entrypoint: 'linux-x64', runsOn: 'glibc 2.28 or later' },
	'linux-arm64-gnu': { os: 'linux', cpu: 'arm64', libc: 'glibc', entrypoint: 'linux-arm64', runsOn: 'glibc 2.28 or later' },
	'linux-x64-musl': { os: 'linux', cpu: 'x64', libc: 'musl', entrypoint: 'linuxmusl-x64', runsOn: 'musl systems such as Alpine' },
	'linux-arm64-musl': { os: 'linux', cpu: 'arm64', libc: 'musl', entrypoint: 'linuxmusl-arm64', runsOn: 'musl systems such as Alpine' },
	'macos-arm64': { os: 'darwin', cpu: 'arm64', entrypoint: 'darwin-arm64', runsOn: 'macOS 11 or later' },
	'macos-x64': { os: 'darwin', cpu: 'x64', entrypoint: 'darwin-x64', runsOn: 'macOS 11 or later' },
	'windows-x64': { os: 'win32', cpu: 'x64', entrypoint: 'win32-x64', runsOn: 'Windows 10 or later' },
	'windows-arm64': { os: 'win32', cpu: 'arm64', entrypoint: 'win32-arm64', runsOn: 'Windows 11' },
};

function isMusl() {
	// Node.js reports the glibc version it runs on, and none on musl.
	try {
		const report = process.report.getReport();
		const header = (typeof report === 'string' ? JSON.parse(report) : report).header;
		if (header) return !header.glibcVersionRuntime;
	} catch (_) {
		// A runtime without that report (some Bun and Deno versions).
	}
	try {
		return fs.readFileSync('/usr/bin/ldd', 'latin1').includes('musl');
	} catch (_) {
		return false;
	}
}

// The target for this process, or null if PotluckDB doesn't ship one.
function currentTarget() {
	const { platform, arch } = process;
	const libc = platform === 'linux' ? (isMusl() ? 'musl' : 'glibc') : undefined;
	for (const [name, t] of Object.entries(TARGETS)) {
		if (t.os === platform && t.cpu === arch && t.libc === libc) return name;
	}
	return null;
}

exports.TARGETS = TARGETS;
exports.currentTarget = currentTarget;
