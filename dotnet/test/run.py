"""Runs the tests against the packages in artifacts/packages (scripts/pack.py),
on this machine's platform:

1. PotluckDB.Tests: each scenario in its own process (see its Program.cs), on
   every .NET installed of 8 and 10. On Linux, `api` runs once more with the
   system's libsqlite3 preloaded, so that its functions come first in the
   process's symbol lookup.
2. Microsoft.Data.Sqlite.Tests: Microsoft.Data.Sqlite's own test suite. Tests
   listed in its known-failures.json may fail, each for the reason given
   there. Any other failure fails the run, and so does a listed test that
   passes now (then remove it from the list).

Usage: python3 test/run.py [--target <target>]
The versions to expect come from artifacts/native/<rid>/BUILD-INFO.json.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))
from targets import TARGETS, current_target  # noqa: E402

DOTNET = os.environ.get("DOTNET", "dotnet")
SCENARIOS = ["api", "freeze", "e_sqlite3-first", "e_sqlite3-after", "system-first", "system-after"]
SYSTEM_SQLITE = ["/usr/lib/x86_64-linux-gnu/libsqlite3.so.0", "/usr/lib/aarch64-linux-gnu/libsqlite3.so.0",
                 "/usr/lib64/libsqlite3.so.0", "/usr/lib/libsqlite3.so.0"]


def run(command, env=None, cwd=None):
    print(f"$ {' '.join(str(c) for c in command)}", flush=True)
    subprocess.run(command, check=True, cwd=cwd, env=None if env is None else {**os.environ, **env})


def frameworks():
    out = subprocess.run([DOTNET, "--list-runtimes"], capture_output=True, text=True, check=True).stdout
    majors = {line.split()[1].split(".")[0] for line in out.splitlines() if line.startswith("Microsoft.NETCore.App ")}
    found = [f"net{m}.0" for m in ("10", "8") if m in majors]
    for missing in sorted({"net10.0", "net8.0"} - set(found)):
        print(f"skipped: {missing}, which is not installed")
    return found


def own_tests(target, version, sqlite_version):
    project = HERE / "PotluckDB.Tests"
    for framework in frameworks():
        run([DOTNET, "build", str(project), "-c", "Release", "-f", framework, "--nologo", "-v", "quiet"])
        dll = project / "bin" / "Release" / framework / "PotluckDB.Tests.dll"
        for scenario in SCENARIOS:
            run([DOTNET, str(dll), scenario, version, sqlite_version])
        if TARGETS[target]["os"] == "linux":
            system = next((p for p in SYSTEM_SQLITE if os.path.exists(p)), None)
            if not system:
                raise SystemExit(f"no system libsqlite3.so.0 in {', '.join(SYSTEM_SQLITE)}; install it (Alpine: apk add sqlite-libs)")
            run([DOTNET, str(dll), "api", version, sqlite_version], env={"LD_PRELOAD": system})


def microsoft_data_sqlite_tests(target):
    project = HERE / "Microsoft.Data.Sqlite.Tests"
    known = json.loads((project / "known-failures.json").read_text(encoding="utf-8"))
    expected = {f["test"]: f["reason"] for f in known["failures"]
                if not f.get("platforms") or target in f["platforms"]}
    results_dir = ROOT / "artifacts" / "test-results"
    shutil.rmtree(results_dir, ignore_errors=True)
    command = [DOTNET, "test", str(project), "-c", "Release", "--nologo", "--logger", "trx;LogFileName=mds.trx",
               "--results-directory", str(results_dir)]
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command)  # failures are judged below, against the known ones
    trx = results_dir / "mds.trx"
    if not trx.exists():
        raise SystemExit("Microsoft.Data.Sqlite.Tests: no results; the tests didn't build or run")
    ns = {"t": "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"}
    results = [(r.get("testName"), r.get("outcome")) for r in ET.parse(trx).getroot().iterfind(".//t:UnitTestResult", ns)]
    failed = sorted({name for name, outcome in results if outcome == "Failed"})
    passed = sum(1 for _, outcome in results if outcome == "Passed")
    skipped = sum(1 for _, outcome in results if outcome == "NotExecuted")
    unexpected = [name for name in failed if name not in expected]
    fixed = [name for name in expected if name not in failed and any(n == name for n, _ in results)]
    ran = len(results) - skipped
    print(f"Microsoft.Data.Sqlite {known['efcore']} test suite on PotluckDB ({target}):")
    print(f"  {passed} of {ran} tests pass ({100 * passed / max(ran, 1):.1f}%); {skipped} skipped by the suite itself")
    print(f"  {len(failed)} failures, {len(failed) - len(unexpected)} of them known (see known-failures.json)")
    for name in failed:
        if name in expected:
            print(f"    known: {name}")
    for name in unexpected:
        print(f"NEW FAILURE: {name}")
    for name in fixed:
        print(f"NOW PASSES (remove it from known-failures.json): {name}")
    if unexpected or fixed or not passed:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--target", default=current_target(), choices=TARGETS)
    args = parser.parse_args()
    info = json.loads((ROOT / "artifacts" / "native" / TARGETS[args.target]["rid"] / "BUILD-INFO.json").read_text(encoding="utf-8"))
    # The packages are rebuilt with the same version: drop the copies restored before.
    for name in ("potluckdb.sqlitepclraw", "potluckdb.data.sqlite"):
        shutil.rmtree(ROOT / "artifacts" / "test-packages" / name, ignore_errors=True)
    for obj in HERE.glob("*/obj"):
        shutil.rmtree(obj)
    own_tests(args.target, info["potluckdb_version"], info["sqlite_version"])
    microsoft_data_sqlite_tests(args.target)
    print("tests ok")


if __name__ == "__main__":
    main()
