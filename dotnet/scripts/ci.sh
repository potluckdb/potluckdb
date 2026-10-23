#!/bin/sh
# The CI steps for one platform, run from dotnet/: make the packages from the
# native libraries in artifacts/native/ (those of every platform the run
# built), then run the tests and the quickstart apps on this platform. Runs on
# the CI machine itself or in an Alpine container. Needs VERSION (the
# PotluckDB version) and TARGET (this platform, e.g. linux-x64-gnu).
set -eu
PYTHON=${PYTHON:-python3}
"$PYTHON" scripts/pack.py --version "$VERSION"
"$PYTHON" test/run.py --target "$TARGET"
"$PYTHON" test/quickstart/run.py --target "$TARGET"
