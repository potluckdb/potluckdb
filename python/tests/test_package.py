"""Tests of the potluckdb package itself (CPython's sqlite3 suite is run by
run_cpython_tests.py).

    python tests/test_package.py [-v]

Environment, all optional:
    POTLUCKDB_EXPECT_CORE_VERSION    the PotluckDB version the build must report
    POTLUCKDB_EXPECT_SQLITE_VERSION  the SQLite version the build must report
"""
import contextlib
import io
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

import potluckdb

README = pathlib.Path(__file__).resolve().parent.parent / "README.md"


def run_python(code):
    """Runs code in a fresh interpreter (same potluckdb) and returns stdout."""
    env = dict(os.environ)
    parent = str(pathlib.Path(potluckdb.__file__).resolve().parent.parent)
    env["PYTHONPATH"] = os.pathsep.join([parent] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
    result = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], env=env,
                            capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise AssertionError(f"subprocess failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout


class QuickstartTests(unittest.TestCase):
    def test_readme_quickstart_runs(self):
        text = README.read_text(encoding="utf-8")
        blocks = re.findall(r"```python\n(.*?)```", text, re.S)
        self.assertTrue(blocks, "README.md has no python example")
        with tempfile.TemporaryDirectory() as tmp, _chdir(tmp):
            out = io.StringIO()
            namespace = {"__name__": "__readme__"}
            try:
                with contextlib.redirect_stdout(out):
                    exec(compile(blocks[0], str(README), "exec"), namespace)
                self.assertTrue(os.path.exists("app.db"))
            finally:
                for value in namespace.values():
                    if isinstance(value, potluckdb.Connection):
                        value.close()
        printed = out.getvalue().strip()
        self.assertEqual(printed, repr((potluckdb.core_version, potluckdb.sqlite_version)))

    def test_versions(self):
        db = potluckdb.connect(":memory:")
        try:
            core, sqlite = db.execute("select potluckdb_version(), sqlite_version()").fetchone()
        finally:
            db.close()
        self.assertEqual(core, potluckdb.core_version)
        self.assertEqual(sqlite, potluckdb.sqlite_version)
        self.assertRegex(potluckdb.core_version, r"^\d+\.\d+\.\d+(-(dev|rc|alpha|beta)\.\d+)?$")
        self.assertRegex(potluckdb.__version__, r"^\d+\.\d+\.\d+((\.dev|rc|a|b)\d+)?(\.post\d+)?$")
        if os.environ.get("POTLUCKDB_EXPECT_CORE_VERSION"):
            self.assertEqual(core, os.environ["POTLUCKDB_EXPECT_CORE_VERSION"])
        if os.environ.get("POTLUCKDB_EXPECT_SQLITE_VERSION"):
            self.assertEqual(sqlite, os.environ["POTLUCKDB_EXPECT_SQLITE_VERSION"])

    def test_dbapi2_module(self):
        import potluckdb.dbapi2
        self.assertIs(potluckdb.dbapi2.Connection, potluckdb.Connection)
        self.assertIs(potluckdb.dbapi2.connect, potluckdb.connect)
        self.assertEqual(potluckdb.dbapi2.paramstyle, "qmark")


class NamesTests(unittest.TestCase):
    def test_every_stdlib_name_exists(self):
        stdlib_names = run_python("""
            import sqlite3, sqlite3.dbapi2
            print(sorted(n for n in dir(sqlite3) if not n.startswith("_")))
            print(sorted(n for n in dir(sqlite3.dbapi2) if not n.startswith("_")))
            print(sorted(n for n in dir(sqlite3.Connection) if not n.startswith("_")))
            print(sorted(n for n in dir(sqlite3.Cursor) if not n.startswith("_")))
            print(sorted(n for n in dir(sqlite3.Row) if not n.startswith("_")))
            print(sorted(n for n in dir(getattr(sqlite3, "Blob", object)) if not n.startswith("_")))
        """).splitlines()
        import potluckdb.dbapi2
        ours = [
            dir(potluckdb), dir(potluckdb.dbapi2), dir(potluckdb.Connection),
            dir(potluckdb.Cursor), dir(potluckdb.Row), dir(getattr(potluckdb, "Blob", object)),
        ]
        for line, names in zip(stdlib_names, ours):
            missing = sorted(set(eval(line)) - set(names))
            self.assertEqual(missing, [], "names of the standard sqlite3 module missing from potluckdb")


class IsolationTests(unittest.TestCase):
    """The standard sqlite3 module (the system's or Python's own SQLite) and
    potluckdb (its built-in library) each use their own SQLite in one process."""

    CHECK = """
        import sqlite3

        def has_potluckdb_function(connection, error):
            try:
                connection.execute("select potluckdb_version()")
                return True
            except error as e:
                assert "no such function" in str(e), e
                return False

        def check_stdlib(label):
            con = sqlite3.connect(":memory:")
            assert con.execute("select sqlite_version()").fetchone()[0] == sqlite3.sqlite_version
            assert not has_potluckdb_function(con, sqlite3.OperationalError), \\
                f"{label}: the standard sqlite3 module runs on PotluckDB's library"
            con.close()
            return sqlite3.sqlite_version

        def check_potluckdb():
            import potluckdb
            con = potluckdb.connect(":memory:")
            core, version = con.execute("select potluckdb_version(), sqlite_version()").fetchone()
            assert core == potluckdb.core_version and version == potluckdb.sqlite_version
            con.close()
            return potluckdb.sqlite_version
    """

    def test_stdlib_first_then_potluckdb(self):
        out = run_python(textwrap.dedent(self.CHECK) + textwrap.dedent("""
            before = check_stdlib("before")
            ours = check_potluckdb()
            after = check_stdlib("after")
            assert before == after
            print(before, ours)
        """))
        stdlib_version, our_version = out.split()
        self.assertEqual(our_version, potluckdb.sqlite_version)

    def test_potluckdb_first_then_stdlib(self):
        out = run_python(textwrap.dedent(self.CHECK) + textwrap.dedent("""
            ours = check_potluckdb()
            theirs = check_stdlib("after potluckdb")
            print(theirs, ours)
        """))
        stdlib_version, our_version = out.split()
        self.assertEqual(our_version, potluckdb.sqlite_version)


class SymbolTests(unittest.TestCase):
    """The extension exports only its init function, never SQLite's API."""

    def extension(self):
        return pathlib.Path(potluckdb._sqlite3.__file__)

    @unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("nm"), "needs nm on Linux")
    def test_no_sqlite_symbols_linux(self):
        dynamic = subprocess.run(["nm", "-D", str(self.extension())], capture_output=True,
                                 text=True, check=True).stdout
        sqlite = [line for line in dynamic.splitlines() if "sqlite3_" in line or "potluckdb_" in line]
        self.assertEqual(sqlite, [], "SQLite symbols in the extension's dynamic symbol table")
        defined = [line.split()[-1] for line in dynamic.splitlines() if " T " in line]
        self.assertIn("PyInit__sqlite3", defined)

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("nm"), "needs nm on macOS")
    def test_no_sqlite_symbols_macos(self):
        exported = subprocess.run(["nm", "-gU", str(self.extension())], capture_output=True,
                                  text=True, check=True).stdout
        undefined = subprocess.run(["nm", "-u", str(self.extension())], capture_output=True,
                                   text=True, check=True).stdout
        self.assertEqual([l for l in exported.splitlines() if "sqlite3_" in l], [])
        self.assertEqual([l for l in undefined.splitlines() if "sqlite3_" in l], [])
        self.assertIn("_PyInit__sqlite3", [l.split()[-1] for l in exported.splitlines()])

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_exports_and_imports_windows(self):
        exports, dlls = pe_exports_and_imports(self.extension().read_bytes())
        self.assertEqual(exports, ["PyInit__sqlite3"])
        self.assertFalse([d for d in dlls if "sqlite" in d.lower()], dlls)


