"""Runs CPython's own sqlite3 test suite against potluckdb, aliased as sqlite3.

The suite is taken from the CPython release that matches the running
interpreter (tag v3.X.Y): Lib/test/test_sqlite3 (3.11+) or Lib/sqlite3/test
(3.10), plus Lib/test/support. It is fetched with a shallow, sparse git clone
into a cache directory (POTLUCKDB_CPYTHON_TESTS, default build/cpython-tests).

Every failure must be listed in cpython_known_failures.txt with a reason; a
failure that is not listed (a new failure) makes the run fail. A listed test
that passes is reported, so the list can be trimmed.

    python tests/run_cpython_tests.py [-v] [--suite-dir DIR] [test name filters...]
"""
import argparse
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
KNOWN_FAILURES = HERE / "cpython_known_failures.txt"
PYTHON = sys.version_info[:2]


def cpython_tag():
    v = sys.version_info
    tag = f"v{v.major}.{v.minor}.{v.micro}"
    if v.releaselevel != "final":
        tag += {"alpha": "a", "beta": "b", "candidate": "rc"}[v.releaselevel] + str(v.serial)
    return tag


def suite_paths():
    tests = "Lib/sqlite3/test/" if PYTHON < (3, 11) else "Lib/test/test_sqlite3/"
    return [tests, "Lib/test/support/", "Lib/test/__init__.py"]


def fetch_suite(cache):
    """A checkout of the suite for this interpreter's CPython tag (cached)."""
    tag = cpython_tag()
    dest = cache / tag
    if (dest / ".complete").exists():
        return dest
    shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    git = ["git", "-c", "advice.detachedHead=false", "-c", "core.longpaths=true"]
    print(f"fetching CPython {tag} sqlite3 tests", flush=True)
    subprocess.run(git + ["clone", "--quiet", "--depth", "1", "--filter=blob:none", "--no-checkout",
                          "--branch", tag, "https://github.com/python/cpython.git", str(dest)], check=True)
    subprocess.run(git + ["-C", str(dest), "sparse-checkout", "set", "--no-cone"]
                   + ["/" + p for p in suite_paths()], check=True)
    subprocess.run(git + ["-C", str(dest), "checkout", "--quiet"], check=True)
    (dest / ".complete").write_text(tag)
    return dest


ALIAS_SQLITE3 = '''\
"""potluckdb under the name sqlite3, for CPython's test suite."""
import sys
import potluckdb
import potluckdb.dbapi2
import potluckdb.dump
sys.modules["sqlite3"] = potluckdb
sys.modules["sqlite3.dbapi2"] = potluckdb.dbapi2
sys.modules["sqlite3.dump"] = potluckdb.dump
try:
    import potluckdb.__main__
    sys.modules["sqlite3.__main__"] = potluckdb.__main__
except ImportError:
    pass
'''

ALIAS_SQLITE3_EXT = '''\
"""potluckdb._sqlite3 under the name _sqlite3, for CPython's test suite."""
import sys
import potluckdb._sqlite3
sys.modules["_sqlite3"] = potluckdb._sqlite3
'''


TESTCAPI_STUB = '''\
"""The constants of CPython's _testcapi that the sqlite3 tests use, for
Pythons built without the test C API (python-build-standalone, some
installers). The 3.11 and 3.12 suites import them at module level."""
import sys
INT_MAX = 2**31 - 1
INT_MIN = -2**31
UINT_MAX = 2**32 - 1
LLONG_MAX = 2**63 - 1
LLONG_MIN = -2**63
ULLONG_MAX = 2**64 - 1
PY_SSIZE_T_MAX = sys.maxsize
PY_SSIZE_T_MIN = -sys.maxsize - 1
'''


def make_alias(directory):
    """A directory that, first on sys.path, makes `import sqlite3` give potluckdb."""
    (directory / "sqlite3").mkdir(parents=True)
    (directory / "sqlite3" / "__init__.py").write_text(ALIAS_SQLITE3)
    (directory / "_sqlite3.py").write_text(ALIAS_SQLITE3_EXT)
    import importlib.util
    if importlib.util.find_spec("_testcapi") is None:
        (directory / "_testcapi.py").write_text(TESTCAPI_STUB)


# --- known failures -------------------------------------------------------

def _version_matches(token, python):
    m = re.fullmatch(r"(\d+)\.(\d+)(\+|-(\d+)\.(\d+))?", token)
    if not m:
        raise ValueError(f"bad version condition {token!r}")
    low = (int(m[1]), int(m[2]))
    if m[3] is None:
        return python == low
    if m[3] == "+":
        return python >= low
    return low <= python <= (int(m[4]), int(m[5]))


PLATFORMS = {"linux": "Linux", "macos": "Darwin", "windows": "Windows"}


def parse_known_failures(text, python=PYTHON, system=None, name="known failures"):
    """{test id: reason} for the failures expected on this Python and platform."""
    system = system or platform.system()
    known = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"(\S+)\s*(?:\[([^\]]*)\])?\s*#\s*(.+)", line)
        if not m:
            raise ValueError(f"{name}:{number}: expected '<test id> [conditions] # reason'")
        test_id, conditions, reason = m[1], (m[2] or "").replace(",", " ").split(), m[3]
        versions = [c for c in conditions if c[0].isdigit()]
        platforms = [c for c in conditions if not c[0].isdigit()]
        for p in platforms:
            if p not in PLATFORMS:
                raise ValueError(f"{name}:{number}: unknown platform {p!r}")
        if versions and not any(_version_matches(v, python) for v in versions):
            continue
        if platforms and system not in {PLATFORMS[p] for p in platforms}:
            continue
        known[test_id] = reason
    return known


