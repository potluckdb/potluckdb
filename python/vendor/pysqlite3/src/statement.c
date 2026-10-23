/* statement.c - the statement type
 *
 * Copyright (C) 2005-2010 Gerhard Häring <gh@ghaering.de>
 *
 * This file is part of pysqlite.
 *
 * This software is provided 'as-is', without any express or implied
 * warranty.  In no event will the authors be held liable for any damages
 * arising from the use of this software.
 *
 * Permission is granted to anyone to use this software for any purpose,
 * including commercial applications, and to alter it and redistribute it
 * freely, subject to the following restrictions:
 *
 * 1. The origin of this software must not be misrepresented; you must not
 *    claim that you wrote the original software. If you use this software
 *    in a product, an acknowledgment in the product documentation would be
 *    appreciated but is not required.
 * 2. Altered source versions must be plainly marked as such, and must not be
 *    misrepresented as being the original software.
 * 3. This notice may not be removed or altered from any source distribution.
 *
 * Altered for PotluckDB (see ../README.md): rewritten. A statement is
 * prepared once (checking the length limit, NUL characters and that only one
 * statement is given) and knows whether it is DML (INSERT, UPDATE, DELETE,
 * REPLACE, after any leading comments); it cannot be created from Python.
 */

#include "statement.h"
#include "util.h"

/* The first character of sql that is not whitespace or part of a comment,
 * or NULL if there is none. */
static const char *
lstrip_sql(const char *sql)
{
    const char *p = sql;
    while (*p) {
        switch (*p) {
            case ' ':
            case '\t':
            case '\f':
            case '\n':
            case '\r':
                p++;
                break;
            case '-':
                if (p[1] != '-') {
                    return p;
                }
                p += 2;
                while (*p && *p != '\n') {
                    p++;
                }
                if (*p == '\0') {
                    return NULL;
                }
                p++;
                break;
            case '/':
                if (p[1] != '*') {
                    return p;
                }
                p += 2;
                while (*p && !(p[0] == '*' && p[1] == '/')) {
                    p++;
                }
                if (*p == '\0') {
                    return NULL;  /* an unclosed comment runs to the end */
                }
                p += 2;
                break;
            default:
                return p;
        }
    }
    return NULL;
}

static int
starts_with_keyword(const char *p, const char *keyword)
{
    size_t n = strlen(keyword);
    return PyOS_strnicmp(p, keyword, n) == 0;
}

pysqlite_Statement *
pysqlite_statement_create(pysqlite_Connection *connection, PyObject *sql)
{
    Py_ssize_t size;
    const char *sql_cstr = PyUnicode_AsUTF8AndSize(sql, &size);
    if (sql_cstr == NULL) {
        return NULL;
    }

    sqlite3 *db = connection->db;
    int max_length = sqlite3_limit(db, SQLITE_LIMIT_SQL_LENGTH, -1);
    if (size > max_length) {
        PyErr_SetString(connection->DataError, "query string is too large");
        return NULL;
    }
    if (strlen(sql_cstr) != (size_t)size) {
#if PYSQLITE_PY311
        PyErr_SetString(connection->ProgrammingError, "the query contains a null character");
#else
        PyErr_SetString(PyExc_ValueError, "the query contains a null character");
#endif
        return NULL;
    }

    sqlite3_stmt *stmt;
    const char *tail;
    int rc;
    Py_BEGIN_ALLOW_THREADS
    rc = sqlite3_prepare_v2(db, sql_cstr, (int)size + 1, &stmt, &tail);
    Py_END_ALLOW_THREADS
    if (rc != SQLITE_OK) {
        pysqlite_set_error_from_db(db);
        return NULL;
    }

    if (lstrip_sql(tail) != NULL) {
#if PYSQLITE_PY311
        PyErr_SetString(connection->ProgrammingError,
                        "You can only execute one statement at a time.");
#else
        PyErr_SetString(connection->Warning, "You can only execute one statement at a time.");
#endif
        goto error;
    }

    int is_dml = 0;
    const char *p = lstrip_sql(sql_cstr);
    if (p != NULL) {
        is_dml = starts_with_keyword(p, "insert") || starts_with_keyword(p, "update")
                 || starts_with_keyword(p, "delete") || starts_with_keyword(p, "replace");
    }

    pysqlite_Statement *self = PyObject_New(pysqlite_Statement, &pysqlite_StatementType);
    if (self == NULL) {
        goto error;
    }
    self->st = stmt;
    self->is_dml = is_dml;
    return self;

error:
    (void)sqlite3_finalize(stmt);
    return NULL;
}

static void
statement_dealloc(pysqlite_Statement *self)
{
    if (self->st) {
        Py_BEGIN_ALLOW_THREADS
        sqlite3_finalize(self->st);
        Py_END_ALLOW_THREADS
        self->st = NULL;
    }
    Py_TYPE(self)->tp_free((PyObject *)self);
}

PyTypeObject pysqlite_StatementType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = MODULE_NAME ".Statement",
    .tp_basicsize = sizeof(pysqlite_Statement),
    .tp_dealloc = (destructor)statement_dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_DISALLOW_INSTANTIATION,
};

int
pysqlite_statement_setup_types(void)
{
    return PyType_Ready(&pysqlite_StatementType);
}
