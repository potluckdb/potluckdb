#!/bin/sh
# The CI steps for one platform, run from node/: build the addon, check its
# exported symbols and system requirements, run the tests, then pack the npm
# packages and run the quickstart from them. Runs on the CI machine itself or
# in a manylinux or Alpine container. Needs VERSION (the PotluckDB version)
# and POTLUCKDB_CORE_DIR (a folder with its core archive for this platform).
set -eu
export POTLUCKDB_CORE_VERSION="$VERSION"

npm ci --no-audit --no-fund
node scripts/build.js
node scripts/check-binary.js
node test/run-better-sqlite3.js
node --test --test-reporter=spec test/*.test.js
node scripts/package.js --version "$VERSION" --pack --out dist
node test/quickstart/run.js dist
