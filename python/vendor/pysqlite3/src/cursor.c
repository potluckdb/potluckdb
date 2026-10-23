/* cursor.c - the cursor type
 *
 * Copyright (C) 2004-2010 Gerhard Häring <gh@ghaering.de>
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
 * Altered for PotluckDB (see ../README.md): rewritten to behave like the
 * sqlite3 module of the Python version it is built for: rows are fetched as the
 * statement is stepped (no prefetching, no reset after commit or rollback),
 * parameter binding lives here, statements come from the LRU cache, implicit
 * transactions follow the connection's autocommit mode, executescript() checks
 * the length limit, rowcount covers RETURNING and statements after comments,
 * arraysize is validated, and recursive use is detected while rows are built.
 */

#include "cursor.h"
#include "microprotocols.h"
#include "prepare_protocol.h"
#include "util.h"

static const char errmsg_recursive[] = "Recursive use of cursors not allowed.";

static inline int
check_cursor_locked(pysqlite_Cursor *cur)
{
    if (cur->locked) {
        PyErr_SetString(pysqlite_get_state()->ProgrammingError, errmsg_recursive);
        return 0;
    }
    return 1;
}

static int
register_cursor(pysqlite_Connection *connection, PyObject *cursor)
{
    PyObject *ref = PyWeakref_NewRef(cursor, NULL);
    if (ref == NULL) {
        return 0;
    }
    int rc = PyList_Append(connection->cursors, ref);
    Py_DECREF(ref);
    return rc == 0;
}

static int
cursor_init(pysqlite_Cursor *self, PyObject *args, PyObject *kwargs)
{
    pysqlite_Connection *connection;
    if (kwargs != NULL && PyDict_GET_SIZE(kwargs) != 0) {
        PyErr_SetString(PyExc_TypeError, "Cursor() takes no keyword arguments");
        return -1;
    }
    if (!PyArg_ParseTuple(args, "O!:Cursor", &pysqlite_ConnectionType, &connection)) {
        return -1;
    }
    if (!check_cursor_locked(self)) {
        return -1;
    }

    Py_XSETREF(self->connection, (pysqlite_Connection *)Py_NewRef(connection));
    Py_CLEAR(self->statement);
    Py_CLEAR(self->row_cast_map);
    Py_XSETREF(self->description, Py_NewRef(Py_None));
    Py_XSETREF(self->lastrowid, Py_NewRef(Py_None));
    self->arraysize = 1;
    self->closed = 0;
    self->rowcount = -1L;
    Py_XSETREF(self->row_factory, Py_NewRef(Py_None));

    if (!pysqlite_check_thread(self->connection)) {
        return -1;
    }
    if (connection->cursors == NULL) {
        /* The connection itself is not initialised. */
        return pysqlite_check_connection(connection) ? 0 : -1;
    }
    if (!register_cursor(connection, (PyObject *)self)) {
        return -1;
    }
    self->initialized = 1;
    return 0;
}

static inline int
stmt_reset(pysqlite_Statement *stmt)
{
    int rc = SQLITE_OK;
    if (stmt->st != NULL) {
        Py_BEGIN_ALLOW_THREADS
        rc = sqlite3_reset(stmt->st);
        Py_END_ALLOW_THREADS
    }
    return rc;
}

static inline int
stmt_step(sqlite3_stmt *stmt)
{
    int rc;
    Py_BEGIN_ALLOW_THREADS
    rc = sqlite3_step(stmt);
    Py_END_ALLOW_THREADS
    return rc;
}

static int
cursor_traverse(pysqlite_Cursor *self, visitproc visit, void *arg)
{
    Py_VISIT(self->connection);
    Py_VISIT(self->description);
    Py_VISIT(self->row_cast_map);
    Py_VISIT(self->lastrowid);
    Py_VISIT(self->row_factory);
    Py_VISIT(self->statement);
    return 0;
}

static int
cursor_clear(pysqlite_Cursor *self)
{
    Py_CLEAR(self->connection);
    Py_CLEAR(self->description);
    Py_CLEAR(self->row_cast_map);
    Py_CLEAR(self->lastrowid);
    Py_CLEAR(self->row_factory);
    if (self->statement) {
        /* Reset the statement if the user did not close the cursor. */
        stmt_reset(self->statement);
        Py_CLEAR(self->statement);
    }
    return 0;
}

