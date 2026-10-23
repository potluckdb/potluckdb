"""Builds potluckdb._sqlite3: the vendored pysqlite3 sources, linked statically
with PotluckDB's own SQLite build from the core archive (see core_archive.py).
"""
import os
import pathlib
import sys

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import core_archive  # noqa: E402

BUILD = HERE / "build"
SOURCES = sorted(p.name for p in (HERE / "vendor/pysqlite3/src").glob("*.c"))

# The licence texts in licenses/ ship in the wheel; each must match the archive's.
LICENSE_COPIES = {"license": "LICENSE-potluckdb-binary.txt", "notices": "THIRD_PARTY_NOTICES.txt"}


def c_string(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def core_or_exit():
    try:
        return core_archive.locate(BUILD)
    except core_archive.CoreError as error:
        sys.exit(f"\npotluckdb: cannot build without the PotluckDB core library.\n{error}\n")


def sync_licences(core):
    """The wheel ships the core archive's licence and notices: copy them over
    ours when the core's changed (before the wheel collects license files)."""
    for key, name in LICENSE_COPIES.items():
        ours = HERE / "licenses" / name
        theirs = core[key].read_bytes().replace(b"\r\n", b"\n")
        if ours.read_bytes().replace(b"\r\n", b"\n") != theirs:
            ours.write_bytes(theirs)
            print(f"potluckdb: licenses/{name} updated from {core['root'].name}")


class BuildExt(build_ext):
    """Finds the core only when the extension is actually built (not for sdist/egg_info)."""

    def build_extensions(self):
        core = core_or_exit()
        sync_licences(core)
        print(f"potluckdb: linking PotluckDB {core['potluckdb_version']} "
              f"(SQLite {core['sqlite_version']}, {core['target']}) from {core['root']}")
        windows = core["target"].startswith("windows-")
        for ext in self.extensions:
            ext.include_dirs.append(str(core["include"]))
            ext.define_macros += [
                ("MODULE_NAME", c_string("potluckdb")),
                ("POTLUCKDB_PACKAGE_VERSION", c_string(package_version(core))),
                ("POTLUCKDB_EXPECTED_SQLITE_VERSION", c_string(core["sqlite_version"])),
            ]
            ext.extra_objects.append(str(core["static_lib"]))
            if windows:
                ext.extra_compile_args += ["/utf-8"]
            else:
                # Only PyInit__sqlite3 is exported; the archive's symbols are hidden already.
                ext.extra_compile_args += ["-fvisibility=hidden"]
            if core["target"].startswith("linux-"):
                ext.libraries += ["pthread", "dl", "m"]
                ext.extra_link_args += ["-Wl,--exclude-libs,ALL"]
        super().build_extensions()


def single_arch_on_universal_python():
    """The library is built per architecture. With a universal2 Python (such
    as python.org's macOS installers) build for this machine only, and tag
    the wheel accordingly, unless ARCHFLAGS or _PYTHON_HOST_PLATFORM say
    otherwise (cibuildwheel sets both)."""
    import sysconfig
    import platform
    plat = sysconfig.get_platform()
    if (plat.startswith("macosx-") and plat.endswith("-universal2")
            and not os.environ.get("ARCHFLAGS") and not os.environ.get("_PYTHON_HOST_PLATFORM")):
        arch = platform.machine()
        target = os.environ.get("MACOSX_DEPLOYMENT_TARGET", "11.0")
        os.environ["ARCHFLAGS"] = f"-arch {arch}"
        os.environ["_PYTHON_HOST_PLATFORM"] = f"macosx-{target}-{arch}"


single_arch_on_universal_python()


def package_version(core=None):
    if os.environ.get("POTLUCKDB_PACKAGE_VERSION"):
        return os.environ["POTLUCKDB_PACKAGE_VERSION"]
    if core is None:
        # Metadata only (sdist, egg_info): the version of the core that will be linked.
        directory = os.environ.get("POTLUCKDB_CORE_DIR")
        if directory:
            core = core_or_exit()
        else:
            return core_archive.pep440(core_archive.default_version())
    return core_archive.pep440(core["potluckdb_version"])


setup(
    version=package_version(),
    ext_modules=[Extension(
        "potluckdb._sqlite3",
        sources=[f"vendor/pysqlite3/src/{name}" for name in SOURCES],
        depends=[str(p.relative_to(HERE)) for p in (HERE / "vendor/pysqlite3/src").glob("*.h")],
    )],
    cmdclass={"build_ext": BuildExt},
)
