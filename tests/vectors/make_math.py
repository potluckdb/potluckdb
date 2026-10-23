"""Write math.tsv, the frozen math vectors: SQL statements that compute with
floating point, with the exact bits PotluckDB's library returns for them.

Run it once, on one platform, against a built library, and only when the
library's math changes on purpose (for example a new version of the math
code it builds in). That is a compatibility change: devices on the old and
the new version compute different bits, so it needs a `compatibility` change
note. Every platform is then checked against the file with check_math.py.

Usage: python make_math.py <library> [output, default: math.tsv next to this script]
"""
import math
import pathlib
import platform
import random
import struct
import sys

from check_math import Database

SEED = 20261023
RANDOM = 150  # random inputs per function

INF = float("inf")
TINY = 5e-324  # smallest subnormal
MAX_SUBNORMAL = 2.225073858507201e-308
MIN_NORMAL = 2.2250738585072014e-308
MAX = 1.7976931348623157e308
BELOW_ONE = 0.9999999999999999  # the double just below 1
ABOVE_ONE = 1.0000000000000002  # the double just above 1

# Inputs every one-argument function gets.
EDGES = [0.0, -0.0, TINY, -TINY, MAX_SUBNORMAL, MIN_NORMAL, -MIN_NORMAL, MAX, -MAX, INF, -INF,
         1.0, -1.0, 0.5, -0.5, 2.0, -2.0, 0.1, 10.0, 1e-300, 1e-8, 1e8, 1e300, -1e300,
         math.pi, -math.pi, math.pi / 2, math.pi / 4, math.e, BELOW_ONE, ABOVE_ONE,
         1e22, 2.0 ** 52, 2.0 ** 53, 2.0 ** 63]
# Arguments that are not REAL: SQLite converts or rejects them before any math.
OTHER_ARGUMENTS = ["0", "1", "-1", "2", "9223372036854775807", "-9223372036854775808",
                   "NULL", "'abc'", "'0.5'", "x'3132'"]


def bits(x):
    return struct.pack(">d", x).hex()


def literal(x):
    """x as an SQL literal that SQLite reads back as exactly x."""
    if math.isinf(x):
        return "9e999" if x > 0 else "-9e999"
    return repr(x)


def scaled(rng, low, high, sign=None):
    """A double 2**e * (1 + random 52-bit fraction) with e uniform in [low, high]."""
    x = math.ldexp(1 + rng.getrandbits(52) / 2.0 ** 52, rng.randint(low, high))
    return x * (sign if sign is not None else rng.choice((1, -1)))


def near_half_pi_multiples(rng, count, largest):
    return [rng.randint(1, largest) * (math.pi / 2) * rng.choice((1, -1)) for _ in range(count)]