static void
cursor_dealloc(pysqlite_Cursor *self)
{
    PyObject_GC_UnTrack(self);
    if (self->in_weakreflist != NULL) {
        PyObject_ClearWeakRefs((PyObject *)self);
    }
    cursor_clear(self);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

/* ---------------------------------------------------------------------- */
/* Converters and rows                                                     */

static PyObject *
get_converter(const char *name, Py_ssize_t len)
{
    PyObject *key = PyUnicode_FromStringAndSize(name, len);
    if (key == NULL) {
        return NULL;
    }
    PyObject *upper = PyObject_CallMethodNoArgs(key, pysqlite_get_state()->str_upper);
    Py_DECREF(key);
    if (upper == NULL) {
        return NULL;
    }
    PyObject *converter = PyDict_GetItemWithError(pysqlite_get_state()->converters, upper);
    Py_DECREF(upper);
    return converter;  /* borrowed */
}

static int
build_row_cast_map(pysqlite_Cursor *self)
{
    if (!self->connection->detect_types) {
        return 0;
    }
    Py_XSETREF(self->row_cast_map, PyList_New(0));
    if (self->row_cast_map == NULL) {
        return -1;
    }
    sqlite3_stmt *st = self->statement->st;
    for (int i = 0; i < sqlite3_column_count(st); i++) {
        PyObject *converter = NULL;

        if (self->connection->detect_types & PARSE_COLNAMES) {
            const char *colname = sqlite3_column_name(st, i);
            if (colname == NULL) {
                PyErr_NoMemory();
                Py_CLEAR(self->row_cast_map);
                return -1;
            }
            const char *type_start = NULL;
            for (const char *pos = colname; *pos; pos++) {
                if (*pos == '[') {
                    type_start = pos + 1;
                }
                else if (*pos == ']' && type_start != NULL) {
                    converter = get_converter(type_start, pos - type_start);
                    if (converter == NULL && PyErr_Occurred()) {
                        Py_CLEAR(self->row_cast_map);
                        return -1;
                    }
                    break;
                }
            }
        }

        if (converter == NULL && (self->connection->detect_types & PARSE_DECLTYPES)) {
            const char *decltype = sqlite3_column_decltype(st, i);
            if (decltype != NULL) {
                /* "INTEGER NOT NULL" -> INTEGER, "NUMBER(10)" -> NUMBER */
                const char *pos = decltype;
                while (*pos && *pos != ' ' && *pos != '(') {
                    pos++;
                }
                converter = get_converter(decltype, pos - decltype);
                if (converter == NULL && PyErr_Occurred()) {
                    Py_CLEAR(self->row_cast_map);
                    return -1;
                }
            }
        }

        if (PyList_Append(self->row_cast_map, converter ? converter : Py_None) < 0) {
            Py_CLEAR(self->row_cast_map);
            return -1;
        }
    }
    return 0;
}

static PyObject *
build_column_name(pysqlite_Cursor *self, const char *colname)
{
    Py_ssize_t len;
    if (self->connection->detect_types & PARSE_COLNAMES) {
        const char *pos = colname;
        while (*pos && *pos != '[') {
            pos++;
        }
        if (*pos == '[' && pos != colname && pos[-1] == ' ') {
            pos--;
        }
        len = pos - colname;
    }
    else {
        len = (Py_ssize_t)strlen(colname);
    }
    return PyUnicode_FromStringAndSize(colname, len);
}

/* The current row of the statement (sqlite3_step() returned SQLITE_ROW). */
static PyObject *
fetch_one_row(pysqlite_Cursor *self)
{
    sqlite3_stmt *st = self->statement->st;
    int numcols;
    Py_BEGIN_ALLOW_THREADS
    numcols = sqlite3_data_count(st);
    Py_END_ALLOW_THREADS

    PyObject *row = PyTuple_New(numcols);
    if (row == NULL) {
        return NULL;
    }
    sqlite3 *db = self->connection->db;
    PyObject *text_factory = self->connection->text_factory;
    for (int i = 0; i < numcols; i++) {
        PyObject *converter = Py_None;
        if (self->connection->detect_types && self->row_cast_map != NULL
            && i < PyList_GET_SIZE(self->row_cast_map)) {
            converter = PyList_GET_ITEM(self->row_cast_map, i);
        }

        /* sqlite3_column_bytes() must come after _blob() or _text(). */
        PyObject *value;
        if (converter != Py_None) {
            const void *blob = sqlite3_column_blob(st, i);
            if (blob == NULL) {
                if (sqlite3_errcode(db) == SQLITE_NOMEM) {
                    PyErr_NoMemory();
                    goto error;
                }
                value = Py_NewRef(Py_None);
            }
            else {
                PyObject *item = PyBytes_FromStringAndSize(blob, sqlite3_column_bytes(st, i));
                if (item == NULL) {
                    goto error;
                }
                value = PyObject_CallOneArg(converter, item);
                Py_DECREF(item);
            }
        }
        else {
            int coltype;
            Py_BEGIN_ALLOW_THREADS
            coltype = sqlite3_column_type(st, i);
            Py_END_ALLOW_THREADS
            if (coltype == SQLITE_NULL) {
                value = Py_NewRef(Py_None);
            }
            else if (coltype == SQLITE_INTEGER) {
                value = PyLong_FromLongLong(sqlite3_column_int64(st, i));
            }
            else if (coltype == SQLITE_FLOAT) {
                value = PyFloat_FromDouble(sqlite3_column_double(st, i));
            }
            else if (coltype == SQLITE_TEXT) {
                const char *text = (const char *)sqlite3_column_text(st, i);
                if (text == NULL && sqlite3_errcode(db) == SQLITE_NOMEM) {
                    PyErr_NoMemory();
                    goto error;
                }
                Py_ssize_t nbytes = sqlite3_column_bytes(st, i);
                if (text_factory == (PyObject *)&PyUnicode_Type) {
                    value = PyUnicode_FromStringAndSize(text, nbytes);
                    if (value == NULL && PyErr_ExceptionMatches(PyExc_UnicodeDecodeError)) {
                        PyErr_Clear();
                        const char *colname = sqlite3_column_name(st, i);
                        if (colname == NULL) {
                            PyErr_NoMemory();
                            goto error;
                        }
                        char buf[200];
                        PyOS_snprintf(buf, sizeof(buf) - 1,
                                      "Could not decode to UTF-8 column '%s' with text '%s'",
                                      colname, text);
                        PyObject *msg = PyUnicode_Decode(buf, strlen(buf), "ascii", "replace");
                        if (msg == NULL) {
                            PyErr_SetString(self->connection->OperationalError,
                                            "Could not decode to UTF-8");
                        }
                        else {
                            PyErr_SetObject(self->connection->OperationalError, msg);
                            Py_DECREF(msg);
                        }
                    }
                }
                else if (text_factory == (PyObject *)&PyBytes_Type) {
                    value = PyBytes_FromStringAndSize(text, nbytes);
                }
                else if (text_factory == (PyObject *)&PyByteArray_Type) {
                    value = PyByteArray_FromStringAndSize(text, nbytes);
                }
                else {
                    value = PyObject_CallFunction(text_factory, "y#", text, nbytes);
                }
            }
            else {
                const void *blob = sqlite3_column_blob(st, i);
                if (blob == NULL && sqlite3_errcode(db) == SQLITE_NOMEM) {
                    PyErr_NoMemory();
                    goto error;
                }
                value = PyBytes_FromStringAndSize(blob, sqlite3_column_bytes(st, i));
            }
        }
        if (value == NULL) {
            goto error;
        }
        PyTuple_SET_ITEM(row, i, value);
    }
    return row;

error:
    Py_DECREF(row);
    return NULL;
}

static int
check_cursor(pysqlite_Cursor *cur)
{
    if (!cur->initialized) {
        PyErr_SetString(pysqlite_get_state()->ProgrammingError,
                        "Base Cursor.__init__ not called.");
        return 0;
    }
    if (cur->closed) {
        PyErr_SetString(pysqlite_get_state()->ProgrammingError,
                        "Cannot operate on a closed cursor.");
        return 0;
    }
    return pysqlite_check_thread(cur->connection)
           && pysqlite_check_connection(cur->connection)
           && check_cursor_locked(cur);
}

static int
begin_transaction(pysqlite_Connection *con)
{
    char sql[24] = "BEGIN ";
    strcat(sql, con->isolation_level);
    int rc;
    Py_BEGIN_ALLOW_THREADS
    sqlite3_stmt *stmt;
    rc = sqlite3_prepare_v2(con->db, sql, -1, &stmt, NULL);
    if (rc == SQLITE_OK) {
        (void)sqlite3_step(stmt);
        rc = sqlite3_finalize(stmt);
    }
    Py_END_ALLOW_THREADS
    if (rc != SQLITE_OK) {
        pysqlite_set_error_from_db(con->db);
        return -1;
    }
    return 0;
}

/* ---------------------------------------------------------------------- */
/* Binding parameters                                                      */

static int
bind_param(pysqlite_Statement *self, int pos, PyObject *param)
{
    if (param == Py_None) {
        return sqlite3_bind_null(self->st, pos);
    }
    if (PyLong_Check(param)) {
        sqlite_int64 value = pysqlite_long_as_int64(param);
        if (value == -1 && PyErr_Occurred()) {
            return SQLITE_ERROR;
        }
        return sqlite3_bind_int64(self->st, pos, value);
    }
    if (PyFloat_Check(param)) {
        double value = PyFloat_AsDouble(param);
        if (value == -1 && PyErr_Occurred()) {
            return SQLITE_ERROR;
        }
        return sqlite3_bind_double(self->st, pos, value);
    }
    if (PyUnicode_Check(param)) {
        Py_ssize_t len;
        const char *str = PyUnicode_AsUTF8AndSize(param, &len);
        if (str == NULL) {
            return SQLITE_ERROR;
        }
        if (len > INT_MAX) {
            PyErr_SetString(PyExc_OverflowError, "string longer than INT_MAX bytes");
            return SQLITE_ERROR;
        }
        return sqlite3_bind_text(self->st, pos, str, (int)len, SQLITE_TRANSIENT);
    }
    if (PyObject_CheckBuffer(param)) {
        Py_buffer view;
        if (PyObject_GetBuffer(param, &view, PyBUF_SIMPLE) != 0) {
#if !PYSQLITE_PY311
            PyErr_SetString(PyExc_ValueError, "could not convert BLOB to buffer");
#endif
            return SQLITE_ERROR;
        }
        if (view.len > INT_MAX) {
            PyErr_SetString(PyExc_OverflowError, "BLOB longer than INT_MAX bytes");
            PyBuffer_Release(&view);
            return SQLITE_ERROR;
        }
        int rc = sqlite3_bind_blob(self->st, pos, view.buf, (int)view.len, SQLITE_TRANSIENT);
        PyBuffer_Release(&view);
        return rc;
    }
#if PYSQLITE_PY311
    PyErr_Format(pysqlite_get_state()->ProgrammingError,
                 "Error binding parameter %d: type '%s' is not supported",
                 pos, Py_TYPE(param)->tp_name);
#endif
    return SQLITE_ERROR;
}

/* 0 if obj is a built-in type that needs no adapting */
static inline int
need_adapt(PyObject *obj)
{
    if (pysqlite_get_state()->BaseTypeAdapted) {
        return 1;
    }
    return !(PyLong_CheckExact(obj) || PyFloat_CheckExact(obj)
             || PyUnicode_CheckExact(obj) || PyByteArray_CheckExact(obj));
}

/* Adapts and binds one parameter; steals the reference to param. */
static int
adapt_and_bind(pysqlite_Statement *self, int pos, PyObject *param, const char *name)
{
    PyObject *adapted = param;
    if (need_adapt(param)) {
        adapted = pysqlite_microprotocols_adapt(param, (PyObject *)&pysqlite_PrepareProtocolType,
                                                param);
        Py_DECREF(param);
        if (adapted == NULL) {
            return -1;
        }
    }
    int rc = bind_param(self, pos, adapted);
    Py_DECREF(adapted);
    if (rc != SQLITE_OK) {
#if PYSQLITE_PY311
        PyObject *exc = pysqlite_get_raised();
        pysqlite_set_error_from_db(sqlite3_db_handle(self->st));
        pysqlite_chain_exceptions(exc);
#else
        if (!PyErr_Occurred()) {
            if (name != NULL) {
                PyErr_Format(pysqlite_get_state()->InterfaceError,
                             "Error binding parameter :%s - probably unsupported type.", name);
            }
            else {
                PyErr_Format(pysqlite_get_state()->InterfaceError,
                             "Error binding parameter %d - probably unsupported type.", pos - 1);
            }
        }
#endif
        return -1;
    }
    (void)name;
    return 0;
}

static void
bind_parameters(pysqlite_Statement *self, PyObject *parameters)
{
    pysqlite_state *state = pysqlite_get_state();
    int needed;
    Py_BEGIN_ALLOW_THREADS
    needed = sqlite3_bind_parameter_count(self->st);
    Py_END_ALLOW_THREADS

    if (PyTuple_CheckExact(parameters) || PyList_CheckExact(parameters)
        || (!PyDict_Check(parameters) && PySequence_Check(parameters))) {
        Py_ssize_t given;
        if (PyTuple_CheckExact(parameters)) {
            given = PyTuple_GET_SIZE(parameters);
        }
        else if (PyList_CheckExact(parameters)) {
            given = PyList_GET_SIZE(parameters);
        }
        else {
            given = PySequence_Size(parameters);
            if (given == -1) {
                return;
            }
        }
        if (given != needed) {
            PyErr_Format(state->ProgrammingError,
                         "Incorrect number of bindings supplied. The current "
                         "statement uses %d, and there are %zd supplied.",
                         needed, given);
            return;
        }
        for (int i = 0; i < given; i++) {
#if PYSQLITE_PY312
            const char *name = sqlite3_bind_parameter_name(self->st, i + 1);
            if (name != NULL && name[0] != '?') {
#  if PYSQLITE_PY314
                PyErr_Format(state->ProgrammingError,
                             "Binding %d ('%s') is a named parameter, but you "
                             "supplied a sequence which requires nameless (qmark) "
                             "placeholders.", i + 1, name);
                return;
#  else
                if (PyErr_WarnFormat(PyExc_DeprecationWarning, 1,
                        "Binding %d ('%s') is a named parameter, but you "
                        "supplied a sequence which requires nameless (qmark) "
                        "placeholders. Starting with Python 3.14 an "
                        "sqlite3.ProgrammingError will be raised.", i + 1, name) < 0) {
                    return;
                }
#  endif
            }
#endif
            PyObject *param;
            if (PyTuple_CheckExact(parameters)) {
                param = Py_NewRef(PyTuple_GET_ITEM(parameters, i));
            }
            else if (PyList_CheckExact(parameters)) {
                param = Py_XNewRef(PyList_GetItem(parameters, i));
            }
            else {
                param = PySequence_GetItem(parameters, i);
            }
            if (param == NULL || adapt_and_bind(self, i + 1, param, NULL) < 0) {
                return;
            }
        }
    }
    else if (PyDict_Check(parameters)) {
        for (int i = 1; i <= needed; i++) {
            const char *name;
            Py_BEGIN_ALLOW_THREADS
            name = sqlite3_bind_parameter_name(self->st, i);
            Py_END_ALLOW_THREADS
            if (name == NULL) {
                PyErr_Format(state->ProgrammingError,
                             "Binding %d has no name, but you supplied a "
                             "dictionary (which has only names).", i);
                return;
            }
            name++;  /* skip the ':', '@' or '$' */
            PyObject *param;
            int found = pysqlite_mapping_get_optional_item(parameters, name, &param);
            if (found < 0) {
#if !PYSQLITE_PY313
                if (PyErr_ExceptionMatches(PyExc_LookupError)) {
                    PyErr_Clear();
                    found = 0;
                }
                else
#endif
                return;
            }
            if (found == 0) {
                PyErr_Format(state->ProgrammingError,
                             "You did not supply a value for binding parameter :%s.", name);
                return;
            }
            if (adapt_and_bind(self, i, param, name) < 0) {
                return;
            }
        }
    }
    else {
#if PYSQLITE_PY311
        PyErr_SetString(state->ProgrammingError, "parameters are of unsupported type");
#else
        PyErr_SetString(PyExc_ValueError, "parameters are of unsupported type");
#endif
    }
}

/* ---------------------------------------------------------------------- */
/* Executing                                                               */

static PyObject *
get_statement_from_cache(pysqlite_Cursor *self, PyObject *sql)
{
    return PyObject_CallOneArg(self->connection->statement_cache, sql);
}

PyObject *
pysqlite_query_execute(pysqlite_Cursor *self, int multiple, PyObject *sql, PyObject *second)
{
    PyObject *parameters_iter = NULL;
    PyObject *parameters = NULL;
    pysqlite_state *state = pysqlite_get_state();

    if (!check_cursor(self)) {
        return NULL;
    }
    self->locked = 1;

    if (multiple) {
        parameters_iter = PyObject_GetIter(second);
        if (parameters_iter == NULL) {
            goto error;
        }
    }
    else {
        PyObject *params = second ? Py_NewRef(second) : PyTuple_New(0);
        if (params == NULL) {
            goto error;
        }
        PyObject *list = PyList_New(1);
        if (list == NULL) {
            Py_DECREF(params);
            goto error;
        }
        PyList_SET_ITEM(list, 0, params);
        parameters_iter = PyObject_GetIter(list);
        Py_DECREF(list);
        if (parameters_iter == NULL) {
            goto error;
        }
    }

    Py_XSETREF(self->description, Py_NewRef(Py_None));
    if (self->statement) {
        (void)stmt_reset(self->statement);
    }

    Py_XSETREF(self->statement, (pysqlite_Statement *)get_statement_from_cache(self, sql));
    if (self->statement == NULL) {
        goto error;
    }

    if (multiple && sqlite3_stmt_readonly(self->statement->st)) {
        PyErr_SetString(state->ProgrammingError,
                        "executemany() can only execute DML statements.");
        goto error;
    }

    if (sqlite3_stmt_busy(self->statement->st)) {
        /* Another cursor is using the cached statement: prepare a new one. */
        Py_SETREF(self->statement, pysqlite_statement_create(self->connection, sql));
        if (self->statement == NULL) {
            goto error;
        }
    }

    (void)stmt_reset(self->statement);
    self->rowcount = self->statement->is_dml ? 0L : -1L;

    /* Legacy transaction control: BEGIN implicitly before DML. */
    if (self->connection->autocommit == AUTOCOMMIT_LEGACY
        && self->connection->isolation_level != NULL
        && self->statement->is_dml
        && sqlite3_get_autocommit(self->connection->db)) {
        if (begin_transaction(self->connection) < 0) {
            goto error;
        }
    }

    while (1) {
        parameters = PyIter_Next(parameters_iter);
        if (parameters == NULL) {
            break;
        }

        bind_parameters(self->statement, parameters);
        if (PyErr_Occurred()) {
            goto error;
        }

        int rc = stmt_step(self->statement->st);
        if (rc != SQLITE_DONE && rc != SQLITE_ROW) {
            if (PyErr_Occurred()) {
                /* An exception in a user-defined callback */
                if (state->enable_callback_tracebacks) {
                    PyErr_Print();
                }
                else {
                    PyErr_Clear();
                }
            }
            pysqlite_set_error_from_db(self->connection->db);
            goto error;
        }

        if (build_row_cast_map(self) != 0) {
            PyObject *exc = pysqlite_get_raised();
            PyErr_SetString(state->OperationalError, "Error while building row_cast_map");
            if (exc != NULL) {
                PyObject *new_exc = pysqlite_get_raised();
                PyException_SetCause(new_exc, Py_NewRef(exc));
                PyException_SetContext(new_exc, exc);
                pysqlite_set_raised(new_exc);
            }
            goto error;
        }

        int numcols;
        Py_BEGIN_ALLOW_THREADS
        numcols = sqlite3_column_count(self->statement->st);
        Py_END_ALLOW_THREADS
        if (self->description == Py_None && numcols > 0) {
            Py_SETREF(self->description, PyTuple_New(numcols));
            if (self->description == NULL) {
                goto error;
            }
            for (int i = 0; i < numcols; i++) {
                const char *colname = sqlite3_column_name(self->statement->st, i);
                if (colname == NULL) {
                    PyErr_NoMemory();
                    goto error;
                }
                PyObject *name = build_column_name(self, colname);
                if (name == NULL) {
                    goto error;
                }
                PyObject *descriptor = PyTuple_Pack(7, name, Py_None, Py_None, Py_None,
                                                    Py_None, Py_None, Py_None);
                Py_DECREF(name);
                if (descriptor == NULL) {
                    goto error;
                }
                PyTuple_SET_ITEM(self->description, i, descriptor);
            }
        }

        if (rc == SQLITE_DONE) {
            if (self->statement->is_dml) {
                self->rowcount += (long)sqlite3_changes(self->connection->db);
            }
            stmt_reset(self->statement);
        }
        Py_CLEAR(parameters);
    }

    if (!multiple) {
        sqlite_int64 lastrowid;
        Py_BEGIN_ALLOW_THREADS
        lastrowid = sqlite3_last_insert_rowid(self->connection->db);
        Py_END_ALLOW_THREADS
        Py_SETREF(self->lastrowid, PyLong_FromLongLong(lastrowid));
    }

error:
    Py_XDECREF(parameters);
    Py_XDECREF(parameters_iter);
    self->locked = 0;

    if (PyErr_Occurred()) {
        if (self->statement) {
            (void)stmt_reset(self->statement);
            Py_CLEAR(self->statement);
        }
        self->rowcount = -1L;
        return NULL;
    }
    if (self->statement && !sqlite3_stmt_busy(self->statement->st)) {
        Py_CLEAR(self->statement);
    }
    return Py_NewRef((PyObject *)self);
}

static PyObject *
cursor_execute(pysqlite_Cursor *self, PyObject *args)
{
    PyObject *sql, *parameters = NULL;
    if (!PyArg_ParseTuple(args, "U|O:execute", &sql, &parameters)) {
        return NULL;
    }
    return pysqlite_query_execute(self, 0, sql, parameters);
}

static PyObject *
cursor_executemany(pysqlite_Cursor *self, PyObject *args)
{
    PyObject *sql, *parameters;
    if (!PyArg_ParseTuple(args, "UO:executemany", &sql, &parameters)) {
        return NULL;
    }
    return pysqlite_query_execute(self, 1, sql, parameters);
}

static PyObject *
cursor_executescript(pysqlite_Cursor *self, PyObject *script_obj)
{
    if (!PyUnicode_Check(script_obj)) {
#if PYSQLITE_PY311
        PyErr_Format(PyExc_TypeError, "executescript() argument must be str, not %.50s",
                     Py_TYPE(script_obj)->tp_name);
#else
        PyErr_SetString(PyExc_ValueError, "script argument must be unicode.");
#endif
        return NULL;
    }
    const char *script = pysqlite_utf8_no_nul(script_obj);
    if (script == NULL) {
        return NULL;
    }
    if (!check_cursor(self)) {
        return NULL;
    }

    size_t len = strlen(script);
    int max_length = sqlite3_limit(self->connection->db, SQLITE_LIMIT_SQL_LENGTH, -1);
    if (len > (size_t)max_length) {
        PyErr_SetString(self->connection->DataError, "query string is too large");
        return NULL;
    }

    sqlite3 *db = self->connection->db;
    int rc = SQLITE_OK;
    if (self->connection->autocommit == AUTOCOMMIT_LEGACY && !sqlite3_get_autocommit(db)) {
        Py_BEGIN_ALLOW_THREADS
        rc = sqlite3_exec(db, "COMMIT", NULL, NULL, NULL);
        Py_END_ALLOW_THREADS
        if (rc != SQLITE_OK) {
            goto error;
        }
    }

    while (1) {
        const char *tail;
        Py_BEGIN_ALLOW_THREADS
        sqlite3_stmt *stmt;
        rc = sqlite3_prepare_v2(db, script, (int)len + 1, &stmt, &tail);
        if (rc == SQLITE_OK) {
            do {
                rc = sqlite3_step(stmt);
            } while (rc == SQLITE_ROW);
            rc = sqlite3_finalize(stmt);
        }
        Py_END_ALLOW_THREADS
        if (rc != SQLITE_OK) {
            goto error;
        }
        if (*tail == '\0') {
            break;
        }
        len -= (size_t)(tail - script);
        script = tail;
    }
    return Py_NewRef((PyObject *)self);

error:
    pysqlite_set_error_from_db(db);
    return NULL;
}

static PyObject *
cursor_iternext(pysqlite_Cursor *self)
{
    if (!check_cursor(self)) {
        return NULL;
    }
    if (self->statement == NULL) {
        return NULL;
    }
    sqlite3_stmt *stmt = self->statement->st;

    self->locked = 1;  /* the row's converters must not use this cursor */
    PyObject *row = fetch_one_row(self);
    self->locked = 0;
    if (row == NULL) {
        return NULL;
    }
    int rc = stmt_step(stmt);
    if (rc == SQLITE_DONE) {
        if (self->statement->is_dml) {
            self->rowcount = (long)sqlite3_changes(self->connection->db);
        }
        (void)stmt_reset(self->statement);
        Py_CLEAR(self->statement);
    }
    else if (rc != SQLITE_ROW) {
        pysqlite_set_error_from_db(self->connection->db);
        (void)stmt_reset(self->statement);
        Py_CLEAR(self->statement);
        Py_DECREF(row);
        return NULL;
    }
    if (self->row_factory != Py_None) {
        PyObject *args[] = {(PyObject *)self, row};
        Py_SETREF(row, PyObject_Vectorcall(self->row_factory, args, 2, NULL));
    }
    return row;
}

static PyObject *
cursor_fetchone(pysqlite_Cursor *self, PyObject *Py_UNUSED(ignored))
{
    PyObject *row = cursor_iternext(self);
    if (row == NULL && !PyErr_Occurred()) {
        Py_RETURN_NONE;
    }
    return row;
}

#if PYSQLITE_PY313
/* An unsigned 32-bit int, like PyLong_AsUInt32 (3.14). */
static int
as_uint32(PyObject *value, uint32_t *result)
{
    if (!PyLong_Check(value)) {
        PyErr_Format(PyExc_TypeError, "'%.200s' object cannot be interpreted as an integer",
                     Py_TYPE(value)->tp_name);
        return -1;
    }
    int overflow;
    long long v = PyLong_AsLongLongAndOverflow(value, &overflow);
    if (v == -1 && PyErr_Occurred()) {
        return -1;
    }
    if (overflow < 0 || (!overflow && v < 0)) {
        PyErr_SetString(PyExc_ValueError, "Cannot convert negative int");
        return -1;
    }
    if (overflow > 0 || v > (long long)UINT32_MAX) {
        PyErr_SetString(PyExc_OverflowError, "Python int too large to convert to C uint32_t");
        return -1;
    }
    *result = (uint32_t)v;
    return 0;
}
#endif

static PyObject *
cursor_fetchmany(pysqlite_Cursor *self, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"size", NULL};
#if PYSQLITE_PY313
    PyObject *size = NULL;
    uint32_t maxrows = self->arraysize;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|O:fetchmany", kwlist, &size)) {
        return NULL;
    }
    if (size != NULL && as_uint32(size, &maxrows) < 0) {
        return NULL;
    }
