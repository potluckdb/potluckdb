"""The frozen math vectors file is well formed and covers what it must
(tests/vectors/math.tsv; the release test runs it against every archive)."""
import pathlib
import re
import sys
import unittest

VECTORS = pathlib.Path(__file__).resolve().parent / "vectors"
sys.path.insert(0, str(VECTORS))
import check_math  # noqa: E402

TOKEN = re.compile(r"^(real:[0-9a-f]{16}|int:-?[0-9]+|text:\S*|blob:[0-9a-f]*|null)$")
# Every SQL math function: those SQLite takes from the pinned math library,
# and those IEEE 754 defines exactly.
FUNCTIONS = ["acos", "acosh", "asin", "asinh", "atan", "atan2", "atanh", "cos", "cosh", "exp", "ln", "log",
             "log10", "log2", "pow", "sin", "sinh", "tan", "tanh", "sqrt", "ceil", "floor", "trunc", "mod",
             "radians", "degrees"]


class MathVectors(unittest.TestCase):
    def setUp(self):
        self.vectors = check_math.read_vectors(VECTORS / "math.tsv")

    def test_tokens(self):
        for number, sql, expected in self.vectors:
            if expected is not None:
                for token in expected:
                    self.assertRegex(token, TOKEN, "line %d" % number)

    def test_coverage(self):
        checked = [(sql, expected) for _, sql, expected in self.vectors if expected is not None]
        self.assertGreater(len(checked), 5000)
        self.assertEqual(len({sql for sql, _ in checked}), len(checked), "a statement comes up twice")
        for name in FUNCTIONS:
            calls = [sql for sql, _ in checked if sql.startswith("SELECT %s(" % name)]
            self.assertGreater(len(calls), 60, name)
            for edge in ("(0.0)", "(-0.0)", "(5e-324)", "(9e999)", "(NULL)"):
                if name not in ("pow", "atan2", "mod", "log"):
                    self.assertIn("SELECT %s%s" % (name, edge), calls, name)
        self.assertTrue(any(" OVER (" in sql for sql, _ in checked), "window functions")
        self.assertTrue(any(sql.startswith("WITH") and "sum(" in sql for sql, _ in checked), "aggregates")

    def test_labels(self):
        self.assertEqual(check_math.label("SELECT sin(0.5)"), "sin")
        self.assertEqual(check_math.label("WITH t(x) AS (VALUES (1)) SELECT sum(sin(x)) FROM t"), "SQL-level")


if __name__ == "__main__":
    unittest.main()