def one_argument(rng):
    """(SQL function, inputs) for every one-argument function."""
    trig = lambda: ([scaled(rng, -30, 3) for _ in range(RANDOM // 3)]
                    + [scaled(rng, 3, 30) for _ in range(RANDOM // 6)]
                    + [scaled(rng, 30, 1023) for _ in range(RANDOM // 6)]
                    + near_half_pi_multiples(rng, RANDOM // 3, 2 ** 20)
                    + [1e22, 2.0 ** 1023, 2 * math.pi, 1.5707963267948968, 3.1415926535897936])
    unit = lambda: ([rng.uniform(-1, 1) for _ in range(RANDOM * 2 // 3)]
                    + [scaled(rng, -60, -1) for _ in range(RANDOM // 3)]
                    + [0.7071067811865476, -0.7071067811865476, -BELOW_ONE, -ABOVE_ONE])
    positive = lambda: ([scaled(rng, -1074, 1023, 1) for _ in range(RANDOM * 2 // 3)]
                        + [1 + scaled(rng, -52, -1) for _ in range(RANDOM // 3)]
                        + [1e-310, 3.0, 1000.0, 1024.0, 0.001])
    return [
        ("sin", trig()), ("cos", trig()), ("tan", trig()),
        ("asin", unit()), ("acos", unit()),
        ("atan", [scaled(rng, -60, 60) for _ in range(RANDOM * 2 // 3)]
                 + [scaled(rng, 60, 1023) for _ in range(RANDOM // 3)]),
        ("sinh", [scaled(rng, -30, 9) for _ in range(RANDOM // 2)] + [rng.uniform(-720, 720) for _ in range(RANDOM // 2)]
                 + [710.4758600739439, 710.475860073944, -710.4758600739439, 709.782712893384]),
        ("cosh", [scaled(rng, -30, 9) for _ in range(RANDOM // 2)] + [rng.uniform(-720, 720) for _ in range(RANDOM // 2)]
                 + [710.4758600739439, 710.475860073944, -710.4758600739439, 709.782712893384]),
        ("tanh", [scaled(rng, -30, 6) for _ in range(RANDOM // 2)] + [rng.uniform(-25, 25) for _ in range(RANDOM // 2)]
                 + [19.0615, 22.0, -22.0, 0.55]),
        ("asinh", [scaled(rng, -60, 1023) for _ in range(RANDOM)]),
        ("acosh", [1 + scaled(rng, -52, -1, 1) for _ in range(RANDOM // 2)]
                  + [scaled(rng, 0, 1023, 1) for _ in range(RANDOM // 2)] + [BELOW_ONE, 1.5, 2.0 ** 28]),
        ("atanh", unit() + [BELOW_ONE, 0.5, 0.25]),
        ("exp", [rng.uniform(-745.2, 709.8) for _ in range(RANDOM * 2 // 3)]
                + [scaled(rng, -60, 3) for _ in range(RANDOM // 3)]
                + [709.782712893384, 709.7827128933841, -745.1332191019411, -745.1332191019412,
                   -708.3964185322641, -708.39641853226414, 1e-300, 88.72283905206835]),
        ("ln", positive()), ("log10", positive()), ("log2", positive()),
        ("sqrt", [scaled(rng, -1074, 1023, 1) for _ in range(RANDOM)] + [4.0, 9.0, 1e-310]),
        ("ceil", [scaled(rng, -5, 60) for _ in range(RANDOM)] + [2.0 ** 52 + 0.5, 4503599627370497.0]),
        ("floor", [scaled(rng, -5, 60) for _ in range(RANDOM)] + [2.0 ** 52 + 0.5, 4503599627370497.0]),
        ("trunc", [scaled(rng, -5, 60) for _ in range(RANDOM)] + [2.0 ** 52 + 0.5, 4503599627370497.0]),
        ("radians", [scaled(rng, -30, 1020) for _ in range(RANDOM)] + [180.0, 90.0, 360.0]),
        ("degrees", [scaled(rng, -30, 1020) for _ in range(RANDOM)] + [math.pi / 2]),
    ]


SPECIAL = [0.0, -0.0, 1.0, -1.0, INF, -INF, 0.5, -0.5, 2.0, -2.0, TINY, MAX, 3.0, -3.0]


def two_arguments(rng):
    """(SQL function, [(x, y)]) for every two-argument function."""
    pow_inputs = ([(scaled(rng, -30, 30, 1), rng.uniform(-40, 40)) for _ in range(RANDOM * 2 // 3)]
                  + [(1 + scaled(rng, -52, -10), rng.uniform(-1e6, 1e6)) for _ in range(RANDOM // 3)]
                  + [(-scaled(rng, -10, 10, 1), float(rng.randint(-60, 60))) for _ in range(RANDOM // 3)]
                  + [(scaled(rng, -1074, 1023, 1), rng.uniform(-2, 2)) for _ in range(RANDOM // 3)]
                  + [(x, y) for x in SPECIAL for y in SPECIAL]
                  + [(2.0, 1024.0), (2.0, 1023.0), (2.0, -1074.0), (2.0, -1075.0), (10.0, 308.0), (10.0, -323.0),
                     (-8.0, 1 / 3), (0.5, 1075.0), (BELOW_ONE, 2.0 ** 60), (ABOVE_ONE, 2.0 ** 60), (1.1, 365.0),
                     (MAX, 0.5), (TINY, 0.5), (-2.0, 1025.0), (-2.0, 1024.0)])
    atan2_inputs = ([(scaled(rng, -60, 60), scaled(rng, -60, 60)) for _ in range(RANDOM)]
                    + [(scaled(rng, -1074, 1023), scaled(rng, -1074, 1023)) for _ in range(RANDOM // 3)]
                    + [(y, x) for y in SPECIAL for x in SPECIAL])
    mod_inputs = ([(scaled(rng, -20, 60), scaled(rng, -20, 30)) for _ in range(RANDOM)]
                  + [(scaled(rng, -1074, 1023), scaled(rng, -1074, 1023)) for _ in range(RANDOM // 3)]
                  + [(x, y) for x in SPECIAL for y in SPECIAL])
    log_inputs = ([(scaled(rng, -20, 20, 1), scaled(rng, -1074, 1023, 1)) for _ in range(RANDOM // 2)]
                  + [(2.0, 1024.0), (10.0, 1000.0), (3.0, 81.0), (BELOW_ONE, 2.0), (ABOVE_ONE, 2.0), (0.5, 8.0)])
    return [("pow", pow_inputs), ("atan2", atan2_inputs), ("mod", mod_inputs), ("log", log_inputs)]


# Math reached through other SQL: aggregates, window functions, indexes,
# generated columns, full-text ranking, text conversion. A line "-" runs SQL
# for set-up only.
SERIES = "WITH RECURSIVE s(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM s WHERE i<%d) "
NINE = "WITH t(x) AS (VALUES (0.1),(0.2),(0.3),(0.4),(0.5),(0.6),(0.7),(0.8),(0.9)) "
SQL_LEVEL = [
    "SELECT pow(2, 0.5)", "SELECT power(2, 0.5)", "SELECT exp(1)", "SELECT ln(10)", "SELECT log(10)",
    "SELECT log10(2)", "SELECT log2(10)", "SELECT log(2, 1024)", "SELECT log(3, 81)", "SELECT log(10, 1000)",
    "SELECT radians(180)", "SELECT degrees(pi())", "SELECT degrees(1)", "SELECT atan2(1, 1)", "SELECT 4*atan(1)",
    "SELECT pi()", "SELECT sqrt(2)", "SELECT mod(10.5, 3)", "SELECT mod(-7, 3)", "SELECT exp(ln(2))",
    "SELECT ln(exp(2))", "SELECT sin(pi())", "SELECT cos(pi()/3)", "SELECT tan(pi()/4)", "SELECT acos(-1)",
    "SELECT 2*asin(1)", "SELECT exp(1)*exp(1) - exp(2)", "SELECT pow(10, -2)", "SELECT pow(1.1, 365)",
    "SELECT pow(2, 0.5)*pow(2, 0.5) - 2", "SELECT sinh(1)", "SELECT cosh(1)", "SELECT tanh(0.5)",
    "SELECT asinh(1)", "SELECT acosh(2)", "SELECT atanh(0.5)",
    "SELECT 1000*pow(1 + 0.05/12, 12*30)",
    "SELECT 6371000*2*asin(sqrt(pow(sin(radians(48.8566-51.5074)/2), 2) + cos(radians(51.5074))"
    "*cos(radians(48.8566))*pow(sin(radians(2.3522+0.1278)/2), 2)))",
    "SELECT CAST(pow(2, 0.5) AS TEXT)", "SELECT CAST(exp(1) AS TEXT)", "SELECT printf('%.17g', exp(1))",
    "SELECT printf('%.6f', sin(1))", "SELECT round(sin(1), 12)", "SELECT round(exp(10), 3)",
    "SELECT ceil(-0.5)", "SELECT floor(-0.5)", "SELECT trunc(-0.5)", "SELECT ceil(5)", "SELECT floor(-5)",
    "SELECT ceiling(1.5)", "SELECT sin(1) = sin(1.0)", "SELECT sign(sin(-0.0))", "SELECT exp(0.5) > exp(0.4999999999999999)",
    NINE + "SELECT sum(sin(x)) FROM t", NINE + "SELECT avg(exp(x)) FROM t", NINE + "SELECT total(ln(x)) FROM t",
    NINE + "SELECT max(atan2(x, 1-x)) FROM t", NINE + "SELECT min(cos(x)) FROM t",
    NINE + "SELECT median(tan(x)) FROM t", NINE + "SELECT percentile(log2(x+1), 25) FROM t",
    NINE + "SELECT percentile_cont(pow(x, 1.5), 0.3) FROM t",
    SERIES % 1000 + "SELECT sum(sin(i)*cos(i)) FROM s", SERIES % 1000 + "SELECT avg(exp(-i/100.0)) FROM s",
    SERIES % 1000 + "SELECT total(pow(i, 1.5)) FROM s", SERIES % 1000 + "SELECT sum(ln(i)) - ln(1000) FROM s",
    SERIES % 40 + "SELECT sum(sin(i)) OVER (ORDER BY i ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) FROM s",
    SERIES % 40 + "SELECT avg(ln(i)) OVER (ORDER BY i) FROM s",
    SERIES % 40 + "SELECT exp(-i/10.0) - lag(exp(-i/10.0)) OVER (ORDER BY i) FROM s",
    SERIES % 40 + "SELECT sum(pow(i, 0.5)) OVER (PARTITION BY i % 3 ORDER BY i) FROM s",
    SERIES % 40 + "SELECT max(atan(i/7.0)) OVER (ORDER BY i ROWS BETWEEN 3 PRECEDING AND 3 FOLLOWING) FROM s",
    # A chaotic recurrence: one different last bit grows into a different answer.
    "WITH RECURSIVE s(i, v) AS (SELECT 0, 0.5 UNION ALL SELECT i+1, 3.9*v*(1-v) + 1e-3*sin(v) FROM s WHERE i < 200)"
    " SELECT v FROM s WHERE i = 200",
    # An index on a math expression: the failure the old product hit.
    ("CREATE TABLE pts(id INTEGER PRIMARY KEY, x REAL); " + SERIES % 500
     + "INSERT INTO pts(x) SELECT i*0.731 FROM s; CREATE INDEX pts_sin ON pts(sin(x));"
     " CREATE INDEX pts_e ON pts(exp(x/100), atan2(x, 7))", "-"),
    "SELECT sin(x) FROM pts INDEXED BY pts_sin WHERE sin(x) > 0.99 ORDER BY sin(x)",
    "SELECT id FROM pts INDEXED BY pts_sin ORDER BY sin(x) LIMIT 30",
    "SELECT id FROM pts INDEXED BY pts_e WHERE exp(x/100) > 30 ORDER BY exp(x/100), atan2(x, 7) LIMIT 10",
    "SELECT count(*) FROM pts WHERE sin(x) = (SELECT max(sin(x)) FROM pts)",
    "PRAGMA integrity_check",
    ("CREATE TABLE g(x REAL, y REAL GENERATED ALWAYS AS (ln(x) * cos(x)) STORED);"
     " INSERT INTO g(x) VALUES (0.5), (1.5), (2.5), (1e10), (1e-10)", "-"),
    "SELECT y FROM g ORDER BY rowid",
    # Full-text ranking (bm25 uses log).
    ("CREATE VIRTUAL TABLE docs USING fts5(body); INSERT INTO docs(body) VALUES ('local first sync'),"
     " ('sync through a bucket'), ('a bucket of sync and more sync'), ('no match here'), ('sync')", "-"),
    "SELECT bm25(docs) FROM docs WHERE docs MATCH 'sync' ORDER BY rowid",
    "SELECT rowid FROM docs WHERE docs MATCH 'sync' ORDER BY rank",
    # SQLite's own floating point, without the math library.
    "SELECT geopoly_area(geopoly_regular(0, 0, 1, 7))", "SELECT julianday('2026-10-23 12:34:56.789')",
    "SELECT unixepoch('2026-10-23 12:34:56.789', 'subsec')", "SELECT CAST('0.1' AS REAL) + CAST('0.2' AS REAL)",
    "SELECT 1e308 * 10", "SELECT -0.0", "SELECT 0.1 + 0.2 = 0.3", "SELECT CAST(1e-300 * 1e-300 AS TEXT)",
]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    db = Database(pathlib.Path(sys.argv[1]))
    output = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path(__file__).with_name("math.tsv")
    rng = random.Random(SEED)

    def checked_literal(x):
        text = literal(x)
        assert db.rows("SELECT " + text) == ["real:" + bits(x)], "SQLite reads %s differently" % text
        return text

    statements = []
    for name, inputs in one_argument(rng):
        statements += ["SELECT %s(%s)" % (name, checked_literal(x)) for x in EDGES + inputs]
        statements += ["SELECT %s(%s)" % (name, a) for a in OTHER_ARGUMENTS]
    for name, pairs in two_arguments(rng):
        statements += ["SELECT %s(%s, %s)" % (name, checked_literal(x), checked_literal(y)) for x, y in pairs]
        statements += ["SELECT %s(2.5, %s)" % (name, a) for a in OTHER_ARGUMENTS]
    lines = []
    for statement in dict.fromkeys(statements + SQL_LEVEL):  # once each, in order
        sql, setup = statement if isinstance(statement, tuple) else (statement, None)
        assert "\t" not in sql
        got = db.rows(sql)
        if setup:
            assert not (got and got[0].startswith("error:")), (sql, got)
            lines.append(sql + "\t-")
            continue
        assert got and not any(t.startswith("error:") or (" " in t) for t in got), (sql, got)
        lines.append(sql + "\t" + " ".join(got))
    version = db.rows("SELECT potluckdb_version() || '/' || sqlite_version()")[0][len("text:"):]
    db.close()
    header = [
        "# PotluckDB math vectors: SQL that computes with floating point, and the exact result",
        "# every platform must return. Written by make_math.py; checked on every platform by",
        "# check_math.py and by the library's own build tests.",
        "#",
        "# Each line: SQL, a tab, then one token per result row (first column):",
        "#   real:<16 hex digits>  an IEEE 754 double, bit for bit (sign, exponent, fraction)",
        "#   int:<n>               an integer",
        "#   text:<characters>     text",
        "#   null                  NULL (SQLite returns NULL where the math gives NaN)",
        "#   -                     set-up: run the SQL, ignore its result",
        "#",
        "# Generated once, with seed %d, by PotluckDB/SQLite %s on %s %s." % (
            SEED, version, platform.system(), platform.machine()),
        "# Results are those of the math library PotluckDB builds in, not exact values: the point",
        "# is that every platform agrees. Regenerate only when that library changes on purpose.",
    ]
    output.write_bytes(("\n".join(header + lines) + "\n").encode("utf-8"))
    print("wrote %d vectors to %s" % (len(lines), output))


if __name__ == "__main__":
    main()
