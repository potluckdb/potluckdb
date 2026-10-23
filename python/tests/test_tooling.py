"""Tests of the build and test tooling that need no core archive (they run on
every change, even before a PotluckDB release exists).

    python tests/test_tooling.py [-v]
"""
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import core_archive  # noqa: E402
import run_cpython_tests  # noqa: E402


class CoreArchiveTests(unittest.TestCase):
    def test_pep440(self):
        for core, python in [("0.8.0-dev.1", "0.8.0.dev1"), ("0.8.0-rc.2", "0.8.0rc2"),
                             ("0.8.0-alpha.3", "0.8.0a3"), ("0.8.0-beta.4", "0.8.0b4"),
                             ("1.0.0", "1.0.0")]:
            with self.subTest(core=core):
                self.assertEqual(core_archive.pep440(core), python)
        for bad in ("0.8.0-dev", "0.8.0-preview.1", "0.8.0-dev.x"):
            with self.subTest(bad=bad), self.assertRaises(core_archive.CoreError):
                core_archive.pep440(bad)

    def test_archive_names(self):
        self.assertEqual(core_archive.archive_name("0.8.0-dev.1", "linux-x64-gnu"),
                         "potluckdb-sqlite-0.8.0-dev.1-linux-x64-gnu.tar.gz")
        self.assertEqual(core_archive.archive_name("0.8.0-dev.1", "windows-arm64"),
                         "potluckdb-sqlite-0.8.0-dev.1-windows-arm64.zip")
        self.assertEqual(len(core_archive.TARGETS), 8)

    def test_host_target(self):
        self.assertIn(core_archive.host_target(), core_archive.TARGETS)

    def test_find_in_dir(self):
        target = "linux-x64-gnu"
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            with self.assertRaisesRegex(core_archive.CoreError, "has no potluckdb-sqlite"):
                core_archive._find_in_dir(d, target, None)
            for name in ("potluckdb-sqlite-0.8.0-dev.1-linux-x64-gnu.tar.gz",
                         "potluckdb-sqlite-0.8.0-dev.1-linux-x64-musl.tar.gz",
                         "potluckdb-cli-0.8.0-dev.1-linux-x64-gnu.tar.gz"):
                (d / name).write_bytes(b"")
            found = core_archive._find_in_dir(d, target, None)
            self.assertEqual(found.name, "potluckdb-sqlite-0.8.0-dev.1-linux-x64-gnu.tar.gz")
            (d / "potluckdb-sqlite-0.8.0-dev.2-linux-x64-gnu.tar.gz").write_bytes(b"")
            with self.assertRaisesRegex(core_archive.CoreError, "several archives"):
                core_archive._find_in_dir(d, target, None)
            found = core_archive._find_in_dir(d, target, "0.8.0-dev.2")
            self.assertEqual(found.name, "potluckdb-sqlite-0.8.0-dev.2-linux-x64-gnu.tar.gz")


class KnownFailuresTests(unittest.TestCase):
    TEXT = """
        # comment
        test_a.T.test_all  # everywhere
        test_b.T.test_310  [3.10]  # only 3.10
        test_c.T.test_312_up  [3.12+]  # 3.12 and newer
        test_d.T.test_range  [3.11-3.13, windows]  # 3.11 to 3.13 on Windows
    """

    def known(self, python, system):
        return set(run_cpython_tests.parse_known_failures(self.TEXT, python, system))

    def test_conditions(self):
        self.assertEqual(self.known((3, 10), "Linux"), {"test_a.T.test_all", "test_b.T.test_310"})
        self.assertEqual(self.known((3, 12), "Windows"),
                         {"test_a.T.test_all", "test_c.T.test_312_up", "test_d.T.test_range"})
        self.assertEqual(self.known((3, 14), "Windows"), {"test_a.T.test_all", "test_c.T.test_312_up"})

    def test_bad_lines(self):
        for line in ("test_a.T.test_x", "test_a.T.test_x [mars] # r", "test_a.T.test_x [3.x] # r"):
            with self.subTest(line=line), self.assertRaises(ValueError):
                run_cpython_tests.parse_known_failures(line, (3, 12), "Linux")

    def test_repository_file_parses(self):
        run_cpython_tests.load_known_failures()


if __name__ == "__main__":
    unittest.main()
