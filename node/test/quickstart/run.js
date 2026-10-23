'use strict';
// Installs the packed packages (potluckdb and the one for this platform) into
// a new project with npm, as a user would, and runs the README's quickstart
// there, as CommonJS and as an ES module.
//
// Usage: node test/quickstart/run.js [<dir>]   (default: dist/, from scripts/package.js --pack)
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync, execFileSync } = require('child_process');
const { currentTarget } = require('../../lib/targets');

const dist = path.resolve(process.argv[2] || path.join(__dirname, '..', '..', 'dist'));
const target = currentTarget();
const tarballs = fs.readdirSync(dist).filter(f => f.endsWith('.tgz'));
const main = tarballs.find(f => /^potluckdb-\d/.test(f));
const platform = tarballs.find(f => f.startsWith(`potluckdb-${target}-`));
if (!main || !platform) {
	console.error(`${dist} needs potluckdb-<version>.tgz and potluckdb-${target}-<version>.tgz (scripts/package.js --pack)`);
	process.exit(1);
}

const project = fs.mkdtempSync(path.join(os.tmpdir(), 'potluckdb-quickstart-'));
try {
	fs.writeFileSync(path.join(project, 'package.json'), '{ "private": true }\n');
	const files = [main, platform].map(f => JSON.stringify(path.join(dist, f))).join(' ');
	console.log(`npm install ${main} ${platform} (npm ${execSync('npm --version', { encoding: 'utf8' }).trim()})`);
	execSync(`npm install --no-audit --no-fund ${files}`, { cwd: project, stdio: 'inherit' });
	for (const file of ['quickstart.cjs', 'quickstart.mjs']) {
		fs.copyFileSync(path.join(__dirname, file), path.join(project, file));
		console.log(`node ${file} (Node.js ${process.version})`);
		execFileSync(process.execPath, [file], { cwd: project, stdio: 'inherit' });
	}
	console.log('quickstart ok');
} finally {
	fs.rmSync(project, { recursive: true, force: true });
}
