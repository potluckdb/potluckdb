"""Connection.iterdump(): the database as SQL text, like the sqlite3 shell's
.dump command and the standard library's sqlite3 module."""
import sys


def _ident(name):
    return '"' + name.replace('"', '""') + '"'


def _literal(text):
    return "'" + text.replace("'", "''") + "'"


def _iterdump(connection, *, filter=None):
    """Yields the SQL statements that recreate the database.

    Called by Connection.iterdump(); filter is an optional LIKE pattern for
    the names of the tables, indexes, triggers and views to dump.
    """
    cu = connection.cursor()
    cu.row_factory = None  # plain tuples whatever the connection's factory

    if sys.version_info >= (3, 13):
        # Foreign keys off while loading, if the data violates them now.
        if cu.execute("PRAGMA foreign_key_check").fetchall():
            yield "PRAGMA foreign_keys=OFF;"
    yield "BEGIN TRANSACTION;"

    name_clause = 'AND "name" LIKE ?' if filter else ""
    params = [filter] if filter else []

    tables = cu.execute(f"""
        SELECT "name", "type", "sql"
        FROM "sqlite_master"
            WHERE "sql" NOT NULL AND
            "type" == 'table'
            {name_clause}
            ORDER BY "name"
        """, params).fetchall()

    writable_schema = False
    sequence = []
    for table, _kind, sql in tables:
        if table == "sqlite_sequence":
            rows = cu.execute('SELECT * FROM "sqlite_sequence";').fetchall()
            sequence = ['DELETE FROM "sqlite_sequence"'] + [
                f'INSERT INTO "sqlite_sequence" VALUES({_literal(name)},{seq})'
                for name, seq in rows
            ]
            continue
        elif table == "sqlite_stat1":
            yield 'ANALYZE "sqlite_master";'
        elif table.startswith("sqlite_"):
            continue
        elif sql.startswith("CREATE VIRTUAL TABLE"):
            if not writable_schema:
                writable_schema = True
                yield "PRAGMA writable_schema=ON;"
            yield ("INSERT INTO sqlite_master(type,name,tbl_name,rootpage,sql)"
                   f"VALUES('table',{_literal(table)},{_literal(table)},0,{_literal(sql)});")
        else:
            yield f"{sql};"

        # One INSERT per row, values quoted by SQLite itself.
        table_ident = _ident(table)
        columns = [str(info[1]) for info in cu.execute(f"PRAGMA table_info({table_ident})").fetchall()]
        values = "','".join(f"||quote({_ident(column)})||" for column in columns)
        select = f"SELECT 'INSERT INTO {table_ident.replace(chr(39), chr(39) * 2)} VALUES('{values}')' FROM {table_ident};"
        for row in cu.execute(select):
            yield f"{row[0]};"

    others = cu.execute(f"""
        SELECT "name", "type", "sql"
        FROM "sqlite_master"
            WHERE "sql" NOT NULL AND
            "type" IN ('index', 'trigger', 'view')
            {name_clause}
        """, params).fetchall()
    for _name, _kind, sql in others:
        yield f"{sql};"

    if writable_schema:
        yield "PRAGMA writable_schema=OFF;"

    # Sequence values last, after the tables that use them are filled.
    for statement in sequence:
        yield f"{statement};"

    yield "COMMIT;"