def load_known_failures():
    return parse_known_failures(KNOWN_FAILURES.read_text(encoding="utf-8"), name=KNOWN_FAILURES.name)


# --- running --------------------------------------------------------------

class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}  # test id -> passed / failed / skipped / expected-failure

    def _record(self, test, outcome):
        test_id = short_id(test)
        # A test with subtests fails if any subtest fails.
        if self.outcomes.get(test_id) != "failed":
            self.outcomes[test_id] = outcome

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failed")

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "failed")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "skipped")

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test, "passed")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, "failed")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._record(test, "skipped" if issubclass(err[0], unittest.SkipTest) else "failed")


def short_id(test):
    """test_dbapi.ConnectionTests.test_x, the same for 3.10 (dbapi.ConnectionTests...) and 3.11+."""
    test_id = test.id()
    if isinstance(test, unittest.case._SubTest):
        test_id = test.test_case.id()
    for prefix in ("test.test_sqlite3.", "cpython_sqlite3_tests."):
        if test_id.startswith(prefix):
            test_id = test_id[len(prefix):]
            module, _, rest = test_id.partition(".")
            if not module.startswith("test_"):
                module = "test_" + module
            return f"{module}.{rest}"
    return test_id


def load_suite(checkout, work):
    loader = unittest.TestLoader()
    sys.path.insert(0, str(checkout / "Lib"))
    if PYTHON < (3, 11):
        # 3.10 keeps the suite in the sqlite3 package itself; load it under another name.
        package = work / "pkg" / "cpython_sqlite3_tests"
        shutil.copytree(checkout / "Lib" / "sqlite3" / "test", package)
        sys.path.insert(0, str(work / "pkg"))
        import cpython_sqlite3_tests  # noqa: F401
        names = ["dbapi", "types", "userfunctions", "factory", "transactions", "hooks",
                 "regression", "dump", "backup"]
        suites = []
        for name in names:
            module = __import__(f"cpython_sqlite3_tests.{name}", fromlist=["suite"])
            suites.append(loader.loadTestsFromModule(module))
        return unittest.TestSuite(suites)
    import test.test_sqlite3
    return loader.loadTestsFromModule(test.test_sqlite3)


def filter_suite(suite, patterns):
    if not patterns:
        return suite
    out = unittest.TestSuite()
    for test in _flatten(suite):
        if any(p in short_id(test) for p in patterns):
            out.addTest(test)
    return out


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--suite-dir", type=pathlib.Path,
                        help="an existing CPython checkout (or sparse checkout) to take the tests from")
    parser.add_argument("--list-failures", action="store_true",
                        help="print every failing test id (to update the known-failures file)")
    parser.add_argument("patterns", nargs="*", help="run only tests whose id contains one of these")
    args = parser.parse_args(argv)

    cache = pathlib.Path(os.environ.get("POTLUCKDB_CPYTHON_TESTS") or HERE.parent / "build" / "cpython-tests")
    checkout = args.suite_dir or fetch_suite(cache)
    known = load_known_failures()

    import potluckdb
    work = pathlib.Path(tempfile.mkdtemp(prefix="potluckdb-cpython-tests-"))
    make_alias(work / "alias")
    sys.path.insert(0, str(work / "alias"))
    # Subprocesses started by the tests (sys.executable -c ...) see the alias
    # and the same potluckdb; they run in another directory, so paths are absolute.
    package_parent = str(pathlib.Path(potluckdb.__file__).resolve().parent.parent)
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [str(work / "alias"), package_parent]
        + [os.path.abspath(p) for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p])

    import sqlite3
    assert sqlite3 is potluckdb, "the sqlite3 alias did not take effect"
    print(f"CPython {platform.python_version()} ({cpython_tag()}) sqlite3 tests against potluckdb "
          f"{potluckdb.__version__}, SQLite {potluckdb.sqlite_version}, on {platform.system()}", flush=True)

    suite = filter_suite(load_suite(checkout, work), args.patterns)
    start = time.monotonic()
    old_cwd = os.getcwd()
    os.chdir(work)  # tests create files (TESTFN) in the current directory
    try:
        runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1, resultclass=Result,
                                         stream=sys.stdout, buffer=False)
        result = runner.run(suite)
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(work, ignore_errors=True)
    elapsed = time.monotonic() - start

    outcomes = result.outcomes
    failed = sorted(t for t, o in outcomes.items() if o == "failed")
    passed = [t for t, o in outcomes.items() if o == "passed"]
    skipped = [t for t, o in outcomes.items() if o == "skipped"]
    new = [t for t in failed if t not in known]
    known_hit = [t for t in failed if t in known]
    fixed = sorted(t for t in known if outcomes.get(t) == "passed")
    ran = len(passed) + len(failed)

    print()
    if args.list_failures:
        print("failing tests:")
        for t in failed:
            print(f"  {t}")
    if fixed:
        print("known failures that now pass (remove them from cpython_known_failures.txt):")
        for t in fixed:
            print(f"  {t}")
    if new:
        print("NEW failures (not in cpython_known_failures.txt):")
        for t in new:
            print(f"  {t}")
    rate = 100.0 * len(passed) / ran if ran else 0.0
    print(f"\nPython {platform.python_version()}: {len(passed)}/{ran} passed ({rate:.1f}%), "
          f"{len(known_hit)} known failures, {len(new)} new failures, {len(skipped)} skipped, "
          f"{elapsed:.0f}s")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
