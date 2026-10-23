"""The DB-API 2.0 (PEP 249) interface of potluckdb, as sqlite3.dbapi2.

Same names and behaviour as the standard library's sqlite3.dbapi2 for the
running Python version.
"""
import collections.abc
import datetime
import sys
import time

from potluckdb._sqlite3 import *  # noqa: F401,F403
from potluckdb._sqlite3 import Row, register_adapter, register_converter, sqlite_version

paramstyle = "qmark"
apilevel = "2.0"

if sys.version_info < (3, 11):
    threadsafety = 1  # what Python 3.10's sqlite3 reports

Date = datetime.date
Time = datetime.time
Timestamp = datetime.datetime


def DateFromTicks(ticks):
    return Date(*time.localtime(ticks)[:3])


def TimeFromTicks(ticks):
    return Time(*time.localtime(ticks)[3:6])


def TimestampFromTicks(ticks):
    return Timestamp(*time.localtime(ticks)[:6])


sqlite_version_info = tuple(int(part) for part in sqlite_version.split("."))

if sys.version_info < (3, 12):
    from potluckdb._sqlite3 import version  # noqa: F401
    version_info = tuple(int(part) for part in version.split("."))
elif sys.version_info < (3, 14):
    from potluckdb._sqlite3 import _deprecated_version
    _deprecated_names = frozenset({"version", "version_info"})
    _deprecated_version_info = tuple(int(part) for part in _deprecated_version.split("."))

Binary = memoryview
collections.abc.Sequence.register(Row)


def _register_default_adapters_and_converters():
    """The date/datetime adapters and date/timestamp converters of sqlite3
    (deprecated, with a warning when used, from Python 3.12)."""
    if sys.version_info >= (3, 12):
        from warnings import warn

        def deprecated(what):
            warn(f"The default {what} is deprecated as of Python 3.12; "
                 "see the sqlite3 documentation for suggested replacement recipes",
                 DeprecationWarning, stacklevel=3)
    else:
        def deprecated(what):
            pass

    def adapt_date(value):
        deprecated("date adapter")
        return value.isoformat()

    def adapt_datetime(value):
        deprecated("datetime adapter")
        return value.isoformat(" ")

    def convert_date(value):
        deprecated("date converter")
        return datetime.date(*map(int, value.split(b"-")))

    def convert_timestamp(value):
        deprecated("timestamp converter")
        date_part, time_part = value.split(b" ")
        year, month, day = map(int, date_part.split(b"-"))
        time_parts = time_part.split(b".")
        hours, minutes, seconds = map(int, time_parts[0].split(b":"))
        microseconds = int("{:0<6.6}".format(time_parts[1].decode())) if len(time_parts) == 2 else 0
        return datetime.datetime(year, month, day, hours, minutes, seconds, microseconds)

    register_adapter(datetime.date, adapt_date)
    register_adapter(datetime.datetime, adapt_datetime)
    register_converter("date", convert_date)
    register_converter("timestamp", convert_timestamp)


_register_default_adapters_and_converters()
del _register_default_adapters_and_converters

if sys.version_info < (3, 12):
    def enable_shared_cache(enable):
        import warnings
        from potluckdb._sqlite3 import enable_shared_cache as _enable_shared_cache
        warnings.warn(
            "enable_shared_cache is deprecated and will be removed in Python 3.12. "
            "Shared cache is strongly discouraged by the SQLite 3 documentation. "
            "If shared cache must be used, open the database in URI mode using"
            "the cache=shared query parameter.",
            DeprecationWarning, stacklevel=2)
        return _enable_shared_cache(enable)

if (3, 12) <= sys.version_info < (3, 14):
    def __getattr__(name):
        if name in _deprecated_names:
            from warnings import warn
            warn(f"{name} is deprecated and will be removed in Python 3.14",
                 DeprecationWarning, stacklevel=2)
            return globals()[f"_deprecated_{name}"]
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
