"""Check the frozen math vectors against a built PotluckDB library: every
statement in math.tsv must give exactly the recorded bits (PRD K1).

Usage: python check_math.py <library> [vectors file] [--all]

<library> is the shared library itself (libsqlite3.so.0, libsqlite3.0.dylib
or sqlite3.dll). The vectors file defaults to math.tsv next to this script.
--all lists every difference, not just the first few.

The file format is described at the top of math.tsv. Runs on Python 3.6 and
newer, so it also runs in the oldest Linux images the library supports.
"""
import collections
import ctypes
import pathlib
import re
import struct
import sys

SQLITE_ROW, SQLITE_DONE = 100, 101
INTEGER, FLOAT, TEXT, BLOB, NULL = 1, 2, 3, 4, 5
SHOWN = 20


class Database:
    """One in-memory database on the library, through SQLite's C API."""

    def __init__(self, path):
        lib = ctypes.CDLL(str(path))
        lib.sqlite3_open.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
        lib.sqlite3_prepare_v2.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                           ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        for name in ("sqlite3_step", "sqlite3_finalize"):
            getattr(lib, name).argtypes = [ctypes.c_void_p]
        for name, restype in (("sqlite3_column_type", ctypes.c_int), ("sqlite3_column_double", ctypes.c_double),
                              ("sqlite3_column_int64", ctypes.c_int64), ("sqlite3_column_bytes", ctypes.c_int),
                              ("sqlite3_column_blob", ctypes.c_void_p)):
            function = getattr(lib, name)
            function.argtypes, function.restype = [ctypes.c_void_p, ctypes.c_int], restype
        lib.sqlite3_errmsg.argtypes, lib.sqlite3_errmsg.restype = [ctypes.c_void_p], ctypes.c_char_p
        lib.sqlite3_close.argtypes = [ctypes.c_void_p]
        self.lib, self.db = lib, ctypes.c_void_p()
        if lib.sqlite3_open(b":memory:", ctypes.byref(self.db)) != 0:
            raise RuntimeError("sqlite3_open failed")

    def rows(self, sql):
        """Runs every statement in sql; returns the first column of each row
        of the last one, as tokens (see math.tsv)."""
        lib, tokens = self.lib, []
        text = sql.encode()
        buffer = ctypes.create_string_buffer(text)
        at = ctypes.cast(buffer, ctypes.c_void_p).value
        end = at + len(text)
        while at < end:
            stmt, tail = ctypes.c_void_p(), ctypes.c_void_p()
            if lib.sqlite3_prepare_v2(self.db, at, end - at, ctypes.byref(stmt), ctypes.byref(tail)) != 0:
                return [self._error()]
            at = tail.value or end
            if not stmt.value:  # only white space or a comment was left
                break
            tokens = []
            rc = lib.sqlite3_step(stmt)
            while rc == SQLITE_ROW:
                tokens.append(self._token(stmt))
                rc = lib.sqlite3_step(stmt)
            lib.sqlite3_finalize(stmt)
            if rc != SQLITE_DONE:
                return [self._error()]
        return tokens

    def _error(self):
        return "error:" + self.lib.sqlite3_errmsg(self.db).decode().replace(" ", "_")

    def _token(self, stmt):
        lib, kind = self.lib, self.lib.sqlite3_column_type(stmt, 0)
        if kind == INTEGER:
            return "int:%d" % lib.sqlite3_column_int64(stmt, 0)
        if kind == FLOAT:
            return "real:" + struct.pack(">d", lib.sqlite3_column_double(stmt, 0)).hex()
        if kind == NULL:
            return "null"
        pointer = lib.sqlite3_column_blob(stmt, 0)  # before _bytes, as SQLite advises
        size = lib.sqlite3_column_bytes(stmt, 0)
        data = ctypes.string_at(pointer, size) if size else b""
        return ("text:" + data.decode()) if kind == TEXT else ("blob:" + data.hex())

    def close(self):
        self.lib.sqlite3_close(self.db)


def read_vectors(path):
    """(line number, SQL, expected tokens or None for set-up) for each vector."""
    vectors = []
    for number, line in enumerate(pathlib.Path(str(path)).read_text(encoding="utf-8").splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        sql, expected = line.split("\t")
        vectors.append((number, sql, None if expected == "-" else expected.split(" ")))
    return vectors


def label(sql):
    """What a vector tests, for the summary: its first function name."""
    found = re.search(r"([a-z_0-9]+)\(", sql[len("SELECT "):] if sql.startswith("SELECT ") else sql)
    return found.group(1) if found and not sql.startswith("WITH") else "SQL-level"


def main():
    arguments = [a for a in sys.argv[1:] if a != "--all"]
    if not arguments:
        sys.exit(__doc__)
    library = pathlib.Path(arguments[0])
    vectors_file = pathlib.Path(arguments[1]) if len(arguments) > 1 else pathlib.Path(__file__).with_name("math.tsv")
    db = Database(library)
    differences, checked = [], 0
    for number, sql, expected in read_vectors(vectors_file):
        got = db.rows(sql)
        if expected is None:
            if got and got[0].startswith("error:"):
                sys.exit("set-up failed on line %d: %s: %s" % (number, sql, got[0]))
            continue
        checked += 1
        if got != expected:
            differences.append((number, sql, expected, got))
    db.close()
    if not differences:
        print("ok: %d math vectors give the recorded bits (%s)" % (checked, vectors_file.name))
        return
    per_label = collections.Counter(label(sql) for _, sql, _, _ in differences)
    print("FAIL: %d of %d math vectors differ from the recorded bits" % (len(differences), checked))
    print("  by function: " + ", ".join("%s %d" % item for item in sorted(per_label.items())))
    shown = differences if "--all" in sys.argv else differences[:SHOWN]
    for number, sql, expected, got in shown:
        print("  line %d: %s\n    expected %s\n    got      %s" % (number, sql, " ".join(expected), " ".join(got)))
    if len(shown) < len(differences):
        print("  ... and %d more (--all lists them)" % (len(differences) - len(shown)))
    sys.exit(1)


if __name__ == "__main__":
    main()
