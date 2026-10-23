"""The platforms PotluckDB ships, named like the core archives
(potluckdb-sqlite-<version>-<target>), with the .NET runtime identifier (RID)
that NuGet uses for each: the package holds the native library for a target
in runtimes/<rid>/native/.
"""
import platform
import sys

TARGETS = {
    "linux-x64-gnu": {"rid": "linux-x64", "os": "linux", "cpu": "x64", "libc": "glibc"},
    "linux-arm64-gnu": {"rid": "linux-arm64", "os": "linux", "cpu": "arm64", "libc": "glibc"},
    "linux-x64-musl": {"rid": "linux-musl-x64", "os": "linux", "cpu": "x64", "libc": "musl"},
    "linux-arm64-musl": {"rid": "linux-musl-arm64", "os": "linux", "cpu": "arm64", "libc": "musl"},
    "macos-arm64": {"rid": "osx-arm64", "os": "macos", "cpu": "arm64"},
    "macos-x64": {"rid": "osx-x64", "os": "macos", "cpu": "x64"},
    "windows-x64": {"rid": "win-x64", "os": "windows", "cpu": "x64"},
    "windows-arm64": {"rid": "win-arm64", "os": "windows", "cpu": "arm64"},
}

# The file name of the native library in the package. It is PotluckDB's own
# name, so it can't be mistaken for (or replace) e_sqlite3, sqlite3 or the
# system's libsqlite3 (see DESIGN.md).
LIBRARY = {"linux": "libpotluckdb_dotnet.so", "macos": "libpotluckdb_dotnet.dylib", "windows": "potluckdb_dotnet.dll"}


def library_name(target):
    return LIBRARY[TARGETS[target]["os"]]


def archive_name(version, target):
    if target not in TARGETS:
        raise SystemExit(f"unknown target {target}; known: {', '.join(TARGETS)}")
    extension = "zip" if TARGETS[target]["os"] == "windows" else "tar.gz"
    return f"potluckdb-sqlite-{version}-{target}.{extension}"


def current_target():
    """The target of this machine, or None if PotluckDB doesn't ship one."""
    machine = platform.machine().lower()
    cpu = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if sys.platform.startswith("linux"):
        libc = "glibc" if platform.libc_ver()[0] == "glibc" else "musl"
        os_name = "linux"
    elif sys.platform == "darwin":
        libc, os_name = None, "macos"
    elif sys.platform == "win32":
        libc, os_name = None, "windows"
    else:
        return None
    for name, t in TARGETS.items():
        if t["os"] == os_name and t["cpu"] == cpu and t.get("libc") == libc:
            return name
    return None