def pe_exports_and_imports(data):
    """Exported names and imported DLL names of a PE file (DLL / .pyd)."""
    import struct
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe:pe + 4] == b"PE\0\0"
    sections_count = struct.unpack_from("<H", data, pe + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    optional = pe + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    directories = optional + (112 if magic == 0x20B else 96)
    sections = []
    for i in range(sections_count):
        base = optional + optional_size + 40 * i
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", data, base + 8)
        sections.append((vaddr, max(vsize, rsize), raddr))

    def offset(rva):
        for vaddr, size, raddr in sections:
            if vaddr <= rva < vaddr + size:
                return rva - vaddr + raddr
        raise ValueError(rva)

    def cstring(rva):
        start = offset(rva)
        return data[start:data.index(b"\0", start)].decode()

    exports = []
    export_rva, export_size = struct.unpack_from("<II", data, directories)
    if export_size:
        names_count, _, names_rva = struct.unpack_from("<III", data, offset(export_rva) + 24)[0], 0,             struct.unpack_from("<I", data, offset(export_rva) + 32)[0]
        for i in range(names_count):
            exports.append(cstring(struct.unpack_from("<I", data, offset(names_rva) + 4 * i)[0]))
    dlls = []
    import_rva, import_size = struct.unpack_from("<II", data, directories + 8)
    if import_size:
        entry = offset(import_rva)
        while True:
            name_rva = struct.unpack_from("<I", data, entry + 12)[0]
            if name_rva == 0:
                break
            dlls.append(cstring(name_rva))
            entry += 20
    return exports, dlls


def _chdir(path):
    @contextlib.contextmanager
    def change():
        old = os.getcwd()
        os.chdir(path)
        try:
            yield
        finally:
            os.chdir(old)
    return change()


if __name__ == "__main__":
    print(f"potluckdb {potluckdb.__version__} (PotluckDB {potluckdb.core_version}, "
          f"SQLite {potluckdb.sqlite_version}) on Python {platform.python_version()}, "
          f"{platform.system()} {platform.machine()}")
    unittest.main()