#else
    int maxrows = self->arraysize;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|i:fetchmany", kwlist, &maxrows)) {
        return NULL;
    }
#endif

    PyObject *list = PyList_New(0);
    if (list == NULL) {
        return NULL;
    }
#if PYSQLITE_PY313
    PyObject *row;
    while (maxrows > 0 && (row = cursor_iternext(self)) != NULL) {
        int rc = PyList_Append(list, row);
        Py_DECREF(row);
        if (rc < 0) {
            break;
        }
        maxrows--;
    }
#else
    PyObject *row;
    int counter = 0;
    while ((row = cursor_iternext(self)) != NULL) {
        int rc = PyList_Append(list, row);
        Py_DECREF(row);
        if (rc < 0 || ++counter == maxrows) {
            break;
        }
    }
#endif
    if (PyErr_Occurred()) {
        Py_DECREF(list);
        return NULL;
    }
    return list;
}

static PyObject *
cursor_fetchall(pysqlite_Cursor *self, PyObject *Py_UNUSED(ignored))
{
    PyObject *list = PyList_New(0);
    if (list == NULL) {
        return NULL;
    }
    PyObject *row;
    while ((row = cursor_iternext(self)) != NULL) {
        int rc = PyList_Append(list, row);
        Py_DECREF(row);
        if (rc < 0) {
            break;
        }
    }
    if (PyErr_Occurred()) {
        Py_DECREF(list);
        return NULL;
    }
    return list;
}

