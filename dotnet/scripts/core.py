"""Finds the PotluckDB core archive for a target and unpacks it. The native
library in the NuGet package is made from it (see native.py).

Where the archive comes from:
- POTLUCKDB_CORE_DIR: a folder holding the archives
  (potluckdb-sqlite-<version>-<target>.tar.gz or .zip, checked against
  SHA256SUMS if the folder has one), or one unpacked archive;
- otherwise the GitHub release v<version> of potluckdb/potluckdb, checked
  against the release's SHA256SUMS.

Usage: python3 scripts/core.py <target> [<version>]   (prints the unpacked folder)
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from targets import archive_name  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RELEASES = "https://github.com/potluckdb/potluckdb/releases/download"
CACHE = ROOT / "artifacts" / "core"


def default_version():
    """POTLUCKDB_VERSION, or the version in Directory.Build.props."""
    if os.environ.get("POTLUCKDB_VERSION"):
        return os.environ["POTLUCKDB_VERSION"]
    props = (ROOT / "Directory.Build.props").read_text(encoding="utf-8")
    return re.search(r"<PotluckDBVersion\b[^>]*>([^<]+)</PotluckDBVersion>", props).group(1).strip()


def verify(data, file, sums, where):
    """Fails unless the file's SHA-256 is the one SHA256SUMS lists for it."""
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == file:
            if hashlib.sha256(data).hexdigest() != parts[0]:
                raise SystemExit(f"{file} does not match SHA256SUMS of {where}")
            return
    raise SystemExit(f"SHA256SUMS of {where} does not list {file}")


def download(url):
    with urllib.request.urlopen(url) as response:
        return response.read()


def fetch(version, file):
    destination = CACHE / "downloads" / file
    if destination.exists():
        return destination
    base = f"{RELEASES}/v{version}"
    print(f"downloading {base}/{file}", file=sys.stderr)
    try:
        data, sums = download(f"{base}/{file}"), download(f"{base}/SHA256SUMS")
    except OSError as err:
        raise SystemExit(f"can't download {base}/{file} ({err}); set POTLUCKDB_CORE_DIR to a folder with the core archives")
    verify(data, file, sums.decode("utf-8"), f"v{version}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return destination


def extract(archive, out_dir):
    name = archive.name.removesuffix(".tar.gz").removesuffix(".zip")
    shutil.rmtree(out_dir / name, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(out_dir)
    elif os.name == "nt":
        # The Linux and macOS archives hold symbolic links (libsqlite3.so ->
        # libsqlite3.so.0), which Windows can't always create; skip them.
        with tarfile.open(archive) as t:
            members = [m for m in t.getmembers() if not m.issym()]
            if hasattr(tarfile, "data_filter"):
                t.extractall(out_dir, members=members, filter="data")
            else:
                t.extractall(out_dir, members=members)
    else:
        # tar keeps the permissions and links as they are in the archive.
        subprocess.run(["tar", "-xzf", str(archive), "-C", str(out_dir)], check=True)
    return out_dir / name


def check(directory, version, target):
    info = json.loads((directory / "BUILD-INFO.json").read_text(encoding="utf-8"))
    if info["target"] != target or info["potluckdb_version"] != version:
        raise SystemExit(f"{directory} holds {info['target']} {info['potluckdb_version']}, not {target} {version}")
    return directory


def get_core(target, version=None, core_dir=None):
    """Returns the folder of the unpacked core archive for the target."""
    version = version or default_version()
    core_dir = core_dir if core_dir is not None else os.environ.get("POTLUCKDB_CORE_DIR")
    file = archive_name(version, target)
    name = file.removesuffix(".tar.gz").removesuffix(".zip")
    if core_dir:
        core_dir = Path(core_dir).resolve()
        for candidate in (core_dir, core_dir / name):
            if (candidate / "include" / "sqlite3.h").exists():
                return check(candidate, version, target)
        archive = core_dir / file
        if not archive.exists():
            raise SystemExit(f"POTLUCKDB_CORE_DIR={core_dir} has no {file}")
        if (core_dir / "SHA256SUMS").exists():
            verify(archive.read_bytes(), file, (core_dir / "SHA256SUMS").read_text(encoding="utf-8"), str(core_dir))
    else:
        archive = fetch(version, file)
    return check(extract(archive, CACHE / "unpacked"), version, target)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(get_core(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
