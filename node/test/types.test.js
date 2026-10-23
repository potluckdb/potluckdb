'use strict';
// Type-checks test/types/ with TypeScript: potluckdb's types from CommonJS and
// ES modules, and their compatibility with @types/better-sqlite3.
const path = require('path');
const { execFileSync } = require('child_process');
const { test } = require('node:test');

test('the TypeScript declarations type-check', () => {
	const tsc = require.resolve('typescript/bin/tsc');
	execFileSync(process.execPath, [tsc, '-p', path.join(__dirname, 'types')], { stdio: 'inherit' });
});