static PyObject *
cursor_setinputsizes(PyObject *self, PyObject *sizes)
{
    Py_RETURN_NONE;
}

static PyObject *
cursor_setoutputsize(PyObject *self, PyObject *args)
{
    PyObject *size, *column = Py_None;
    if (!PyArg_ParseTuple(args, "O|O:setoutputsize", &size, &column)) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
cursor_close(pysqlite_Cursor *self, PyObject *Py_UNUSED(ignored))
{
    if (!check_cursor_locked(self)) {
        return NULL;
    }
    if (self->connection == NULL) {
        PyErr_SetString(pysqlite_get_state()->ProgrammingError,
                        "Base Cursor.__init__ not called.");
        return NULL;
    }
    if (!pysqlite_check_thread(self->connection) || !pysqlite_check_connection(self->connection)) {
        return NULL;
    }
    if (self->statement) {
        (void)stmt_reset(self->statement);
        Py_CLEAR(self->statement);
    }
    self->closed = 1;
    Py_RETURN_NONE;
}

/* ---------------------------------------------------------------------- */
/* Attributes                                                              */

static PyObject *
cursor_get_arraysize(pysqlite_Cursor *self, void *Py_UNUSED(closure))
{
#if PYSQLITE_PY313
    return PyLong_FromUnsignedLong(self->arraysize);
#else
    return PyLong_FromLong(self->arraysize);
#endif
}

static int
cursor_set_arraysize(pysqlite_Cursor *self, PyObject *value, void *Py_UNUSED(closure))
{
    if (value == NULL) {
        PyErr_SetString(PyExc_AttributeError, "attribute 'arraysize' of '"
                        MODULE_NAME ".Cursor' objects cannot be deleted");
        return -1;
    }
#if PYSQLITE_PY313
    uint32_t size;
    if (as_uint32(value, &size) < 0) {
        return -1;
    }
#else
    if (!PyLong_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "an integer is required");
        return -1;
    }
    int size = pysqlite_long_as_int(value);
    if (size == -1 && PyErr_Occurred()) {
        return -1;
    }
#endif
    self->arraysize = size;
    return 0;
}

