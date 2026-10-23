"""PotluckDB for Python: a drop-in replacement for the sqlite3 module.

    import potluckdb as sqlite3
    db = sqlite3.connect("app.db")
    db.execute("select potluckdb_version(), sqlite_version()").fetchone()

Every name of the standard library's sqlite3 module works the same; queries
run on PotluckDB's own build of SQLite, linked into this package.

    potluckdb.__version__    this package's version
    potluckdb.core_version   the PotluckDB library's version
"""
import sys

from potluckdb.dbapi2 import *  # noqa: F401,F403
from potluckdb._sqlite3 import __version__, core_version  # noqa: F401

if sys.version_info < (3, 12):
    def __getattr__(name):
        if name == "OptimizedUnicode":
            import warnings
            warnings.warn("""
            OptimizedUnicode is deprecated and will be removed in Python 3.12.
            Since Python 3.3 it has simply been an alias for 'str'.
        """, DeprecationWarning, stacklevel=2)
            return str
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
elif sys.version_info < (3, 14):
    from potluckdb.dbapi2 import _deprecated_names, _deprecated_version, _deprecated_version_info  # noqa: F401

    def __getattr__(name):
        if name in _deprecated_names:
            from warnings import warn
            warn(f"{name} is deprecated and will be removed in Python 3.14",
                 DeprecationWarning, stacklevel=2)
            return globals()[f"_deprecated_{name}"]
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

del sys
