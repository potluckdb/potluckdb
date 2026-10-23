'use strict';
// Makes the npm packages from the builds in prebuilds/<target>/:
//   dist/potluckdb/   the main package, with an optional dependency on each platform package
//   dist/<target>/    @potluckdb/<target>, holding potluckdb.node for one platform
//
// Usage: node scripts/package.js [--version <version>] [--prebuilds <dir>] [--out <dir>] [--pack]
// --version defaults to package.json's; each build must come from the core of
// that version. --pack also runs npm pack in each package folder.
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { TARGETS } = require('../lib/targets');

const ROOT = path.join(__dirname, '..');
const OS_NAMES = { linux: 'Linux', darwin: 'macOS', win32: 'Windows' };

function parseArgs(argv) {
	const args = {
		version: require('../package.json').version,
		prebuilds: path.join(ROOT, 'prebuilds'),
		out: path.join(ROOT, 'dist'),
		pack: false,
	};
	for (let i = 0; i < argv.length; ++i) {
		if (argv[i] === '--version') args.version = argv[++i];
		else if (argv[i] === '--prebuilds') args.prebuilds = path.resolve(argv[++i]);
		else if (argv[i] === '--out') args.out = path.resolve(argv[++i]);
		else if (argv[i] === '--pack') args.pack = true;
		else throw new Error(`unknown argument ${argv[i]}`);
	}
	if (!/^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/.test(args.version)) throw new Error(`not a version: ${args.version}`);
	return args;
}

function writeJson(file, value) {
	fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');
}

function copy(from, to) {
	fs.cpSync(from, to, { recursive: true });
}

function mainPackage(version, out) {
	const source = require('../package.json');
	const dir = path.join(out, 'potluckdb');
	fs.mkdirSync(dir, { recursive: true });
	for (const file of [...source.files, 'README.md', 'LICENSE']) copy(path.join(ROOT, file), path.join(dir, file));
	const pkg = { ...source, version };
	delete pkg.scripts;
	delete pkg.devDependencies;
	pkg.optionalDependencies = Object.fromEntries(Object.keys(TARGETS).map(target => [`@potluckdb/${target}`, version]));
	writeJson(path.join(dir, 'package.json'), pkg);
	return dir;
}

function platformPackage(version, target, prebuild, out) {
	const t = TARGETS[target];
	const info = JSON.parse(fs.readFileSync(path.join(prebuild, 'BUILD-INFO.json'), 'utf8'));
	if (info.target !== target || info.potluckdb_version !== version) {
		throw new Error(`${prebuild} was built from the ${info.target} core ${info.potluckdb_version}, not ${target} ${version}`);
	}
	const source = require('../package.json');
	const label = `${OS_NAMES[t.os]} ${t.cpu}${t.libc ? ` (${t.libc})` : ''}`;
	const dir = path.join(out, target);
	fs.mkdirSync(dir, { recursive: true });
	for (const file of ['potluckdb.node', 'LICENSE.txt', 'THIRD_PARTY_NOTICES.txt']) copy(path.join(prebuild, file), path.join(dir, file));
	copy(path.join(ROOT, 'LICENSE'), path.join(dir, 'LICENSE-APACHE-2.0.txt'));
	const notices = fs.readFileSync(path.join(ROOT, 'THIRD_PARTY_NOTICES.md'), 'utf8');
	const mit = notices.slice(notices.indexOf('```\nThe MIT License'), notices.indexOf('```\n\n## @types') + 3);
	fs.writeFileSync(path.join(dir, 'NOTICE.md'), `# Notices

\`potluckdb.node\` is PotluckDB's Node.js addon for ${label}. It contains:

- the PotluckDB library (PotluckDB's build of SQLite ${info.sqlite_version}), linked in statically,
  under the licence in \`LICENSE.txt\`;
- SQLite, which is in the public domain (see \`THIRD_PARTY_NOTICES.txt\`);
- the addon's own code (\`node/src\` in https://github.com/potluckdb/potluckdb),
  under the Apache License 2.0 (see \`LICENSE-APACHE-2.0.txt\`). It is adapted
  from better-sqlite3 13.0.3 (https://github.com/WiseLibs/better-sqlite3), under
  the MIT licence:

${mit}
`);
	fs.writeFileSync(path.join(dir, 'README.md'), `# @potluckdb/${target}

PotluckDB's native library for ${label}, ${t.minimum} or later. Don't install
it yourself: \`npm install potluckdb\` installs the package for your platform.
See https://github.com/potluckdb/potluckdb/tree/main/node.
`);
	writeJson(path.join(dir, 'package.json'), {
		name: `@potluckdb/${target}`,
		version,
		description: `PotluckDB's native library for ${label}, used by the potluckdb package.`,
		homepage: source.homepage,
		bugs: source.bugs,
		repository: source.repository,
		license: 'SEE LICENSE IN LICENSE.txt',
		os: [t.os],
		cpu: [t.cpu],
		...(t.libc ? { libc: [t.libc] } : {}),
		main: 'potluckdb.node',
		files: ['potluckdb.node', 'LICENSE.txt', 'THIRD_PARTY_NOTICES.txt', 'LICENSE-APACHE-2.0.txt', 'NOTICE.md'],
		engines: source.engines,
		publishConfig: { access: 'public' },
	});
	return dir;
}

function main() {
	const { version, prebuilds, out, pack } = parseArgs(process.argv.slice(2));
	fs.rmSync(out, { recursive: true, force: true });
	const dirs = [];
	const targets = fs.existsSync(prebuilds) ? fs.readdirSync(prebuilds).filter(t => TARGETS[t]) : [];
	if (!targets.length) throw new Error(`no builds in ${prebuilds}: run scripts/build.js first`);
	for (const target of targets.sort()) dirs.push(platformPackage(version, target, path.join(prebuilds, target), out));
	dirs.push(mainPackage(version, out));
	for (const dir of dirs) {
		console.log(`${path.relative(process.cwd(), dir)}: ${require(path.join(dir, 'package.json')).name}@${version}`);
		if (pack) {
			execSync(`npm pack --silent --pack-destination ${JSON.stringify(out)}`, { cwd: dir, stdio: 'inherit' });
		}
	}
}

try {
	main();
} catch (err) {
	console.error(err.message);
	process.exit(1);
}
