"""Builds and runs small apps that use the packages in artifacts/packages the
way the README says, each printing "<potluckdb_version()> <sqlite_version()>":

  MdsApp           Microsoft.Data.Sqlite (the README's quickstart), on .NET 10 and 8;
                   also published self-contained, and as a single file
  DapperApp        Dapper on Microsoft.Data.Sqlite
  EfCoreApp        EF Core (Microsoft.EntityFrameworkCore.Sqlite.Core)
  SqliteNetApp     sqlite-net-base, with SQLitePCL.Batteries_V2.Init()
  SqliteNetPclApp  sqlite-net-pcl, with SQLitePCL.Batteries_V2.Init() first
  ConflictApp      Microsoft.Data.Sqlite and PotluckDB together: must not build

Usage: python3 test/quickstart/run.py [--target <target>] [--publish <dir>]
--publish only publishes MdsApp, self-contained for the target, into <dir>
(for running it on another system, such as the oldest supported glibc).
The versions come from artifacts/native/<rid>/BUILD-INFO.json.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from targets import TARGETS, current_target  # noqa: E402

DOTNET = os.environ.get("DOTNET", "dotnet")


def dotnet(*args, cwd, check=True):
    result = subprocess.run([DOTNET, *args, "--nologo"], cwd=cwd, capture_output=True, text=True)
    if check and result.returncode:
        print(result.stdout, result.stderr, sep="\n")
        raise SystemExit(f"dotnet {' '.join(args)} failed in {cwd.name}")
    return result


def runtimes():
    out = subprocess.run([DOTNET, "--list-runtimes"], capture_output=True, text=True, check=True).stdout
    return {line.split()[1].split(".")[0] for line in out.splitlines() if line.startswith("Microsoft.NETCore.App ")}


def expect(command, expected, label, cwd=None):
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(command, cwd=cwd or tmp, capture_output=True, text=True)
    output = result.stdout.strip()
    if result.returncode or output != expected:
        print(result.stdout, result.stderr, sep="\n")
        raise SystemExit(f"{label}: expected '{expected}', got '{output}' (exit {result.returncode})")
    print(f"ok: {label}: {output}")


def build_and_run(app, version, expected, framework="net10.0", extra=()):
    project = HERE / app
    result = dotnet("build", "-c", "Release", "-f", framework, f"-p:PotluckDBVersion={version}", *extra, cwd=project)
    expect([DOTNET, str(project / "bin" / "Release" / framework / f"{app}.dll")], expected, f"{app} ({framework})")
    return result


def publish(version, rid, out, single_file=False):
    args = ["publish", "-c", "Release", "-f", "net10.0", "-r", rid, "--self-contained", "-o", str(out),
            f"-p:PotluckDBVersion={version}", "-p:InvariantGlobalization=true"]
    if single_file:
        args += ["-p:PublishSingleFile=true", "-p:IncludeNativeLibrariesForSelfExtract=true"]
    dotnet(*args, cwd=HERE / "MdsApp")
    return out / ("MdsApp.exe" if rid.startswith("win") else "MdsApp")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--target", default=current_target(), choices=TARGETS)
    parser.add_argument("--publish", metavar="DIR")
    args = parser.parse_args()
    rid = TARGETS[args.target]["rid"]
    info = json.loads((ROOT / "artifacts" / "native" / rid / "BUILD-INFO.json").read_text(encoding="utf-8"))
    args.version, args.sqlite_version = info["potluckdb_version"], info["sqlite_version"]

    # The packages are rebuilt with the same version: drop the copies restored before.
    packages = ROOT / "artifacts" / "test-packages"
    for name in ("potluckdb.sqlitepclraw", "potluckdb.data.sqlite"):
        shutil.rmtree(packages / name, ignore_errors=True)
    for obj in HERE.glob("*/obj"):
        shutil.rmtree(obj)

    if args.publish:
        print(publish(args.version, rid, Path(args.publish).resolve()))
        return
    expected = f"{args.version} {args.sqlite_version}"

    build_and_run("MdsApp", args.version, expected)
    if "8" in runtimes():
        build_and_run("MdsApp", args.version, expected, framework="net8.0")
    else:
        print("skipped: MdsApp on .NET 8, which is not installed")
    with tempfile.TemporaryDirectory() as tmp:
        expect([str(publish(args.version, rid, Path(tmp) / "self-contained"))], expected, f"MdsApp, self-contained for {rid}")
        expect([str(publish(args.version, rid, Path(tmp) / "single-file", single_file=True))], expected, f"MdsApp, single file for {rid}")
    build_and_run("DapperApp", args.version, expected)
    build_and_run("EfCoreApp", args.version, expected)
    build_and_run("SqliteNetApp", args.version, expected)

    # sqlite-net-pcl: the build warns (POTLUCKDB002) unless the project silences it.
    result = build_and_run("SqliteNetPclApp", args.version, expected)
    if "POTLUCKDB002" in result.stdout:
        raise SystemExit("SqliteNetPclApp: POTLUCKDB002 shows although NoWarn has it")
    result = dotnet("build", "-c", "Release", f"-p:PotluckDBVersion={args.version}", "-p:NoWarn=", "--no-incremental",
                    cwd=HERE / "SqliteNetPclApp")
    if "warning POTLUCKDB002" not in result.stdout:
        print(result.stdout)
        raise SystemExit("SqliteNetPclApp: no warning POTLUCKDB002 without NoWarn")
    print("ok: SqliteNetPclApp: warns POTLUCKDB002 unless silenced")

    result = dotnet("build", "-c", "Release", f"-p:PotluckDBVersion={args.version}", cwd=HERE / "ConflictApp", check=False)
    if result.returncode == 0 or "error POTLUCKDB001" not in result.stdout:
        print(result.stdout)
        raise SystemExit("ConflictApp: expected the build to fail with POTLUCKDB001")
    print("ok: ConflictApp: Microsoft.Data.Sqlite with PotluckDB.Data.Sqlite fails to build (POTLUCKDB001)")
    print("quickstart ok")


if __name__ == "__main__":
    main()
