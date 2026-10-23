'use strict';
const fs = require('fs');
const path = require('path');
const { TARGETS, currentTarget } = require('./targets');

let DEFAULT_ADDON;

function getBinding(nativeBinding) {
	// If a path was provided, load the binding from the filesystem.
	if (typeof nativeBinding === 'string') {
		// See <https://webpack.js.org/api/module-variables/#__non_webpack_require__-webpack-specific>
		const requireFunc = typeof __non_webpack_require__ === 'function' ? __non_webpack_require__ : require;
		return requireFunc(path.resolve(nativeBinding).replace(/(\.node)?$/, '.node'));
	}

	// If an object was provided, use it as the binding directly.
	if (typeof nativeBinding === 'object' && nativeBinding !== null) {
		return nativeBinding;
	}

	// If we're using the default binding and it already exists, just return it.
	if (DEFAULT_ADDON) {
		return DEFAULT_ADDON;
	}

	// A local build (a development checkout; the published package has none).
	for (const configuration of ['Debug', 'Release']) {
		const filename = path.join(__dirname, '..', 'build', configuration, 'potluckdb.node');
		if (fs.existsSync(filename)) return DEFAULT_ADDON = require(filename);
	}

	// Otherwise, the platform package that npm installed with potluckdb.
	return DEFAULT_ADDON = require(getPlatformPackagePath());
}

function getPlatformPackagePath() {
	const target = currentTarget();
	if (!target) {
		throw new Error(`potluckdb has no build for ${process.platform}-${process.arch}. `
			+ `It runs on: ${Object.keys(TARGETS).join(', ')}.`);
	}
	const request = `@potluckdb/${target}/potluckdb.node`;
	try {
		return require.resolve(request);
	} catch (err) {
		if (err.code !== 'MODULE_NOT_FOUND') throw err;
		throw new Error(`potluckdb could not find its native library: the package @potluckdb/${target} is not installed. `
			+ 'npm installs it together with potluckdb unless optional dependencies are turned off '
			+ '(--omit=optional, --no-optional or a lockfile made on another platform). '
			+ 'Reinstall potluckdb with optional dependencies included.');
	}
}

exports.getBinding = getBinding;
exports.getPlatformPackagePath = getPlatformPackagePath;
