'use strict';
// Finds the PotluckDB core archive for a target and unpacks it: the addon is
// built from its headers and static library, and ships its licence files.
//
// Where the archive comes from:
// - POTLUCKDB_CORE_DIR: a folder holding the archives
//   (potluckdb-sqlite-<version>-<target>.tar.gz or .zip, checked against
//   SHA256SUMS if the folder has one), or one unpacked archive;
// - otherwise the GitHub release v<version> of potluckdb/potluckdb, checked
//   against the release's SHA256SUMS.
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { TARGETS } = require('../lib/targets');

const ROOT = path.join(__dirname, '..');
const RELEASES = 'https://github.com/potluckdb/potluckdb/releases/download';

function archiveName(version, target) {
	if (!TARGETS[target]) throw new Error(`unknown target ${target}; known: ${Object.keys(TARGETS).join(', ')}`);
	return `potluckdb-sqlite-${version}-${target}.${TARGETS[target].os === 'win32' ? 'zip' : 'tar.gz'}`;
}

function defaultVersion() {
	return process.env.POTLUCKDB_CORE_VERSION || require('../package.json').version;
}

async function download(url) {
	const response = await fetch(url);
	if (!response.ok) throw new Error(`download failed: ${url}: HTTP ${response.status}`);
	return Buffer.from(await response.arrayBuffer());
}

// Throws unless the file's SHA-256 is the one SHA256SUMS lists for it.
function verify(data, file, sums, where) {
	const line = sums.split('\n').find(l => l.trim().split(/\s+\*?/)[1] === file);
	if (!line) throw new Error(`SHA256SUMS of ${where} does not list ${file}`);
	const actual = crypto.createHash('sha256').update(data).digest('hex');
	if (line.trim().split(/\s+/)[0] !== actual) throw new Error(`${file} does not match SHA256SUMS of ${where}`);
}

async function fetchArchive(version, file, cacheDir) {
	const destination = path.join(cacheDir, file);
	if (fs.existsSync(destination)) return destination;
	const base = `${RELEASES}/v${version}`;
	console.log(`downloading ${base}/${file}`);
	const [data, sums] = await Promise.all([download(`${base}/${file}`), download(`${base}/SHA256SUMS`)]);
	verify(data, file, sums.toString('utf8'), `v${version}`);
	fs.mkdirSync(cacheDir, { recursive: true });
	fs.writeFileSync(destination, data);
	return destination;
}

function extract(archive, outDir) {
	const name = path.basename(archive).replace(/\.(tar\.gz|zip)$/, '');
	fs.rmSync(path.join(outDir, name), { recursive: true, force: true });
	fs.mkdirSync(outDir, { recursive: true });
	if (archive.endsWith('.zip') && process.platform === 'linux') {
		execFileSync('unzip', ['-q', '-o', archive, '-d', outDir], { stdio: 'inherit' });
	} else {
		// GNU or busybox tar on Linux; bsdtar (which also reads zip) on macOS and
		// Windows, where a GNU tar from Git Bash may come first on PATH.
		const tar = process.platform === 'win32' ? path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'tar.exe') : 'tar';
		execFileSync(tar, ['-xf', archive, '-C', outDir], { stdio: 'inherit' });
	}
	return path.join(outDir, name);
}

function check(dir, version, target) {
	const info = JSON.parse(fs.readFileSync(path.join(dir, 'BUILD-INFO.json'), 'utf8'));
	if (info.target !== target || info.potluckdb_version !== version) {
		throw new Error(`${dir} holds ${info.target} ${info.potluckdb_version}, not ${target} ${version}`);
	}
	return dir;
}

// Returns the folder of the unpacked core archive for the target.
async function getCore({ target, version = defaultVersion(), coreDir = process.env.POTLUCKDB_CORE_DIR }) {
	const file = archiveName(version, target);
	const name = file.replace(/\.(tar\.gz|zip)$/, '');
	const unpacked = path.join(ROOT, '.cache', 'core'); // not build/: node-gyp rebuild empties it
	let archive;
	if (coreDir) {
		coreDir = path.resolve(coreDir);
		if (fs.existsSync(path.join(coreDir, 'include', 'sqlite3.h'))) return check(coreDir, version, target);
		if (fs.existsSync(path.join(coreDir, name, 'include', 'sqlite3.h'))) return check(path.join(coreDir, name), version, target);
		archive = path.join(coreDir, file);
		if (!fs.existsSync(archive)) throw new Error(`POTLUCKDB_CORE_DIR=${coreDir} has no ${file}`);
		const sums = path.join(coreDir, 'SHA256SUMS');
		if (fs.existsSync(sums)) verify(fs.readFileSync(archive), file, fs.readFileSync(sums, 'utf8'), coreDir);
	} else {
		archive = await fetchArchive(version, file, path.join(ROOT, '.cache', 'downloads'));
	}
	return check(extract(archive, unpacked), version, target);
}

module.exports = { getCore, archiveName, defaultVersion };

if (require.main === module) {
	const [target, version] = process.argv.slice(2);
	getCore({ target, version: version || undefined }).then(dir => console.log(dir), (err) => {
		console.error(err.message);
		process.exit(1);
	});
}
