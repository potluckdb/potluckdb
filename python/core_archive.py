"""Find, download and unpack the PotluckDB core archive the extension links.

The Python package links PotluckDB's own SQLite build statically. Each core
release on GitHub carries one archive per platform:

    potluckdb-sqlite-<version>-<target>.tar.gz   (Linux, macOS)
    potluckdb-sqlite-<version>-<target>.zip      (Windows)

Where the archive comes from:

    POTLUCKDB_CORE_DIR=<dir>   a directory holding archives (the build picks the
                               one for this platform), or an unpacked archive;
                               a relative path is relative to this directory
    otherwise                  the release for POTLUCKDB_CORE_VERSION (default:
                               the CORE_VERSION file) is downloaded from GitHub and
                               checked against the release's SHA256SUMS

POTLUCKDB_CORE_TARGET overrides the platform (e.g. linux-arm64-musl).

Command line (used by CI):

    python core_archive.py target
    python core_archive.py release-exists [--version V]   exit 0 if the release has
                                                          every platform's archive
"""
import argparse
import hashlib
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import urllib.error
import urllib.request
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = "potluckdb/potluckdb"
TARGETS = [
    "linux-x64-gnu", "linux-arm64-gnu", "linux-x64-musl", "linux-arm64-musl",
    "macos-arm64", "macos-x64", "windows-x64", "windows-arm64",
]


class CoreError(Exception):
    """The core archive is missing or wrong; the message says what to do."""


def default_version():
    return (os.environ.get("POTLUCKDB_CORE_VERSION")
            or (HERE / "CORE_VERSION").read_text(encoding="utf-8").strip())


def host_target():
    """The core target for the platform being built for."""
    if os.environ.get("POTLUCKDB_CORE_TARGET"):
        return os.environ["POTLUCKDB_CORE_TARGET"]
    plat = sysconfig.get_platform()  # honours _PYTHON_HOST_PLATFORM (cross-compiling)
    if plat.startswith("macosx-"):
        arch = plat.rsplit("-", 1)[1]
        archs = os.environ.get("ARCHFLAGS", "").split()[1::2]
        if len(archs) == 1:
            arch = archs[0]
        elif arch in ("universal2", "intel", "fat", "fat3", "fat64", "universal"):
            arch = platform.machine()  # see setup.py: one architecture per build
        return {"arm64": "macos-arm64", "x86_64": "macos-x64"}.get(arch) or _unsupported(plat)
    if plat.startswith("win"):
        return {"win-amd64": "windows-x64", "win-arm64": "windows-arm64"}.get(plat) or _unsupported(plat)
    if plat.startswith("linux-"):
        arch = {"x86_64": "x64", "aarch64": "arm64"}.get(plat.split("-", 1)[1]) or _unsupported(plat)
        return f"linux-{arch}-{'musl' if _is_musl() else 'gnu'}"
    _unsupported(plat)


def _unsupported(plat):
    raise CoreError(
        f"PotluckDB has no build for this platform ({plat}). Supported: {', '.join(TARGETS)}.")


def _is_musl():
    if "musl" in (sysconfig.get_config_var("HOST_GNU_TYPE") or ""):
        return True
    if platform.libc_ver()[0] == "glibc":
        return False
    try:
        out = subprocess.run(["ldd", "--version"], capture_output=True, text=True)
        return "musl" in (out.stdout + out.stderr).lower()
    except OSError:
        return False


def archive_name(version, target):
    ext = "zip" if target.startswith("windows-") else "tar.gz"
    return f"potluckdb-sqlite-{version}-{target}.{ext}"


def release_url(version, name):
    return f"https://github.com/{REPO}/releases/download/v{version}/{name}"


def _download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "potluckdb-python-build"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def _find_in_dir(directory, target, version):
    """An archive (or an unpacked archive) for target in directory."""
    if (directory / "include" / "sqlite3.h").exists():
        return directory  # already unpacked
    suffix = archive_name("V", target).split("-V-", 1)[1]
    found = sorted(p for p in directory.glob(f"potluckdb-sqlite-*-{suffix}")
                   if version is None or p.name == archive_name(version, target))
    if not found:
        want = archive_name(version or "<version>", target)
        raise CoreError(f"POTLUCKDB_CORE_DIR={directory} has no {want}.")
    if len(found) > 1:
        raise CoreError(f"POTLUCKDB_CORE_DIR={directory} has several archives for {target} "
                        f"({', '.join(p.name for p in found)}); set POTLUCKDB_CORE_VERSION to pick one.")
    return found[0]


