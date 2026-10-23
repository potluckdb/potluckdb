/* util.c - various utility functions
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
 * Altered for PotluckDB (see ../README.md): errors carry the extended
 * SQLite result code and its name (sqlite_errorcode, sqlite_errorname);
 * SQLITE_RANGE and SQLITE_MISUSE raise InterfaceError; errors can be raised
 * from a result code alone.
 */

#include "util.h"

/* The exception class for a primary result code; NULL if no exception is to
 * be raised (SQLITE_OK) or one is set already (out of memory). */
static PyObject *
exception_for(int code)
{
    pysqlite_state *state = pysqlite_get_state();
    switch (code & 0xff) {
        case SQLITE_OK:
            PyErr_Clear();
            return NULL;
        case SQLITE_INTERNAL:
        case SQLITE_NOTFOUND:
            return state->InternalError;
        case SQLITE_NOMEM:
            (void)PyErr_NoMemory();
            return NULL;
        case SQLITE_ERROR:
        case SQLITE_PERM:
        case SQLITE_ABORT:
        case SQLITE_BUSY:
        case SQLITE_LOCKED:
        case SQLITE_READONLY:
        case SQLITE_INTERRUPT:
        case SQLITE_IOERR:
        case SQLITE_FULL:
        case SQLITE_CANTOPEN:
        case SQLITE_PROTOCOL:
        case SQLITE_EMPTY:
        case SQLITE_SCHEMA:
            return state->OperationalError;
        case SQLITE_CORRUPT:
            return state->DatabaseError;
        case SQLITE_TOOBIG:
            return state->DataError;
        case SQLITE_CONSTRAINT:
        case SQLITE_MISMATCH:
            return state->IntegrityError;
        case SQLITE_MISUSE:
        case SQLITE_RANGE:
            return state->InterfaceError;
        default:
            return state->DatabaseError;
    }
}

static void
raise_with_code(PyObject *exc_class, int code, const char *message)
{
    PyObject *text = PyUnicode_FromString(message);
    if (text == NULL) {
        return;
    }
    PyObject *exc = PyObject_CallOneArg(exc_class, text);
    Py_DECREF(text);
    if (exc == NULL) {
        return;
    }

    PyObject *value = PyLong_FromLong(code);
    if (value == NULL || PyObject_SetAttrString(exc, "sqlite_errorcode", value) < 0) {
        Py_XDECREF(value);
        Py_DECREF(exc);
        return;
    }
    Py_DECREF(value);

    const char *name = pysqlite_error_name(code);
    value = PyUnicode_FromString(name ? name : "unknown");
    if (value == NULL || PyObject_SetAttrString(exc, "sqlite_errorname", value) < 0) {
        Py_XDECREF(value);
        Py_DECREF(exc);
        return;
    }
    Py_DECREF(value);

    PyErr_SetObject(exc_class, exc);
    Py_DECREF(exc);
}

void
pysqlite_set_error_from_code(int code)
{
    PyObject *exc_class = exception_for(code);
    if (exc_class != NULL) {
        raise_with_code(exc_class, code, sqlite3_errstr(code));
    }
}

void
pysqlite_set_error_from_db(sqlite3 *db)
{
    PyObject *exc_class = exception_for(sqlite3_errcode(db));
    if (exc_class != NULL) {
        raise_with_code(exc_class, sqlite3_extended_errcode(db), sqlite3_errmsg(db));
    }
}

sqlite_int64
pysqlite_long_as_int64(PyObject *value)
{
    int overflow;
    long long result = PyLong_AsLongLongAndOverflow(value, &overflow);
    if (result == -1 && PyErr_Occurred()) {
        return -1;
    }
    if (overflow) {
        PyErr_SetString(PyExc_OverflowError,
                        "Python int too large to convert to SQLite INTEGER");
        return -1;
    }
    return (sqlite_int64)result;
}
