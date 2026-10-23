"""python -m potluckdb: the sqlite3 command-line shell, running on potluckdb.

Python 3.12 and newer ship a small shell as `python -m sqlite3`. Rather than
keep a copy, this runs the shell of the Python that is running it (its
Lib/sqlite3/__main__.py), with `sqlite3` meaning potluckdb, so the options,
prompts and output are exactly those of that Python version.
"""
import os
import sys
import sysconfig

import potluckdb


def _load_stdlib_shell():
    path = os.path.join(sysconfig.get_path("stdlib"), "sqlite3", "__main__.py")
    try:
        with open(path, encoding="utf-8") as file:
            source = file.read()
    except OSError:
        raise ImportError(
            f"python -m potluckdb needs the sqlite3 shell of Python 3.12 or newer ({path})"
        ) from None
    namespace = {"__name__": __name__ + "._shell", "__file__": path, "__builtins__": __builtins__}
    saved = sys.modules.get("sqlite3")
    sys.modules["sqlite3"] = potluckdb  # the shell's `import sqlite3`
    try:
        exec(compile(source, path, "exec"), namespace)
    finally:
        if saved is None:
            del sys.modules["sqlite3"]
        else:
            sys.modules["sqlite3"] = saved
    return namespace


_shell = _load_stdlib_shell()
main = _shell["main"]
execute = _shell.get("execute")
SqliteInteractiveConsole = _shell.get("SqliteInteractiveConsole")

if __name__ == "__main__":
    main(sys.argv[1:])
