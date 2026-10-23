"""Release check for one core archive: unpack it, load the library and run
a query through SQLite's C API, check the frozen math vectors give exactly
the recorded bits (tests/vectors), then check an existing program (Python's
own sqlite3 module) uses it in place of its usual SQLite where it can.

Usage: python tests/release/smoke.py <archive> <expected version>

Runs on Python 3.6 and newer, so it also runs in the oldest Linux images
the library supports.
"""
import ctypes
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

MATH_VECTORS = pathlib.Path(__file__).resolve().parent.parent / "vectors" / "check_math.py"

PROBE = """
import sqlite3
db = sqlite3.connect(":memory:")
print(db.execute("SELECT potluckdb_version()").fetchone()[0])
"""


def unpack(archive, into):
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(str(archive)) as z:
            z.extractall(str(into))
    else:
        with tarfile.open(str(archive)) as t:
            # The safe "data" filter, where this Python has it (3.12, and backports).
            options = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
            t.extractall(str(into), **options)
    (root,) = [p for p in into.iterdir() if p.is_dir()]
    return root


def library(root):
    system = platform.system()
    if system == "Windows":
        return root / "bin" / "sqlite3.dll"
    if system == "Darwin":
        return root / "lib" / "libsqlite3.0.dylib"
    return root / "lib" / "libsqlite3.so.0"


def query(path):
    """Opens a database through the C API and returns `SELECT potluckdb_version()`."""
    lib = ctypes.CDLL(str(path))
    lib.potluckdb_version.restype = ctypes.c_char_p
    lib.sqlite3_libversion.restype = ctypes.c_char_p
    db = ctypes.c_void_p()
    if lib.sqlite3_open(b":memory:", ctypes.byref(db)) != 0:
        sys.exit("sqlite3_open failed")
    stmt = ctypes.c_void_p()
    sql = b"SELECT potluckdb_version() || ' on ' || sqlite_version()"
    if lib.sqlite3_prepare_v2(db, sql, -1, ctypes.byref(stmt), None) != 0 or lib.sqlite3_step(stmt) != 100:
        sys.exit("query failed")
    lib.sqlite3_column_text.restype = ctypes.c_char_p
    answer = lib.sqlite3_column_text(stmt, 0).decode()
    lib.sqlite3_finalize(stmt)
    lib.sqlite3_close(db)
    return lib.potluckdb_version().decode(), lib.sqlite3_libversion().decode(), answer


def stdlib_dropin(path):
    """The version Python's sqlite3 module reports when pointed at the library,
    or None where this Python builds SQLite in and can't be pointed elsewhere."""
    env = dict(os.environ)
    system = platform.system()
    with tempfile.TemporaryDirectory() as tmp:
        code = PROBE
        if system == "Windows":
            # Python loads sqlite3.dll from its _sqlite3 module's folder.
            shutil.copy(str(pathlib.Path(sys.base_prefix) / "DLLs" / "_sqlite3.pyd"), tmp)
            shutil.copy(str(path), tmp)
            code = "import sys; sys.path.insert(0, %r)\n" % tmp + PROBE
        else:
            name = "DYLD_LIBRARY_PATH" if system == "Darwin" else "LD_LIBRARY_PATH"
            env[name] = str(path.parent)
        pythons = [sys.executable]
        if system == "Darwin":
            pythons = [p for p in ("/opt/homebrew/bin/python3", "/usr/local/bin/python3") if os.path.exists(p)]
        for python in pythons:
            result = subprocess.run([python, "-c", code], env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, universal_newlines=True)
            if result.returncode == 0:
                return result.stdout.strip()
    return None


def query_in_child(path):
    """query(), in a child process, so the library is unloaded again (Windows
    can't delete a loaded DLL)."""
    result = subprocess.run([sys.executable, __file__, "--query", str(path)], stdout=subprocess.PIPE,
                            universal_newlines=True, check=True)
    return result.stdout.strip().splitlines()


def main():
    if sys.argv[1] == "--query":
        print("\n".join(query(pathlib.Path(sys.argv[2]))))
        return
    archive, expected = pathlib.Path(sys.argv[1]).resolve(), sys.argv[2]
    with tempfile.TemporaryDirectory() as tmp:
        path = library(unpack(archive, pathlib.Path(tmp)))
        version, sqlite, answer = query_in_child(path)
        if version != expected:
            sys.exit("library reports %s, expected %s" % (version, expected))
        print("ok: %s runs a query: %s" % (path.name, answer))
        sys.stdout.flush()
        # In a child process too, so the library is unloaded again.
        if subprocess.run([sys.executable, str(MATH_VECTORS), str(path)]).returncode != 0:
            sys.exit("the math vectors differ: this platform computes different bits (PRD K1)")
        dropin = stdlib_dropin(path)
        if dropin is None:
            print("note: this Python can't load another SQLite; drop-in check skipped")
        elif dropin != expected:
            sys.exit("Python's sqlite3 reports %s, expected %s" % (dropin, expected))
        else:
            print("ok: Python's sqlite3 module runs on PotluckDB %s (SQLite %s)" % (dropin, sqlite))


if __name__ == "__main__":
    main()
