"""Makes the NuGet packages from the native libraries in artifacts/native/<rid>/
(from scripts/native.py):

  artifacts/packages/PotluckDB.SQLitePCLRaw.<version>.nupkg  the bundle, with the native library for each platform
  artifacts/packages/PotluckDB.Data.Sqlite.<version>.nupkg   Microsoft.Data.Sqlite.Core plus the bundle

Each native library must come from the core of that version. --all fails
unless there is one for every platform (for publishing).

Usage: python3 scripts/pack.py [--version <version>] [--all]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import ROOT, default_version  # noqa: E402
from targets import TARGETS, library_name  # noqa: E402

NATIVE = ROOT / "artifacts" / "native"
PACKAGES = ROOT / "artifacts" / "packages"
LICENSE = ROOT / "artifacts" / "license" / "LICENSE.txt"


def natives(version, require_all):
    found = {}
    for target, t in TARGETS.items():
        directory = NATIVE / t["rid"]
        if not (directory / library_name(target)).exists():
            continue
        info = json.loads((directory / "BUILD-INFO.json").read_text(encoding="utf-8"))
        if info["target"] != target or info["potluckdb_version"] != version:
            raise SystemExit(f"{directory} was made from the {info['target']} core {info['potluckdb_version']}, not {target} {version}")
        found[target] = directory
    if not found:
        raise SystemExit(f"no native libraries in {NATIVE}: run scripts/native.py first")
    missing = [t for t in TARGETS if t not in found]
    if require_all and missing:
        raise SystemExit(f"no native library for {', '.join(missing)}")
    for directory in NATIVE.iterdir():
        if directory.is_dir() and directory.name not in {t["rid"] for t in TARGETS.values()}:
            raise SystemExit(f"{directory} is not a platform PotluckDB ships")
    return found


def write_license(directory):
    """The packages' licence file: what each part is licensed under, then the texts."""
    binary = (directory / "LICENSE.txt").read_text(encoding="utf-8").strip()
    notices = (directory / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8").strip()
    apache = (ROOT / "LICENSE").read_text(encoding="utf-8").strip()
    LICENSE.parent.mkdir(parents=True, exist_ok=True)
    LICENSE.write_text(f"""Licences of PotluckDB's .NET packages
=====================================

These packages (PotluckDB.SQLitePCLRaw and PotluckDB.Data.Sqlite) contain:

- PotluckDB's native library, runtimes/<platform>/native/*potluckdb_dotnet*:
  a build of the PotluckDB library, under the PotluckDB binary licence (1.
  below). It contains SQLite, which is in the public domain (2. below).
- The managed code, SQLitePCLRaw.batteries_v2.dll, from
  https://github.com/potluckdb/potluckdb/tree/main/dotnet: under the Apache
  License 2.0 (3. below).

The packages they depend on (SQLitePCLRaw, Microsoft.Data.Sqlite.Core) come
with their own licences.


1. PotluckDB binary licence
---------------------------

{binary}


2. SQLite
---------

{notices}


3. Apache License 2.0 (the managed code)
----------------------------------------

{apache}
""", encoding="utf-8", newline="\n")


def check_package(package, expected):
    with zipfile.ZipFile(package) as z:
        names = set(z.namelist())
    missing = [name for name in expected if name not in names]
    if missing:
        raise SystemExit(f"{package.name} lacks {', '.join(missing)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", default=None)
    parser.add_argument("--all", action="store_true", help="require a native library for every platform")
    args = parser.parse_args()
    version = args.version or default_version()
    found = natives(version, args.all)
    write_license(next(iter(found.values())))
    shutil.rmtree(PACKAGES, ignore_errors=True)
    dotnet = os.environ.get("DOTNET", "dotnet")
    for project in ("PotluckDB.SQLitePCLRaw", "PotluckDB.Data.Sqlite"):
        subprocess.run([dotnet, "pack", str(ROOT / "src" / project / f"{project}.csproj"), "-c", "Release",
                        "-o", str(PACKAGES), f"-p:PotluckDBVersion={version}", "--nologo"], check=True)
    bundle = PACKAGES / f"PotluckDB.SQLitePCLRaw.{version}.nupkg"
    check_package(bundle, ["LICENSE.txt", "README.md", "lib/net8.0/SQLitePCLRaw.batteries_v2.dll",
                           "buildTransitive/PotluckDB.SQLitePCLRaw.targets"]
                  + [f"runtimes/{TARGETS[t]['rid']}/native/{library_name(t)}" for t in found])
    check_package(PACKAGES / f"PotluckDB.Data.Sqlite.{version}.nupkg", ["LICENSE.txt", "README.md"])
    print(f"{PACKAGES}: PotluckDB.SQLitePCLRaw and PotluckDB.Data.Sqlite {version}, "
          f"with the native library for {', '.join(TARGETS[t]['rid'] for t in found)}")


if __name__ == "__main__":
    main()