static PyObject *
cursor_get_row_factory(pysqlite_Cursor *self, void *Py_UNUSED(closure))
{
    return Py_NewRef(self->row_factory ? self->row_factory : Py_None);
}

static int
cursor_set_row_factory(pysqlite_Cursor *self, PyObject *value, void *Py_UNUSED(closure))
{
    if (value == NULL) {
        PyErr_SetString(PyExc_AttributeError, "cannot delete row_factory attribute");
        return -1;
    }
    Py_XSETREF(self->row_factory, Py_NewRef(value));
    return 0;
}

static PyMethodDef cursor_methods[] = {
    {"close", (PyCFunction)cursor_close, METH_NOARGS,
     PyDoc_STR("close($self, /)\n--\n\nCloses the cursor.")},
    {"execute", (PyCFunction)cursor_execute, METH_VARARGS,
     PyDoc_STR("execute($self, sql, parameters=(), /)\n--\n\nExecutes an SQL statement.")},
    {"executemany", (PyCFunction)cursor_executemany, METH_VARARGS,
     PyDoc_STR("executemany($self, sql, seq_of_parameters, /)\n--\n\n"
               "Repeatedly executes an SQL statement.")},
    {"executescript", (PyCFunction)cursor_executescript, METH_O,
     PyDoc_STR("executescript($self, sql_script, /)\n--\n\nExecutes multiple SQL statements at once.")},
    {"fetchall", (PyCFunction)cursor_fetchall, METH_NOARGS,
     PyDoc_STR("fetchall($self, /)\n--\n\nFetches all rows from the resultset.")},
    {"fetchmany", (PyCFunction)(void (*)(void))cursor_fetchmany, METH_VARARGS | METH_KEYWORDS,
     PyDoc_STR("fetchmany($self, /, size=1)\n--\n\nFetches several rows from the resultset.\n\n"
               "  size\n    The default value is set by the Cursor.arraysize attribute.")},
    {"fetchone", (PyCFunction)cursor_fetchone, METH_NOARGS,
     PyDoc_STR("fetchone($self, /)\n--\n\nFetches one row from the resultset.")},
    {"setinputsizes", (PyCFunction)cursor_setinputsizes, METH_O,
     PyDoc_STR("setinputsizes($self, sizes, /)\n--\n\nRequired by DB-API. Does nothing in sqlite3.")},
    {"setoutputsize", (PyCFunction)cursor_setoutputsize, METH_VARARGS,
     PyDoc_STR("setoutputsize($self, size, column=None, /)\n--\n\n"
               "Required by DB-API. Does nothing in sqlite3.")},
    {NULL, NULL}
};