def _fetch_release(version, target, cache):
    name = archive_name(version, target)
    path = cache / name
    if path.exists():
        return path
    try:
        sums = _download(release_url(version, "SHA256SUMS")).decode()
        data = _download(release_url(version, name))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise CoreError(
                f"PotluckDB core {version} is not released on GitHub (no {name} at "
                f"https://github.com/{REPO}/releases/tag/v{version}). Set POTLUCKDB_CORE_DIR to a "
                f"directory holding the archive, or POTLUCKDB_CORE_VERSION to a released version.")
        raise CoreError(f"downloading {name}: {error}")
    except urllib.error.URLError as error:
        raise CoreError(f"downloading {name}: {error.reason}. Set POTLUCKDB_CORE_DIR to build offline.")
    expected = next((line.split()[0] for line in sums.splitlines()
                     if line.split()[-1:] == [name] or line.split()[-1:] == ["*" + name]), None)
    actual = hashlib.sha256(data).hexdigest()
    if expected != actual:
        raise CoreError(f"{name}: sha256 {actual} does not match the release's SHA256SUMS ({expected}).")
    cache.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _unpack(archive, dest):
    """Unpacks archive into dest/<archive stem>/ and returns that directory."""
    stem = archive.name.removesuffix(".tar.gz").removesuffix(".zip")
    out = dest / stem
    stamp = out / ".unpacked-sha256"
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if stamp.exists() and stamp.read_text() == digest:
        return out
    shutil.rmtree(out, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                _check_member(member, stem)
            zf.extractall(dest)
    else:
        with tarfile.open(archive) as tf:
            members = [m for m in tf.getmembers() if not (m.issym() or m.islnk())]  # only the .so symlink
            for member in members:
                _check_member(member.name, stem)
            tf.extractall(dest, members=members, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
    stamp.write_text(digest)
    return out


def _check_member(name, stem):
    parts = pathlib.PurePosixPath(name).parts
    if not parts or parts[0] != stem or ".." in parts or name.startswith("/"):
        raise CoreError(f"unexpected path in core archive: {name}")


def locate(build_dir):
    """Returns a dict describing the unpacked core for this platform.

    Keys: root, include, static_lib, license, notices, potluckdb_version,
    sqlite_version, target.
    """
    target = host_target()
    version = os.environ.get("POTLUCKDB_CORE_VERSION")
    core_dir = os.environ.get("POTLUCKDB_CORE_DIR")
    if core_dir:
        # A relative path is relative to this directory (python/), wherever
        # the build runs (cibuildwheel's Linux containers see it as /project).
        found = _find_in_dir((HERE / core_dir).resolve(), target, version)
        root = found if found.is_dir() else _unpack(found, build_dir / "core")
    else:
        version = default_version()
        root = _unpack(_fetch_release(version, target, build_dir / "core-download"), build_dir / "core")
    info_path = root / "BUILD-INFO.json"
    if not info_path.exists():
        raise CoreError(f"{root} is not a PotluckDB core archive (no BUILD-INFO.json).")
    info = json.loads(info_path.read_text(encoding="utf-8"))
    if info.get("target") != target:
        raise CoreError(f"{root} is for {info.get('target')}, but this build is for {target}.")
    if version and info.get("potluckdb_version") != version:
        raise CoreError(f"{root} is PotluckDB {info.get('potluckdb_version')}, expected {version}.")
    static = root / "lib" / "static" / ("sqlite3.lib" if target.startswith("windows-") else "libsqlite3.a")
    for needed in (root / "include" / "sqlite3.h", root / "include" / "potluckdb.h", static,
                   root / "LICENSE.txt", root / "THIRD_PARTY_NOTICES.txt"):
        if not needed.exists():
            raise CoreError(f"core archive {root.name} lacks {needed.relative_to(root)}.")
    return {
        "root": root,
        "include": root / "include",
        "static_lib": static,
        "license": root / "LICENSE.txt",
        "notices": root / "THIRD_PARTY_NOTICES.txt",
        "potluckdb_version": info["potluckdb_version"],
        "sqlite_version": info["sqlite_version"],
        "target": target,
    }


def pep440(version):
    """PotluckDB's version (0.8.0-dev.1, 0.8.0-rc.2, 0.8.0) as a Python version."""
    base, _, pre = version.partition("-")
    if not pre:
        return base
    kind, _, number = pre.partition(".")
    mark = {"dev": ".dev", "alpha": "a", "beta": "b", "rc": "rc"}.get(kind)
    if mark is None or not number.isdigit():
        raise CoreError(f"cannot turn PotluckDB version {version!r} into a Python version")
    return f"{base}{mark}{number}"


def release_exists(version):
    """True if the GitHub release v<version> has the archive for every target."""
    missing = []
    for target in TARGETS:
        request = urllib.request.Request(release_url(version, archive_name(version, target)), method="HEAD",
                                         headers={"User-Agent": "potluckdb-python-build"})
        try:
            urllib.request.urlopen(request, timeout=60).close()
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            missing.append(target)
    return missing


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("target", help="print the core target for this platform")
    check = sub.add_parser("release-exists", help="exit 0 if the core release has every archive")
    check.add_argument("--version", default=None)
    sub.add_parser("version", help="print the default core version")
    args = parser.parse_args(argv)
    try:
        if args.command == "target":
            print(host_target())
        elif args.command == "version":
            print(default_version())
        else:
            version = args.version or default_version()
            missing = release_exists(version)
            if missing:
                print(f"PotluckDB core {version} is not released (missing: {', '.join(missing)})")
                return 1
            print(f"PotluckDB core {version} is released for every platform")
    except CoreError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