static struct PyMemberDef cursor_members[] = {
    {"connection", PYSQLITE_T_OBJECT, offsetof(pysqlite_Cursor, connection), PYSQLITE_READONLY},
    {"description", PYSQLITE_T_OBJECT, offsetof(pysqlite_Cursor, description), PYSQLITE_READONLY},
    {"lastrowid", PYSQLITE_T_OBJECT, offsetof(pysqlite_Cursor, lastrowid), PYSQLITE_READONLY},
    {"rowcount", PYSQLITE_T_LONG, offsetof(pysqlite_Cursor, rowcount), PYSQLITE_READONLY},
    {NULL}
};

static PyGetSetDef cursor_getset[] = {
    {"arraysize", (getter)cursor_get_arraysize, (setter)cursor_set_arraysize, NULL},
    {"row_factory", (getter)cursor_get_row_factory, (setter)cursor_set_row_factory, NULL},
    {NULL}
};

PyTypeObject pysqlite_CursorType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = MODULE_NAME ".Cursor",
    .tp_basicsize = sizeof(pysqlite_Cursor),
    .tp_dealloc = (destructor)cursor_dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE | Py_TPFLAGS_HAVE_GC,
    .tp_doc = PyDoc_STR("SQLite database cursor class."),
    .tp_traverse = (traverseproc)cursor_traverse,
    .tp_clear = (inquiry)cursor_clear,
    .tp_weaklistoffset = offsetof(pysqlite_Cursor, in_weakreflist),
    .tp_iter = PyObject_SelfIter,
    .tp_iternext = (iternextfunc)cursor_iternext,
    .tp_methods = cursor_methods,
    .tp_members = cursor_members,
    .tp_getset = cursor_getset,
    .tp_init = (initproc)cursor_init,
    .tp_new = PyType_GenericNew,
};

int
pysqlite_cursor_setup_types(void)
{
    return PyType_Ready(&pysqlite_CursorType);
}
