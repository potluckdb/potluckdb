/* connection.c - the connection type
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
 * sqlite3 module of the Python version it is built for (3.10 to 3.14): the
 * autocommit attribute, blobopen(), serialize()/deserialize(), limits and
 * configuration options, iterdump(), window functions, callback contexts that
 * SQLite owns, an LRU statement cache, garbage-collector support, and the
 * standard library's argument handling, deprecation warnings and messages.
 * pysqlite3-only extras (open_blob, set_busy_handler, set_busy_timeout,
 * encryption keys, the flags and vfs arguments) are removed.
 */

#include "connection.h"
#include "statement.h"
#include "cursor.h"
#include "blob.h"
#include "prepare_protocol.h"
#include "util.h"

#include <stdbool.h>

/* ---------------------------------------------------------------------- */
/* Callback contexts                                                       */

static pysqlite_callback_context *
create_callback_context(PyObject *callable)
{
    pysqlite_callback_context *ctx = PyMem_Malloc(sizeof(*ctx));
    if (ctx == NULL) {
        PyErr_NoMemory();
        return NULL;
    }
    ctx->callable = Py_NewRef(callable);
    ctx->refcount = 1;
    return ctx;
}

static inline void
incref_callback_context(pysqlite_callback_context *ctx)
{
    ctx->refcount++;
}

static inline void
decref_callback_context(pysqlite_callback_context *ctx)
{
    if (--ctx->refcount == 0) {
        Py_XDECREF(ctx->callable);
        PyMem_Free(ctx);
    }
}

/* Replaces *slot with ctx, dropping the reference held for the old one. */
static void
set_callback_context(pysqlite_callback_context **slot, pysqlite_callback_context *ctx)
{
    pysqlite_callback_context *old = *slot;
    *slot = ctx;
    if (old != NULL) {
        decref_callback_context(old);
    }
}

/* SQLite drops a function, aggregate or collation; may run without the GIL. */
static void
destructor_callback(void *ctx)
{
    if (ctx != NULL) {
        PyGILState_STATE gil = PyGILState_Ensure();
        decref_callback_context((pysqlite_callback_context *)ctx);
        PyGILState_Release(gil);
    }
}

/* With enable_callback_tracebacks(True), report the exception raised by a
 * callback through sys.unraisablehook; otherwise discard it. */
static void
print_or_clear_traceback(pysqlite_callback_context *ctx)
{
    if (pysqlite_get_state()->enable_callback_tracebacks) {
        pysqlite_write_unraisable("Exception ignored on sqlite3 callback %R", ctx->callable);
    }
    else {
        PyErr_Clear();
    }
}

/* ---------------------------------------------------------------------- */
/* Helpers                                                                 */

static int
exec_simple(pysqlite_Connection *self, const char *sql)
{
    int rc;
    Py_BEGIN_ALLOW_THREADS
    sqlite3_stmt *stmt;
    rc = sqlite3_prepare_v2(self->db, sql, (int)strlen(sql) + 1, &stmt, NULL);
    if (rc == SQLITE_OK) {
        (void)sqlite3_step(stmt);
        rc = sqlite3_finalize(stmt);
    }
    Py_END_ALLOW_THREADS
    if (rc != SQLITE_OK) {
        pysqlite_set_error_from_db(self->db);
        return -1;
    }
    return 0;
}

static const char *
isolation_level_from_str(const char *level)
{
    static const char *const levels[] = {"", "DEFERRED", "IMMEDIATE", "EXCLUSIVE", NULL};
    for (int i = 0; levels[i] != NULL; i++) {
        if (sqlite3_stricmp(level, levels[i]) == 0) {
            return levels[i];
        }
    }
    PyErr_SetString(PyExc_ValueError,
                    "isolation_level string must be '', 'DEFERRED', "
                    "'IMMEDIATE', or 'EXCLUSIVE'");
    return NULL;
}

/* O& converter: None or one of the isolation level strings. */
static int
isolation_level_converter(PyObject *value, const char **result)
{
    if (value == Py_None) {
        *result = NULL;
        return 1;
    }
    if (!PyUnicode_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "isolation_level must be str or None");
        return 0;
    }
    const char *str = pysqlite_utf8_no_nul(value);
    if (str == NULL) {
        return 0;
    }
    const char *level = isolation_level_from_str(str);
    if (level == NULL) {
        return 0;
    }
    *result = level;
    return 1;
}

static int
autocommit_converter(PyObject *value, enum autocommit_mode *result)
{
    if (value == Py_True) {
        *result = AUTOCOMMIT_ENABLED;
        return 1;
    }
    if (value == Py_False) {
        *result = AUTOCOMMIT_DISABLED;
        return 1;
    }
    if (PyLong_Check(value)) {
        int overflow;
        long v = PyLong_AsLongAndOverflow(value, &overflow);
        if (v == -1 && PyErr_Occurred()) {
            return 0;
        }
        if (!overflow && v == LEGACY_TRANSACTION_CONTROL) {
            *result = AUTOCOMMIT_LEGACY;
            return 1;
        }
    }
    PyErr_SetString(PyExc_ValueError,
                    "autocommit must be True, False, or "
                    "sqlite3.LEGACY_TRANSACTION_CONTROL");
    return 0;
}

static int
int64_converter(PyObject *value, sqlite3_int64 *result)
{
    if (!PyLong_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "expected 'int'");
        return 0;
    }
    *result = pysqlite_long_as_int64(value);
    return !(*result == -1 && PyErr_Occurred());
}

/* The statement cache is functools.lru_cache(maxsize)(factory), where
 * factory(sql) prepares a statement on this connection. The factory refers to
 * the connection (which owns the cache) only weakly, so the cache makes no
 * reference cycle: a connection nobody refers to any more is closed at once
 * (as with Python 3.10's sqlite3), not at the next garbage collection.
 */
typedef struct {
    PyObject_HEAD
    PyObject *connection;  /* weak reference */
} statement_factory;

static PyObject *connection_call(pysqlite_Connection *self, PyObject *args, PyObject *kwargs);

static PyObject *
statement_factory_call(statement_factory *self, PyObject *args, PyObject *kwargs)
{
    PyObject *connection;
    int alive = pysqlite_weakref_get_ref(self->connection, &connection);
    if (alive < 0) {
        return NULL;
    }
    if (alive == 0) {
        PyErr_SetString(pysqlite_get_state()->ProgrammingError,
                        "Cannot operate on a closed database.");
        return NULL;
    }
    PyObject *statement = connection_call((pysqlite_Connection *)connection, args, kwargs);
    Py_DECREF(connection);
    return statement;
}

static void
statement_factory_dealloc(statement_factory *self)
{
    Py_XDECREF(self->connection);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

static PyTypeObject statement_factory_type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = MODULE_NAME ".StatementFactory",
    .tp_basicsize = sizeof(statement_factory),
    .tp_dealloc = (destructor)statement_factory_dealloc,
    .tp_call = (ternaryfunc)statement_factory_call,
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_DISALLOW_INSTANTIATION,
};

static PyObject *
new_statement_cache(pysqlite_Connection *self, int maxsize)
{
    PyObject *size = PyLong_FromLong(maxsize);
    if (size == NULL) {
        return NULL;
    }
    PyObject *decorator = PyObject_CallOneArg(pysqlite_get_state()->lru_cache, size);
    Py_DECREF(size);
    if (decorator == NULL) {
        return NULL;
    }
    statement_factory *factory = PyObject_New(statement_factory, &statement_factory_type);
    if (factory == NULL) {
        Py_DECREF(decorator);
        return NULL;
    }
    factory->connection = PyWeakref_NewRef((PyObject *)self, NULL);
    if (factory->connection == NULL) {
        Py_DECREF(factory);
        Py_DECREF(decorator);
        return NULL;
    }
    PyObject *cache = PyObject_CallOneArg(decorator, (PyObject *)factory);
    Py_DECREF(factory);
    Py_DECREF(decorator);
    return cache;
}

int
pysqlite_check_thread(pysqlite_Connection *self)
{
    if (self->check_same_thread && PyThread_get_thread_ident() != self->thread_ident) {
        PyErr_Format(pysqlite_get_state()->ProgrammingError,
                     "SQLite objects created in a thread can only be used in that same thread. "
                     "The object was created in thread id %lu and this is thread id %lu.",
                     self->thread_ident, PyThread_get_thread_ident());
        return 0;
    }
    return 1;
}

int
pysqlite_check_connection(pysqlite_Connection *con)
{
    if (!con->initialized) {
        PyErr_SetString(pysqlite_get_state()->ProgrammingError,
                        "Base Connection.__init__ not called.");
        return 0;
    }
    if (con->db == NULL) {
        PyErr_SetString(pysqlite_get_state()->ProgrammingError,
                        "Cannot operate on a closed database.");
        return 0;
    }
    return 1;
}

#define CHECK_THREAD_AND_CONNECTION(self, failure)                         \
    do {                                                                   \
        if (!pysqlite_check_thread(self) || !pysqlite_check_connection(self)) { \
            return failure;                                                \
        }                                                                  \
    } while (0)

static void
remove_callbacks(sqlite3 *db)
{
    (void)sqlite3_trace_v2(db, SQLITE_TRACE_STMT, NULL, NULL);
    sqlite3_progress_handler(db, 0, NULL, NULL);
    (void)sqlite3_set_authorizer(db, NULL, NULL);
}

static void
free_callback_contexts(pysqlite_Connection *self)
{
    set_callback_context(&self->trace_ctx, NULL);
    set_callback_context(&self->progress_ctx, NULL);
    set_callback_context(&self->authorizer_ctx, NULL);
}

/* Closes the database (rolling back first if autocommit is False). */
static int
connection_close(pysqlite_Connection *self)
{
    if (self->db == NULL) {
        return 0;
    }
    int rc = 0;
    if (self->autocommit == AUTOCOMMIT_DISABLED && !sqlite3_get_autocommit(self->db)) {
        if (exec_simple(self, "ROLLBACK") < 0) {
            rc = -1;
        }
    }

    sqlite3 *db = self->db;
    self->db = NULL;
    remove_callbacks(db);
    Py_BEGIN_ALLOW_THREADS
    /* With a valid handle, close_v2 always succeeds; statements still held by
     * cursors keep the database open until they are finalized. */
    (void)sqlite3_close_v2(db);
    Py_END_ALLOW_THREADS

    free_callback_contexts(self);
    return rc;
}

/* ---------------------------------------------------------------------- */
/* Construction and destruction                                            */

static int
connection_traverse(pysqlite_Connection *self, visitproc visit, void *arg)
{
    Py_VISIT(self->statement_cache);
    Py_VISIT(self->cursors);
    Py_VISIT(self->blobs);
    Py_VISIT(self->row_factory);
    Py_VISIT(self->text_factory);
    if (self->trace_ctx) Py_VISIT(self->trace_ctx->callable);
    if (self->progress_ctx) Py_VISIT(self->progress_ctx->callable);
    if (self->authorizer_ctx) Py_VISIT(self->authorizer_ctx->callable);
    return 0;
}

static int
connection_clear(pysqlite_Connection *self)
{
    Py_CLEAR(self->statement_cache);
    Py_CLEAR(self->cursors);
    Py_CLEAR(self->blobs);
    Py_CLEAR(self->row_factory);
    Py_CLEAR(self->text_factory);
    return 0;
}

static int
connection_init(pysqlite_Connection *self, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {
        "database", "timeout", "detect_types", "isolation_level",
        "check_same_thread", "factory", "cached_statements", "uri",
        "autocommit", NULL
    };
    PyObject *database;
    double timeout = 5.0;
    int detect_types = 0;
    const char *isolation_level = "";
    int check_same_thread = 1;
    PyObject *factory = NULL;
#if PYSQLITE_PY311
    int cache_size = 128;
#else
    int cache_size = 100;
#endif
    int uri = 0;
    enum autocommit_mode autocommit = AUTOCOMMIT_LEGACY;

#if PYSQLITE_PY313
    Py_ssize_t nargs = PyTuple_GET_SIZE(args);
    if (nargs > 1 && nargs <= 8) {
        if (PyErr_WarnEx(PyExc_DeprecationWarning,
                "Passing more than 1 positional argument to _sqlite3.Connection()"
                " is deprecated. Parameters 'timeout', 'detect_types', "
                "'isolation_level', 'check_same_thread', 'factory', "
                "'cached_statements' and 'uri' will become keyword-only "
                "parameters in Python 3.15.", 1)) {
            return -1;
        }
    }
#endif
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|diO&pOip$O&:Connection", kwlist,
                                     &database, &timeout, &detect_types,
                                     isolation_level_converter, &isolation_level,
                                     &check_same_thread, &factory, &cache_size, &uri,
                                     autocommit_converter, &autocommit)) {
        return -1;
    }

    if (PySys_Audit("sqlite3.connect", "O", database) < 0) {
        return -1;
    }

    PyObject *bytes;
    if (!PyUnicode_FSConverter(database, &bytes)) {
        return -1;
    }

    if (self->initialized) {
        /* Re-initialisation: drop everything of the old database first. */
        self->initialized = 0;
        pysqlite_close_all_blobs(self);
        if (connection_close(self) < 0) {
            Py_DECREF(bytes);
            return -1;
        }
        connection_clear(self);
    }

    sqlite3 *db = NULL;
    int rc;
    Py_BEGIN_ALLOW_THREADS
    rc = sqlite3_open_v2(PyBytes_AS_STRING(bytes), &db,
                         SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE |
                         (uri ? SQLITE_OPEN_URI : 0), NULL);
    if (rc == SQLITE_OK) {
        (void)sqlite3_busy_timeout(db, (int)(timeout * 1000));
    }
    Py_END_ALLOW_THREADS
    Py_DECREF(bytes);

    if (db == NULL && rc == SQLITE_NOMEM) {
        PyErr_NoMemory();
        return -1;
    }
    if (rc != SQLITE_OK) {
        pysqlite_set_error_from_db(db);
        goto error;
    }

    PyObject *statement_cache = new_statement_cache(self, cache_size);
    if (statement_cache == NULL) {
        goto error;
    }
    PyObject *cursors = PyList_New(0);
    PyObject *blobs = PyList_New(0);
    if (cursors == NULL || blobs == NULL) {
        Py_DECREF(statement_cache);
        Py_XDECREF(cursors);
        Py_XDECREF(blobs);
        goto error;
    }

    pysqlite_state *state = pysqlite_get_state();
    self->db = db;
    self->detect_types = detect_types;
    self->isolation_level = isolation_level;
    self->autocommit = autocommit;
    self->check_same_thread = check_same_thread;
    self->thread_ident = PyThread_get_thread_ident();
    Py_XSETREF(self->statement_cache, statement_cache);
    Py_XSETREF(self->cursors, cursors);
    Py_XSETREF(self->blobs, blobs);
    self->created_cursors = 0;
    Py_XSETREF(self->row_factory, Py_NewRef(Py_None));
    Py_XSETREF(self->text_factory, Py_NewRef((PyObject *)&PyUnicode_Type));
    self->trace_ctx = NULL;
    self->progress_ctx = NULL;
    self->authorizer_ctx = NULL;

    self->Warning = state->Warning;
    self->Error = state->Error;
    self->InterfaceError = state->InterfaceError;
    self->DatabaseError = state->DatabaseError;
    self->DataError = state->DataError;
    self->OperationalError = state->OperationalError;
    self->IntegrityError = state->IntegrityError;
    self->InternalError = state->InternalError;
    self->ProgrammingError = state->ProgrammingError;
    self->NotSupportedError = state->NotSupportedError;

    if (PySys_Audit("sqlite3.connect/handle", "O", self) < 0) {
        return -1;  /* dealloc cleans up */
    }

    self->initialized = 1;

    if (autocommit == AUTOCOMMIT_DISABLED) {
        if (exec_simple(self, "BEGIN") < 0) {
            return -1;
        }
    }
    return 0;

error:
    /* No statements exist yet, so this closes the database right away. */
    (void)sqlite3_close(db);
    return -1;
}

static void
connection_finalize(pysqlite_Connection *self)
{
    PyObject *exc = pysqlite_get_raised();

    /* At interpreter shutdown, never call back into Python. */
    int teardown = pysqlite_is_finalizing();
    if (teardown && self->db) {
        remove_callbacks(self->db);
    }
#if PYSQLITE_PY313
    if (self->db) {
        if (PyErr_ResourceWarning((PyObject *)self, 1, "unclosed database in %R", self)) {
            if (PyErr_ExceptionMatches(PyExc_Warning)) {
                PyErr_WriteUnraisable((PyObject *)self);
            }
            PyErr_Clear();
        }
    }
#endif
    if (connection_close(self) < 0) {
        if (teardown) {
            PyErr_Clear();
        }
        else {
            PyErr_WriteUnraisable((PyObject *)self);
        }
    }
    pysqlite_set_raised(exc);
}

static void
connection_dealloc(pysqlite_Connection *self)
{
    if (PyObject_CallFinalizerFromDealloc((PyObject *)self) < 0) {
        return;  /* resurrected */
    }
    PyObject_GC_UnTrack(self);
    if (self->in_weakreflist != NULL) {
        PyObject_ClearWeakRefs((PyObject *)self);
    }
    connection_clear(self);
    free_callback_contexts(self);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

/* ---------------------------------------------------------------------- */
/* Cursors, blobs, closing, transactions                                   */

static int
drop_unused_cursor_references(pysqlite_Connection *self)
{
    if (self->created_cursors++ < 200) {
        return 0;
    }
    self->created_cursors = 0;

    PyObject *alive = PyList_New(0);
    if (alive == NULL) {
        return -1;
    }
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(self->cursors); i++) {
        PyObject *ref = PyList_GET_ITEM(self->cursors, i);
        PyObject *obj;
        int r = pysqlite_weakref_get_ref(ref, &obj);
        if (r < 0) {
            Py_DECREF(alive);
            return -1;
        }
        if (r == 0) {
            continue;
        }
        Py_DECREF(obj);
        if (PyList_Append(alive, ref) < 0) {
            Py_DECREF(alive);
            return -1;
        }
    }
    Py_SETREF(self->cursors, alive);
    return 0;
}

PyObject *
pysqlite_connection_cursor_new(pysqlite_Connection *self, PyObject *factory)
{
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    if (factory == NULL) {
        factory = (PyObject *)&pysqlite_CursorType;
    }
    PyObject *cursor = PyObject_CallOneArg(factory, (PyObject *)self);
    if (cursor == NULL) {
        return NULL;
    }
    if (!PyObject_TypeCheck(cursor, &pysqlite_CursorType)) {
        PyErr_Format(PyExc_TypeError, "factory must return a cursor, not %.100s",
                     Py_TYPE(cursor)->tp_name);
        Py_DECREF(cursor);
        return NULL;
    }
    if (drop_unused_cursor_references(self) < 0) {
        Py_DECREF(cursor);
        return NULL;
    }
    if (self->row_factory != Py_None) {
        Py_XSETREF(((pysqlite_Cursor *)cursor)->row_factory, Py_NewRef(self->row_factory));
    }
    return cursor;
}

static PyObject *
connection_cursor(pysqlite_Connection *self, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"factory", NULL};
    PyObject *factory = NULL;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|O:cursor", kwlist, &factory)) {
        return NULL;
    }
    return pysqlite_connection_cursor_new(self, factory);
}

static PyObject *
connection_blobopen(pysqlite_Connection *self, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"", "", "", "readonly", "name", NULL};
    const char *table, *column, *name = "main";
    sqlite3_int64 row;
    int readonly = 0;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "ssO&|$ps:blobopen", kwlist,
                                     &table, &column, int64_converter, &row,
                                     &readonly, &name)) {
        return NULL;
    }
    CHECK_THREAD_AND_CONNECTION(self, NULL);

    sqlite3_blob *blob;
    int rc;
    Py_BEGIN_ALLOW_THREADS
    rc = sqlite3_blob_open(self->db, name, table, column, row, !readonly, &blob);
    Py_END_ALLOW_THREADS
    if (rc == SQLITE_MISUSE) {
        pysqlite_set_error_from_code(rc);
        return NULL;
    }
    if (rc != SQLITE_OK) {
        pysqlite_set_error_from_db(self->db);
        return NULL;
    }
    return pysqlite_blob_new(self, blob);
}

static PyObject *
connection_close_method(pysqlite_Connection *self, PyObject *Py_UNUSED(ignored))
{
    if (!pysqlite_check_thread(self)) {
        return NULL;
    }
    if (!self->initialized) {
        PyErr_SetString(pysqlite_get_state()->ProgrammingError,
                        "Base Connection.__init__ not called.");
        return NULL;
    }
    pysqlite_close_all_blobs(self);
    Py_CLEAR(self->statement_cache);
    if (connection_close(self) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
connection_commit(pysqlite_Connection *self, PyObject *Py_UNUSED(ignored))
{
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    if (self->autocommit == AUTOCOMMIT_LEGACY) {
        if (!sqlite3_get_autocommit(self->db) && exec_simple(self, "COMMIT") < 0) {
            return NULL;
        }
    }
    else if (self->autocommit == AUTOCOMMIT_DISABLED) {
        if (exec_simple(self, "COMMIT") < 0 || exec_simple(self, "BEGIN") < 0) {
            return NULL;
        }
    }
    Py_RETURN_NONE;
}

static PyObject *
connection_rollback(pysqlite_Connection *self, PyObject *Py_UNUSED(ignored))
{
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    if (self->autocommit == AUTOCOMMIT_LEGACY) {
        if (!sqlite3_get_autocommit(self->db) && exec_simple(self, "ROLLBACK") < 0) {
            return NULL;
        }
    }
    else if (self->autocommit == AUTOCOMMIT_DISABLED) {
        if (exec_simple(self, "ROLLBACK") < 0 || exec_simple(self, "BEGIN") < 0) {
            return NULL;
        }
    }
    Py_RETURN_NONE;
}

/* ---------------------------------------------------------------------- */
/* User-defined functions, aggregates and window functions                 */

static int
set_result(sqlite3_context *context, PyObject *value)
{
    if (value == Py_None) {
        sqlite3_result_null(context);
    }
    else if (PyLong_Check(value)) {
        sqlite_int64 v = pysqlite_long_as_int64(value);
        if (v == -1 && PyErr_Occurred()) {
            return -1;
        }
        sqlite3_result_int64(context, v);
    }
    else if (PyFloat_Check(value)) {
        double v = PyFloat_AsDouble(value);
        if (v == -1 && PyErr_Occurred()) {
            return -1;
        }
        sqlite3_result_double(context, v);
    }
    else if (PyUnicode_Check(value)) {
        Py_ssize_t size;
        const char *str = PyUnicode_AsUTF8AndSize(value, &size);
        if (str == NULL) {
            return -1;
        }
        if (size > INT_MAX) {
            PyErr_SetString(PyExc_OverflowError, "string is longer than INT_MAX bytes");
            return -1;
        }
        sqlite3_result_text(context, str, (int)size, SQLITE_TRANSIENT);
    }
    else if (PyObject_CheckBuffer(value)) {
        Py_buffer view;
        if (PyObject_GetBuffer(value, &view, PyBUF_SIMPLE) != 0) {
            return -1;
        }
        if (view.len > INT_MAX) {
            PyErr_SetString(PyExc_OverflowError, "BLOB longer than INT_MAX bytes");
            PyBuffer_Release(&view);
            return -1;
        }
        sqlite3_result_blob(context, view.buf, (int)view.len, SQLITE_TRANSIENT);
        PyBuffer_Release(&view);
    }
    else {
        PyErr_Format(pysqlite_get_state()->ProgrammingError,
                     "User-defined functions cannot return '%s' values to SQLite",
                     Py_TYPE(value)->tp_name);
        return -1;
    }
    return 0;
}

static PyObject *
build_py_params(sqlite3_context *context, int argc, sqlite3_value **argv)
{
    PyObject *args = PyTuple_New(argc);
    if (args == NULL) {
        return NULL;
    }
    sqlite3 *db = sqlite3_context_db_handle(context);
    for (int i = 0; i < argc; i++) {
        sqlite3_value *value = argv[i];
        PyObject *item;
        switch (sqlite3_value_type(value)) {
            case SQLITE_INTEGER:
                item = PyLong_FromLongLong(sqlite3_value_int64(value));
                break;
            case SQLITE_FLOAT:
                item = PyFloat_FromDouble(sqlite3_value_double(value));
                break;
            case SQLITE_TEXT: {
                const char *text = (const char *)sqlite3_value_text(value);
                if (text == NULL && sqlite3_errcode(db) == SQLITE_NOMEM) {
                    PyErr_NoMemory();
                    goto error;
                }
                item = PyUnicode_FromStringAndSize(text, sqlite3_value_bytes(value));
                break;
            }
            case SQLITE_BLOB: {
                const void *blob = sqlite3_value_blob(value);
                if (blob == NULL && sqlite3_errcode(db) == SQLITE_NOMEM) {
                    PyErr_NoMemory();
                    goto error;
                }
                item = PyBytes_FromStringAndSize(blob, sqlite3_value_bytes(value));
                break;
            }
            default:
                item = Py_NewRef(Py_None);
        }
        if (item == NULL) {
            goto error;
        }
        PyTuple_SET_ITEM(args, i, item);
    }
    return args;

error:
    Py_DECREF(args);
    return NULL;
}

/* Turns the Python exception into an SQLite error for the statement. */
static void
set_sqlite_error(sqlite3_context *context, const char *message)
{
#if PYSQLITE_PY311
    if (PyErr_ExceptionMatches(PyExc_MemoryError)) {
        sqlite3_result_error_nomem(context);
    }
    else if (PyErr_ExceptionMatches(PyExc_OverflowError)) {
        sqlite3_result_error_toobig(context);
    }
    else
#endif
    {
        sqlite3_result_error(context, message, -1);
    }
    print_or_clear_traceback((pysqlite_callback_context *)sqlite3_user_data(context));
}

static void
func_callback(sqlite3_context *context, int argc, sqlite3_value **argv)
{
    PyGILState_STATE gil = PyGILState_Ensure();
    pysqlite_callback_context *ctx = sqlite3_user_data(context);
    incref_callback_context(ctx);

    PyObject *result = NULL;
    PyObject *args = build_py_params(context, argc, argv);
    if (args != NULL) {
        result = PyObject_CallObject(ctx->callable, args);
        Py_DECREF(args);
    }
    int ok = 0;
    if (result != NULL) {
        ok = set_result(context, result) == 0;
        Py_DECREF(result);
    }
    if (!ok) {
        set_sqlite_error(context, "user-defined function raised exception");
    }

    decref_callback_context(ctx);
    PyGILState_Release(gil);
}

static void
step_callback(sqlite3_context *context, int argc, sqlite3_value **params)
{
    PyGILState_STATE gil = PyGILState_Ensure();
    pysqlite_callback_context *ctx = sqlite3_user_data(context);
    incref_callback_context(ctx);
    PyObject *step = NULL;

    PyObject **instance = sqlite3_aggregate_context(context, sizeof(PyObject *));
    if (instance == NULL) {
        (void)PyErr_NoMemory();
        set_sqlite_error(context, "unable to allocate SQLite aggregate context");
        goto exit;
    }
    if (*instance == NULL) {
        *instance = PyObject_CallNoArgs(ctx->callable);
        if (*instance == NULL) {
            set_sqlite_error(context, "user-defined aggregate's '__init__' method raised error");
            goto exit;
        }
    }

    step = PyObject_GetAttr(*instance, pysqlite_get_state()->str_step);
    if (step == NULL) {
#if PYSQLITE_PY311
        set_sqlite_error(context, "user-defined aggregate's 'step' method not defined");
#endif
        /* Python 3.10 leaves the AttributeError for execute() to raise. */
        goto exit;
    }
    PyObject *args = build_py_params(context, argc, params);
    if (args == NULL) {
        goto exit;
    }
    PyObject *result = PyObject_CallObject(step, args);
    Py_DECREF(args);
    if (result == NULL) {
        set_sqlite_error(context, "user-defined aggregate's 'step' method raised error");
    }
    Py_XDECREF(result);

exit:
    Py_XDECREF(step);
    decref_callback_context(ctx);
    PyGILState_Release(gil);
}

static void
final_callback(sqlite3_context *context)
{
    PyGILState_STATE gil = PyGILState_Ensure();

    PyObject **instance = sqlite3_aggregate_context(context, 0);
    if (instance == NULL || *instance == NULL) {
        /* No rows (step never called), or __init__ failed. */
        goto exit;
    }

    /* Keep the exception (if any) of the last step, value or inverse call. */
    PyObject *exc = pysqlite_get_raised();

    pysqlite_callback_context *ctx = sqlite3_user_data(context);
    incref_callback_context(ctx);
    PyObject *result = PyObject_CallMethodNoArgs(*instance, pysqlite_get_state()->str_finalize);
    Py_CLEAR(*instance);

    int ok = 0;
    if (result != NULL) {
        ok = set_result(context, result) == 0;
        Py_DECREF(result);
    }
    if (!ok) {
#if PYSQLITE_PY311
        int attr_err = PyErr_ExceptionMatches(PyExc_AttributeError);
#else
        int attr_err = 0;
#endif
        pysqlite_chain_exceptions(exc);
        /* SQLite does not report errors from the final callback to
         * sqlite3_step(), so execute() does not raise for them. */
        set_sqlite_error(context, attr_err
                         ? "user-defined aggregate's 'finalize' method not defined"
                         : "user-defined aggregate's 'finalize' method raised error");
    }
    else {
        pysqlite_set_raised(exc);
    }
    decref_callback_context(ctx);

exit:
    PyGILState_Release(gil);
}

static void
inverse_callback(sqlite3_context *context, int argc, sqlite3_value **params)
{
    PyGILState_STATE gil = PyGILState_Ensure();
    pysqlite_callback_context *ctx = sqlite3_user_data(context);
    incref_callback_context(ctx);

    PyObject **instance = sqlite3_aggregate_context(context, sizeof(PyObject *));
    PyObject *method = PyObject_GetAttr(*instance, pysqlite_get_state()->str_inverse);
    if (method == NULL) {
        set_sqlite_error(context, "user-defined aggregate's 'inverse' method not defined");
        goto exit;
    }
    PyObject *args = build_py_params(context, argc, params);
    if (args == NULL) {
        set_sqlite_error(context,
                         "unable to build arguments for user-defined aggregate's "
                         "'inverse' method");
        goto exit;
    }
    PyObject *result = PyObject_CallObject(method, args);
    Py_DECREF(args);
    if (result == NULL) {
        set_sqlite_error(context, "user-defined aggregate's 'inverse' method raised error");
        goto exit;
    }
    Py_DECREF(result);

exit:
    Py_XDECREF(method);
    decref_callback_context(ctx);
    PyGILState_Release(gil);
}

static void
value_callback(sqlite3_context *context)
{
    PyGILState_STATE gil = PyGILState_Ensure();
    pysqlite_callback_context *ctx = sqlite3_user_data(context);
    incref_callback_context(ctx);

    PyObject **instance = sqlite3_aggregate_context(context, sizeof(PyObject *));
    PyObject *result = PyObject_CallMethodNoArgs(*instance, pysqlite_get_state()->str_value);
    if (result == NULL) {
        int attr_err = PyErr_ExceptionMatches(PyExc_AttributeError);
        set_sqlite_error(context, attr_err
                         ? "user-defined aggregate's 'value' method not defined"
                         : "user-defined aggregate's 'value' method raised error");
    }
    else {
        int rc = set_result(context, result);
        Py_DECREF(result);
        if (rc < 0) {
            set_sqlite_error(context,
                             "unable to set result from user-defined aggregate's "
                             "'value' method");
        }
    }

    decref_callback_context(ctx);
    PyGILState_Release(gil);
}

static int
check_num_params(pysqlite_Connection *self, int n, const char *name)
{
#if PYSQLITE_PY314
    int limit = sqlite3_limit(self->db, SQLITE_LIMIT_FUNCTION_ARG, -1);
    if (n < -1 || n > limit) {
        PyErr_Format(self->ProgrammingError, "'%s' must be between -1 and %d, not %d",
                     name, limit, n);
        return -1;
    }
#else
    /* Before Python 3.14, SQLite rejects it ("Error creating function"). */
    (void)self, (void)n, (void)name;
#endif
    return 0;
}

#if PYSQLITE_PY313
#  define WARN_KEYWORDS(args, n, message)                                   \
    do {                                                                    \
        if (PyTuple_GET_SIZE(args) < (n)                                    \
            && PyErr_WarnEx(PyExc_DeprecationWarning, message, 1) < 0) {    \
            return NULL;                                                    \
        }                                                                   \
    } while (0)
#else
#  define WARN_KEYWORDS(args, n, message) do { } while (0)
#endif

static PyObject *
connection_create_function(pysqlite_Connection *self, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"name", "narg", "func", "deterministic", NULL};
    const char *name;
    int narg;
    PyObject *func;
    int deterministic = 0;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "siO|$p:create_function", kwlist,
                                     &name, &narg, &func, &deterministic)) {
        return NULL;
    }
    WARN_KEYWORDS(args, 3,
        "Passing keyword arguments 'name', 'narg' and 'func' to "
        "_sqlite3.Connection.create_function() is deprecated. Parameters "
        "'name', 'narg' and 'func' will become positional-only in Python 3.15.");
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    if (check_num_params(self, narg, "narg") < 0) {
        return NULL;
    }

    int flags = SQLITE_UTF8 | (deterministic ? SQLITE_DETERMINISTIC : 0);
    pysqlite_callback_context *ctx = create_callback_context(func);
    if (ctx == NULL) {
        return NULL;
    }
    /* SQLite owns ctx from here on, also when the call fails. */
    int rc = sqlite3_create_function_v2(self->db, name, narg, flags, ctx,
                                        func_callback, NULL, NULL, destructor_callback);
    if (rc != SQLITE_OK) {
        PyErr_SetString(self->OperationalError, "Error creating function");
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
connection_create_window_function(pysqlite_Connection *self, PyObject *args)
{
    const char *name;
    int num_params;
    PyObject *aggregate_class;
    if (!PyArg_ParseTuple(args, "siO:create_window_function", &name, &num_params,
                          &aggregate_class)) {
        return NULL;
    }
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    if (check_num_params(self, num_params, "num_params") < 0) {
        return NULL;
    }

    int rc;
    if (aggregate_class == Py_None) {
        rc = sqlite3_create_window_function(self->db, name, num_params, SQLITE_UTF8,
                                            NULL, NULL, NULL, NULL, NULL, NULL);
    }
    else {
        pysqlite_callback_context *ctx = create_callback_context(aggregate_class);
        if (ctx == NULL) {
            return NULL;
        }
        rc = sqlite3_create_window_function(self->db, name, num_params, SQLITE_UTF8, ctx,
                                            step_callback, final_callback,
                                            value_callback, inverse_callback,
                                            destructor_callback);
    }
    if (rc != SQLITE_OK) {
        /* The error is not set on the connection; use the result code. */
#if PYSQLITE_PY314
        pysqlite_set_error_from_code(rc);
#else
        PyErr_SetString(self->ProgrammingError, sqlite3_errstr(rc));
#endif
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
connection_create_aggregate(pysqlite_Connection *self, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"name", "n_arg", "aggregate_class", NULL};
    const char *name;
    int n_arg;
    PyObject *aggregate_class;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "siO:create_aggregate", kwlist,
                                     &name, &n_arg, &aggregate_class)) {
        return NULL;
    }
    WARN_KEYWORDS(args, 3,
        "Passing keyword arguments 'name', 'n_arg' and 'aggregate_class' "
        "to _sqlite3.Connection.create_aggregate() is deprecated. "
        "Parameters 'name', 'n_arg' and 'aggregate_class' will become "
        "positional-only in Python 3.15.");
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    if (check_num_params(self, n_arg, "n_arg") < 0) {
        return NULL;
    }

    pysqlite_callback_context *ctx = create_callback_context(aggregate_class);
    if (ctx == NULL) {
        return NULL;
    }
    int rc = sqlite3_create_function_v2(self->db, name, n_arg, SQLITE_UTF8, ctx,
                                        NULL, step_callback, final_callback,
                                        destructor_callback);
    if (rc != SQLITE_OK) {
        PyErr_SetString(self->OperationalError, "Error creating aggregate");
        return NULL;
    }
    Py_RETURN_NONE;
}

/* ---------------------------------------------------------------------- */
/* Authorizer, progress handler, trace callback                            */

static int
authorizer_callback(void *ctx_vp, int action, const char *arg1, const char *arg2,
                    const char *dbname, const char *source)
{
    PyGILState_STATE gil = PyGILState_Ensure();
    pysqlite_callback_context *ctx = ctx_vp;
    incref_callback_context(ctx);

    int rc = SQLITE_DENY;
    PyObject *ret = PyObject_CallFunction(ctx->callable, "issss", action, arg1, arg2,
                                          dbname, source);
    if (ret == NULL) {
        print_or_clear_traceback(ctx);
    }
    else {
        if (PyLong_Check(ret)) {
            rc = pysqlite_long_as_int(ret);
            if (rc == -1 && PyErr_Occurred()) {
                print_or_clear_traceback(ctx);
                rc = SQLITE_DENY;
            }
        }
        Py_DECREF(ret);
    }

    decref_callback_context(ctx);
    PyGILState_Release(gil);
    return rc;
}

static int
progress_callback(void *ctx_vp)
{
    PyGILState_STATE gil = PyGILState_Ensure();
    pysqlite_callback_context *ctx = ctx_vp;
    incref_callback_context(ctx);

    int rc;
    PyObject *ret = PyObject_CallNoArgs(ctx->callable);
    if (ret == NULL) {
        rc = -1;  /* abort the query */
    }
    else {
        rc = PyObject_IsTrue(ret);
        Py_DECREF(ret);
    }
    if (rc < 0) {
        print_or_clear_traceback(ctx);
    }

    decref_callback_context(ctx);
    PyGILState_Release(gil);
    return rc;
}

static int
trace_callback(unsigned int type, void *ctx_vp, void *stmt, void *sql)
{
    if (type != SQLITE_TRACE_STMT) {
        return 0;
    }
    PyGILState_STATE gil = PyGILState_Ensure();
    pysqlite_callback_context *ctx = ctx_vp;
    incref_callback_context(ctx);

    PyObject *statement = NULL;
    char *expanded = sqlite3_expanded_sql((sqlite3_stmt *)stmt);
    if (expanded == NULL) {
        sqlite3 *db = sqlite3_db_handle((sqlite3_stmt *)stmt);
        if (sqlite3_errcode(db) == SQLITE_NOMEM) {
            (void)PyErr_NoMemory();
            goto exit;
        }
        PyErr_SetString(pysqlite_get_state()->DataError,
                        "Expanded SQL string exceeds the maximum string length");
        print_or_clear_traceback(ctx);
        statement = PyUnicode_FromString((const char *)sql);  /* unexpanded */
    }
    else {
        statement = PyUnicode_FromString(expanded);
        sqlite3_free(expanded);
    }
    if (statement != NULL) {
        PyObject *ret = PyObject_CallOneArg(ctx->callable, statement);
        Py_DECREF(statement);
        Py_XDECREF(ret);
    }
    if (PyErr_Occurred()) {
        print_or_clear_traceback(ctx);
    }

exit:
    decref_callback_context(ctx);
    PyGILState_Release(gil);
    return 0;
}

static PyObject *
connection_set_authorizer(pysqlite_Connection *self, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"authorizer_callback", NULL};
    PyObject *callable;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O:set_authorizer", kwlist, &callable)) {
        return NULL;
    }
    WARN_KEYWORDS(args, 1,
        "Passing keyword argument 'authorizer_callback' to "
        "_sqlite3.Connection.set_authorizer() is deprecated. Parameter "
        "'authorizer_callback' will become positional-only in Python 3.15.");
    CHECK_THREAD_AND_CONNECTION(self, NULL);

    int rc;
    if (callable == Py_None) {
        rc = sqlite3_set_authorizer(self->db, NULL, NULL);
        set_callback_context(&self->authorizer_ctx, NULL);
    }
    else {
        pysqlite_callback_context *ctx = create_callback_context(callable);
        if (ctx == NULL) {
            return NULL;
        }
        rc = sqlite3_set_authorizer(self->db, authorizer_callback, ctx);
        set_callback_context(&self->authorizer_ctx, ctx);
    }
    if (rc != SQLITE_OK) {
        PyErr_SetString(self->OperationalError, "Error setting authorizer callback");
        set_callback_context(&self->authorizer_ctx, NULL);
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
connection_set_progress_handler(pysqlite_Connection *self, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"progress_handler", "n", NULL};
    PyObject *callable;
    int n;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "Oi:set_progress_handler", kwlist,
                                     &callable, &n)) {
        return NULL;
    }
    WARN_KEYWORDS(args, 1,
        "Passing keyword argument 'progress_handler' to "
        "_sqlite3.Connection.set_progress_handler() is deprecated. "
        "Parameter 'progress_handler' will become positional-only in "
        "Python 3.15.");
    CHECK_THREAD_AND_CONNECTION(self, NULL);

    if (callable == Py_None) {
        sqlite3_progress_handler(self->db, 0, NULL, NULL);
        set_callback_context(&self->progress_ctx, NULL);
    }
    else {
        pysqlite_callback_context *ctx = create_callback_context(callable);
        if (ctx == NULL) {
            return NULL;
        }
        sqlite3_progress_handler(self->db, n, progress_callback, ctx);
        set_callback_context(&self->progress_ctx, ctx);
    }
    Py_RETURN_NONE;
}

static PyObject *
connection_set_trace_callback(pysqlite_Connection *self, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"trace_callback", NULL};
    PyObject *callable;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O:set_trace_callback", kwlist,
                                     &callable)) {
        return NULL;
    }
    WARN_KEYWORDS(args, 1,
        "Passing keyword argument 'trace_callback' to "
        "_sqlite3.Connection.set_trace_callback() is deprecated. "
        "Parameter 'trace_callback' will become positional-only in Python 3.15.");
    CHECK_THREAD_AND_CONNECTION(self, NULL);

    if (callable == Py_None) {
        (void)sqlite3_trace_v2(self->db, SQLITE_TRACE_STMT, NULL, NULL);
        set_callback_context(&self->trace_ctx, NULL);
    }
    else {
        pysqlite_callback_context *ctx = create_callback_context(callable);
        if (ctx == NULL) {
            return NULL;
        }
        (void)sqlite3_trace_v2(self->db, SQLITE_TRACE_STMT, trace_callback, ctx);
        set_callback_context(&self->trace_ctx, ctx);
    }
    Py_RETURN_NONE;
}

/* ---------------------------------------------------------------------- */
/* Extensions                                                              */

static PyObject *
connection_enable_load_extension(pysqlite_Connection *self, PyObject *args)
{
    int onoff;
    if (!PyArg_ParseTuple(args, "p:enable_load_extension", &onoff)) {
        return NULL;
    }
    if (PySys_Audit("sqlite3.enable_load_extension", "OO", self,
                    onoff ? Py_True : Py_False) < 0) {
        return NULL;
    }
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    if (sqlite3_enable_load_extension(self->db, onoff) != SQLITE_OK) {
        PyErr_SetString(self->OperationalError, "Error enabling load extension");
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
connection_load_extension(pysqlite_Connection *self, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"", "entrypoint", NULL};
    const char *name;
    const char *entrypoint = NULL;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s|$z:load_extension", kwlist,
                                     &name, &entrypoint)) {
        return NULL;
    }
    if (PySys_Audit("sqlite3.load_extension", "Os", self, name) < 0) {
        return NULL;
    }
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    char *errmsg = NULL;
    int rc = sqlite3_load_extension(self->db, name, entrypoint, &errmsg);
    if (rc != SQLITE_OK) {
        PyErr_SetString(self->OperationalError, errmsg ? errmsg : sqlite3_errstr(rc));
        sqlite3_free(errmsg);
        return NULL;
    }
    Py_RETURN_NONE;
}

/* ---------------------------------------------------------------------- */
/* Attributes                                                              */

static PyObject *
connection_get_isolation_level(pysqlite_Connection *self, void *Py_UNUSED(closure))
{
    if (!pysqlite_check_connection(self)) {
        return NULL;
    }
    if (self->isolation_level != NULL) {
        return PyUnicode_FromString(self->isolation_level);
    }
    Py_RETURN_NONE;
}

static int
connection_set_isolation_level(pysqlite_Connection *self, PyObject *value,
                               void *Py_UNUSED(closure))
{
    if (value == NULL) {
        PyErr_SetString(PyExc_AttributeError, "cannot delete attribute");
        return -1;
    }
    if (value == Py_None) {
        self->isolation_level = NULL;
        /* COMMIT to get back to SQLite's autocommit mode */
        PyObject *res = connection_commit(self, NULL);
        if (res == NULL) {
            return -1;
        }
        Py_DECREF(res);
        return 0;
    }
    return isolation_level_converter(value, &self->isolation_level) ? 0 : -1;
}

static PyObject *
connection_get_total_changes(pysqlite_Connection *self, void *Py_UNUSED(closure))
{
    if (!pysqlite_check_connection(self)) {
        return NULL;
    }
    return PyLong_FromLong(sqlite3_total_changes(self->db));
}

static PyObject *
connection_get_in_transaction(pysqlite_Connection *self, void *Py_UNUSED(closure))
{
    if (!pysqlite_check_connection(self)) {
        return NULL;
    }
    return PyBool_FromLong(!sqlite3_get_autocommit(self->db));
}

static PyObject *
connection_get_autocommit(pysqlite_Connection *self, void *Py_UNUSED(closure))
{
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    if (self->autocommit == AUTOCOMMIT_ENABLED) {
        Py_RETURN_TRUE;
    }
    if (self->autocommit == AUTOCOMMIT_DISABLED) {
        Py_RETURN_FALSE;
    }
    return PyLong_FromLong(LEGACY_TRANSACTION_CONTROL);
}

static int
connection_set_autocommit(pysqlite_Connection *self, PyObject *value, void *Py_UNUSED(closure))
{
    if (value == NULL) {
        PyErr_SetString(PyExc_AttributeError, "cannot delete autocommit attribute");
        return -1;
    }
    CHECK_THREAD_AND_CONNECTION(self, -1);
    if (!autocommit_converter(value, &self->autocommit)) {
        return -1;
    }
    if (self->autocommit == AUTOCOMMIT_ENABLED) {
        if (!sqlite3_get_autocommit(self->db) && exec_simple(self, "COMMIT") < 0) {
            return -1;
        }
    }
    else if (self->autocommit == AUTOCOMMIT_DISABLED) {
        if (sqlite3_get_autocommit(self->db) && exec_simple(self, "BEGIN") < 0) {
            return -1;
        }
    }
    return 0;
}

static PyObject *
connection_get_row_factory(pysqlite_Connection *self, void *Py_UNUSED(closure))
{
    return Py_NewRef(self->row_factory ? self->row_factory : Py_None);
}

static int
connection_set_row_factory(pysqlite_Connection *self, PyObject *value, void *Py_UNUSED(closure))
{
    if (value == NULL) {
        PyErr_SetString(PyExc_AttributeError, "cannot delete row_factory attribute");
        return -1;
    }
    Py_XSETREF(self->row_factory, Py_NewRef(value));
    return 0;
}

static PyObject *
connection_get_text_factory(pysqlite_Connection *self, void *Py_UNUSED(closure))
{
    return Py_NewRef(self->text_factory ? self->text_factory : (PyObject *)&PyUnicode_Type);
}

static int
connection_set_text_factory(pysqlite_Connection *self, PyObject *value, void *Py_UNUSED(closure))
{
    if (value == NULL) {
        PyErr_SetString(PyExc_AttributeError, "cannot delete text_factory attribute");
        return -1;
    }
    Py_XSETREF(self->text_factory, Py_NewRef(value));
    return 0;
}

static PyObject *
connection_get_signature(PyObject *Py_UNUSED(self), void *Py_UNUSED(closure))
{
    return PyUnicode_FromString("(sql, /)");
}

/* ---------------------------------------------------------------------- */
/* Statements and execution                                                */

static PyObject *
connection_call(pysqlite_Connection *self, PyObject *args, PyObject *kwargs)
{
    PyObject *sql;
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    if (kwargs != NULL && PyDict_GET_SIZE(kwargs) != 0) {
        PyErr_SetString(PyExc_TypeError, MODULE_NAME ".Connection() takes no keyword arguments");
        return NULL;
    }
    if (!PyArg_ParseTuple(args, "U", &sql)) {
        return NULL;
    }
    return (PyObject *)pysqlite_statement_create(self, sql);
}

static PyObject *
connection_execute(pysqlite_Connection *self, PyObject *args)
{
    PyObject *sql, *parameters = NULL;
    if (!PyArg_ParseTuple(args, "U|O:execute", &sql, &parameters)) {
        return NULL;
    }
    PyObject *cursor = pysqlite_connection_cursor_new(self, NULL);
    if (cursor == NULL) {
        return NULL;
    }
    PyObject *result = pysqlite_query_execute((pysqlite_Cursor *)cursor, 0, sql, parameters);
    if (result == NULL) {
        Py_CLEAR(cursor);
    }
    Py_XDECREF(result);
    return cursor;
}

static PyObject *
connection_executemany(pysqlite_Connection *self, PyObject *args)
{
    PyObject *sql, *parameters;
    if (!PyArg_ParseTuple(args, "UO:executemany", &sql, &parameters)) {
        return NULL;
    }
    PyObject *cursor = pysqlite_connection_cursor_new(self, NULL);
    if (cursor == NULL) {
        return NULL;
    }
    PyObject *result = pysqlite_query_execute((pysqlite_Cursor *)cursor, 1, sql, parameters);
    if (result == NULL) {
        Py_CLEAR(cursor);
    }
    Py_XDECREF(result);
    return cursor;
}

static PyObject *
connection_executescript(pysqlite_Connection *self, PyObject *script)
{
    PyObject *cursor = pysqlite_connection_cursor_new(self, NULL);
    if (cursor == NULL) {
        return NULL;
    }
    PyObject *result = PyObject_CallMethodObjArgs(cursor, pysqlite_get_state()->str_executescript,
                                                  script, NULL);
    if (result == NULL) {
        Py_CLEAR(cursor);
    }
    Py_XDECREF(result);
    return cursor;
}

/* ---------------------------------------------------------------------- */
/* Collations                                                              */

static int
collation_callback(void *context, int len1, const void *data1, int len2, const void *data2)
{
    PyGILState_STATE gil = PyGILState_Ensure();
    pysqlite_callback_context *ctx = context;
    incref_callback_context(ctx);

    PyObject *s1 = NULL, *s2 = NULL, *ret = NULL;
    int result = 0;
    /* Called several times per sqlite3_step(); stop after a failure. */
    if (PyErr_Occurred()) {
        goto exit;
    }
    s1 = PyUnicode_FromStringAndSize((const char *)data1, len1);
    if (s1 == NULL) {
        goto exit;
    }
    s2 = PyUnicode_FromStringAndSize((const char *)data2, len2);
    if (s2 == NULL) {
        goto exit;
    }
    ret = PyObject_CallFunctionObjArgs(ctx->callable, s1, s2, NULL);
    if (ret == NULL) {
        goto exit;
    }
    int overflow;
    long value = PyLong_AsLongAndOverflow(ret, &overflow);
    if (value == -1 && PyErr_Occurred()) {
        PyErr_Clear();
        result = 0;
    }
    else if (overflow) {
        result = overflow;
    }
    else {
        result = (value > 0) - (value < 0);
    }

exit:
    Py_XDECREF(s1);
    Py_XDECREF(s2);
    Py_XDECREF(ret);
    decref_callback_context(ctx);
    PyGILState_Release(gil);
    return result;
}

static PyObject *
register_collation(pysqlite_Connection *self, const char *name, PyObject *callable)
{
    pysqlite_callback_context *ctx = NULL;
    int rc;
    if (callable == Py_None) {
        rc = sqlite3_create_collation_v2(self->db, name, SQLITE_UTF8, NULL, NULL, NULL);
    }
    else {
        if (!PyCallable_Check(callable)) {
            PyErr_SetString(PyExc_TypeError, "parameter must be callable");
            return NULL;
        }
        ctx = create_callback_context(callable);
        if (ctx == NULL) {
            return NULL;
        }
        rc = sqlite3_create_collation_v2(self->db, name, SQLITE_UTF8, ctx,
                                         collation_callback, destructor_callback);
    }
    if (rc != SQLITE_OK) {
        /* On failure SQLite does not call the destructor. */
        if (ctx != NULL) {
            decref_callback_context(ctx);
        }
        pysqlite_set_error_from_db(self->db);
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
connection_create_collation(pysqlite_Connection *self, PyObject *args)
{
    PyObject *callable;
#if PYSQLITE_PY311
    const char *name;
    if (!PyArg_ParseTuple(args, "sO:create_collation", &name, &callable)) {
        return NULL;
    }
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    return register_collation(self, name, callable);
#else
    /* Python 3.10: the name is upper-cased (with str.upper, whatever its
     * type) and may only hold ASCII letters, digits and underscores. */
    PyObject *name_obj;
    if (!PyArg_ParseTuple(args, "UO:create_collation", &name_obj, &callable)) {
        return NULL;
    }
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    PyObject *upper = PyObject_CallMethod((PyObject *)&PyUnicode_Type, "upper", "O", name_obj);
    if (upper == NULL) {
        return NULL;
    }
    PyObject *result = NULL;
    for (Py_ssize_t i = 0; i < PyUnicode_GET_LENGTH(upper); i++) {
        Py_UCS4 ch = PyUnicode_READ_CHAR(upper, i);
        if (!((ch >= '0' && ch <= '9') || (ch >= 'A' && ch <= 'Z') || ch == '_')) {
            PyErr_SetString(self->ProgrammingError, "invalid character in collation name");
            goto done;
        }
    }
    const char *name = PyUnicode_AsUTF8(upper);
    if (name != NULL) {
        result = register_collation(self, name, callable);
    }
done:
    Py_DECREF(upper);
    return result;
#endif
}

/* ---------------------------------------------------------------------- */
/* Misc methods                                                            */

static PyObject *
connection_interrupt(pysqlite_Connection *self, PyObject *Py_UNUSED(ignored))
{
    if (!pysqlite_check_connection(self)) {
        return NULL;
    }
    sqlite3_interrupt(self->db);
    Py_RETURN_NONE;
}

static PyObject *
connection_iterdump(pysqlite_Connection *self, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"filter", NULL};
    PyObject *filter = Py_None;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|$O:iterdump", kwlist, &filter)) {
        return NULL;
    }
    if (!pysqlite_check_connection(self)) {
        return NULL;
    }
    PyObject *iterdump = pysqlite_import_attr(MODULE_NAME ".dump", "_iterdump");
    if (iterdump == NULL) {
        if (!PyErr_Occurred()) {
            PyErr_SetString(self->OperationalError, "Failed to obtain _iterdump() reference");
        }
        return NULL;
    }
    PyObject *call_args = PyTuple_Pack(1, (PyObject *)self);
    PyObject *call_kwargs = Py_BuildValue("{sO}", "filter", filter);
    PyObject *result = NULL;
    if (call_args != NULL && call_kwargs != NULL) {
        result = PyObject_Call(iterdump, call_args, call_kwargs);
    }
    Py_XDECREF(call_args);
    Py_XDECREF(call_kwargs);
    Py_DECREF(iterdump);
    return result;
}

static PyObject *
connection_backup(pysqlite_Connection *self, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"target", "pages", "progress", "name", "sleep", NULL};
    pysqlite_Connection *target;
    int pages = -1;
    PyObject *progress = Py_None;
    const char *name = "main";
    double sleep = 0.250;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O!|$iOsd:backup", kwlist,
                                     &pysqlite_ConnectionType, &target, &pages,
                                     &progress, &name, &sleep)) {
        return NULL;
    }
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    if (!pysqlite_check_connection(target)) {
        return NULL;
    }
    if (target == self) {
        PyErr_SetString(PyExc_ValueError, "target cannot be the same connection instance");
        return NULL;
    }
    if (progress != Py_None && !PyCallable_Check(progress)) {
        PyErr_SetString(PyExc_TypeError, "progress argument must be a callable");
        return NULL;
    }
    if (pages == 0) {
        pages = -1;
    }
    int sleep_ms = (int)(sleep * 1000.0);

    sqlite3 *dest = target->db;
    sqlite3_backup *backup;
    Py_BEGIN_ALLOW_THREADS
    backup = sqlite3_backup_init(dest, "main", self->db, name);
    Py_END_ALLOW_THREADS
    if (backup == NULL) {
        pysqlite_set_error_from_db(dest);
        return NULL;
    }

    int rc;
    do {
        Py_BEGIN_ALLOW_THREADS
        rc = sqlite3_backup_step(backup, pages);
        Py_END_ALLOW_THREADS

        if (progress != Py_None) {
            int remaining = sqlite3_backup_remaining(backup);
            int pagecount = sqlite3_backup_pagecount(backup);
            PyObject *res = PyObject_CallFunction(progress, "iii", rc, remaining, pagecount);
            if (res == NULL) {
                /* The callback failed: abandon the backup. */
                Py_BEGIN_ALLOW_THREADS
                sqlite3_backup_finish(backup);
                Py_END_ALLOW_THREADS
                return NULL;
            }
            Py_DECREF(res);
        }
        if (rc == SQLITE_BUSY || rc == SQLITE_LOCKED) {
            Py_BEGIN_ALLOW_THREADS
            sqlite3_sleep(sleep_ms);
            Py_END_ALLOW_THREADS
        }
    } while (rc == SQLITE_OK || rc == SQLITE_BUSY || rc == SQLITE_LOCKED);

    Py_BEGIN_ALLOW_THREADS
    rc = sqlite3_backup_finish(backup);
    Py_END_ALLOW_THREADS
    if (rc != SQLITE_OK) {
        pysqlite_set_error_from_db(dest);
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
connection_serialize(pysqlite_Connection *self, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"name", NULL};
    const char *name = "main";
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|$s:serialize", kwlist, &name)) {
        return NULL;
    }
    CHECK_THREAD_AND_CONNECTION(self, NULL);

    /* Without copying if SQLite has the database in contiguous memory. */
    sqlite3_int64 size;
    unsigned int flags = SQLITE_SERIALIZE_NOCOPY;
    const char *data;
    Py_BEGIN_ALLOW_THREADS
    data = (const char *)sqlite3_serialize(self->db, name, &size, flags);
    if (data == NULL) {
        flags = 0;
        data = (const char *)sqlite3_serialize(self->db, name, &size, flags);
    }
    Py_END_ALLOW_THREADS
    if (data == NULL) {
        PyErr_Format(self->OperationalError, "unable to serialize '%s'", name);
        return NULL;
    }
    PyObject *result = PyBytes_FromStringAndSize(data, (Py_ssize_t)size);
    if (!(flags & SQLITE_SERIALIZE_NOCOPY)) {
        sqlite3_free((void *)data);
    }
    return result;
}

static PyObject *
connection_deserialize(pysqlite_Connection *self, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"", "name", NULL};
    Py_buffer data;
    const char *name = "main";
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s*|$s:deserialize", kwlist, &data, &name)) {
        return NULL;
    }
    if (!pysqlite_check_thread(self) || !pysqlite_check_connection(self)) {
        PyBuffer_Release(&data);
        return NULL;
    }

    /* SQLite takes ownership of a copy, may free it and may grow it. */
    sqlite3_int64 size = (sqlite3_int64)data.len;
    unsigned char *buf = sqlite3_malloc64(size ? size : 1);
    if (buf == NULL) {
        PyBuffer_Release(&data);
        return PyErr_NoMemory();
    }
    int rc;
    Py_BEGIN_ALLOW_THREADS
    memcpy(buf, data.buf, data.len);
    rc = sqlite3_deserialize(self->db, name, buf, size, size,
                             SQLITE_DESERIALIZE_FREEONCLOSE | SQLITE_DESERIALIZE_RESIZEABLE);
    Py_END_ALLOW_THREADS
    PyBuffer_Release(&data);
    if (rc != SQLITE_OK) {
        pysqlite_set_error_from_db(self->db);
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
connection_enter(pysqlite_Connection *self, PyObject *Py_UNUSED(ignored))
{
    if (!pysqlite_check_connection(self)) {
        return NULL;
    }
    return Py_NewRef((PyObject *)self);
}

static PyObject *
connection_exit(pysqlite_Connection *self, PyObject *args)
{
    PyObject *exc_type, *exc_value, *exc_tb;
    if (!PyArg_ParseTuple(args, "OOO:__exit__", &exc_type, &exc_value, &exc_tb)) {
        return NULL;
    }
    int commit = exc_type == Py_None && exc_value == Py_None && exc_tb == Py_None;
    PyObject *result = commit ? connection_commit(self, NULL) : connection_rollback(self, NULL);
    if (result == NULL) {
        if (commit) {
            /* COMMIT failed: roll back to release the database lock. */
            PyObject *exc = pysqlite_get_raised();
            result = connection_rollback(self, NULL);
            if (result == NULL) {
                pysqlite_chain_exceptions(exc);
            }
            else {
                Py_DECREF(result);
                pysqlite_set_raised(exc);
            }
        }
        return NULL;
    }
    Py_DECREF(result);
    Py_RETURN_FALSE;
}

static PyObject *
connection_setlimit(pysqlite_Connection *self, PyObject *args)
{
    int category, limit;
    if (!PyArg_ParseTuple(args, "ii:setlimit", &category, &limit)) {
        return NULL;
    }
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    int old = sqlite3_limit(self->db, category, limit);
    if (old < 0) {
        PyErr_SetString(self->ProgrammingError, "'category' is out of bounds");
        return NULL;
    }
    return PyLong_FromLong(old);
}

static PyObject *
connection_getlimit(pysqlite_Connection *self, PyObject *args)
{
    int category;
    if (!PyArg_ParseTuple(args, "i:getlimit", &category)) {
        return NULL;
    }
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    int old = sqlite3_limit(self->db, category, -1);
    if (old < 0) {
        PyErr_SetString(self->ProgrammingError, "'category' is out of bounds");
        return NULL;
    }
    return PyLong_FromLong(old);
}

static bool
is_int_config(int op)
{
    switch (op) {
        case SQLITE_DBCONFIG_ENABLE_FKEY:
        case SQLITE_DBCONFIG_ENABLE_TRIGGER:
        case SQLITE_DBCONFIG_ENABLE_FTS3_TOKENIZER:
        case SQLITE_DBCONFIG_ENABLE_LOAD_EXTENSION:
        case SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE:
        case SQLITE_DBCONFIG_ENABLE_QPSG:
        case SQLITE_DBCONFIG_TRIGGER_EQP:
        case SQLITE_DBCONFIG_RESET_DATABASE:
        case SQLITE_DBCONFIG_DEFENSIVE:
        case SQLITE_DBCONFIG_WRITABLE_SCHEMA:
        case SQLITE_DBCONFIG_DQS_DDL:
        case SQLITE_DBCONFIG_DQS_DML:
        case SQLITE_DBCONFIG_LEGACY_ALTER_TABLE:
        case SQLITE_DBCONFIG_ENABLE_VIEW:
        case SQLITE_DBCONFIG_LEGACY_FILE_FORMAT:
        case SQLITE_DBCONFIG_TRUSTED_SCHEMA:
            return true;
        default:
            return false;
    }
}

static PyObject *
connection_setconfig(pysqlite_Connection *self, PyObject *args)
{
    int op, enable = 1;
    if (!PyArg_ParseTuple(args, "i|p:setconfig", &op, &enable)) {
        return NULL;
    }
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    if (!is_int_config(op)) {
        return PyErr_Format(PyExc_ValueError, "unknown config 'op': %d", op);
    }
    int actual;
    if (sqlite3_db_config(self->db, op, enable, &actual) != SQLITE_OK) {
        pysqlite_set_error_from_db(self->db);
        return NULL;
    }
    if (enable != actual) {
        PyErr_SetString(self->OperationalError, "Unable to set config");
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
connection_getconfig(pysqlite_Connection *self, PyObject *args)
{
    int op;
    if (!PyArg_ParseTuple(args, "i:getconfig", &op)) {
        return NULL;
    }
    CHECK_THREAD_AND_CONNECTION(self, NULL);
    if (!is_int_config(op)) {
        return PyErr_Format(PyExc_ValueError, "unknown config 'op': %d", op);
    }
    int current;
    if (sqlite3_db_config(self->db, op, -1, &current) != SQLITE_OK) {
        pysqlite_set_error_from_db(self->db);
        return NULL;
    }
    return PyBool_FromLong(current);
}

/* ---------------------------------------------------------------------- */
/* Type                                                                    */

static PyGetSetDef connection_getset[] = {
    {"isolation_level", (getter)connection_get_isolation_level,
     (setter)connection_set_isolation_level},
    {"total_changes", (getter)connection_get_total_changes, NULL},
    {"in_transaction", (getter)connection_get_in_transaction, NULL},
    {"autocommit", (getter)connection_get_autocommit, (setter)connection_set_autocommit},
    {"row_factory", (getter)connection_get_row_factory, (setter)connection_set_row_factory},
    {"text_factory", (getter)connection_get_text_factory, (setter)connection_set_text_factory},
    {"__text_signature__", connection_get_signature, NULL},
    {NULL}
};

#define KW METH_VARARGS | METH_KEYWORDS
static PyMethodDef connection_methods[] = {
    {"backup", (PyCFunction)(void (*)(void))connection_backup, KW,
     PyDoc_STR("backup($self, /, target, *, pages=-1, progress=None, name='main', sleep=0.25)\n--\n\n"
               "Makes a backup of the database.")},
    {"blobopen", (PyCFunction)(void (*)(void))connection_blobopen, KW,
     PyDoc_STR("blobopen($self, table, column, rowid, /, *, readonly=False, name='main')\n--\n\n"
               "Open and return a BLOB object.")},
    {"close", (PyCFunction)connection_close_method, METH_NOARGS,
     PyDoc_STR("close($self, /)\n--\n\nClose the database connection.\n\n"
               "Any pending transaction is not committed implicitly.")},
    {"commit", (PyCFunction)connection_commit, METH_NOARGS,
     PyDoc_STR("commit($self, /)\n--\n\nCommit any pending transaction to the database.\n\n"
               "If there is no open transaction, this method is a no-op.")},
    {"create_aggregate", (PyCFunction)(void (*)(void))connection_create_aggregate, KW,
     PyDoc_STR("create_aggregate($self, /, name, n_arg, aggregate_class)\n--\n\n"
               "Creates a new aggregate.")},
    {"create_collation", (PyCFunction)connection_create_collation, METH_VARARGS,
     PyDoc_STR("create_collation($self, name, callback, /)\n--\n\nCreates a collation function.")},
    {"create_function", (PyCFunction)(void (*)(void))connection_create_function, KW,
     PyDoc_STR("create_function($self, /, name, narg, func, *, deterministic=False)\n--\n\n"
               "Creates a new function.")},
    {"create_window_function", (PyCFunction)connection_create_window_function, METH_VARARGS,
     PyDoc_STR("create_window_function($self, name, num_params, aggregate_class, /)\n--\n\n"
               "Creates or redefines an aggregate window function. Non-standard.")},
    {"cursor", (PyCFunction)(void (*)(void))connection_cursor, KW,
     PyDoc_STR("cursor($self, /, factory=<unrepresentable>)\n--\n\n"
               "Return a cursor for the connection.")},
    {"deserialize", (PyCFunction)(void (*)(void))connection_deserialize, KW,
     PyDoc_STR("deserialize($self, data, /, *, name='main')\n--\n\nLoad a serialized database.")},
    {"enable_load_extension", (PyCFunction)connection_enable_load_extension, METH_VARARGS,
     PyDoc_STR("enable_load_extension($self, enable, /)\n--\n\n"
               "Enable dynamic loading of SQLite extension modules.")},
    {"execute", (PyCFunction)connection_execute, METH_VARARGS,
     PyDoc_STR("execute($self, sql, parameters=(), /)\n--\n\nExecutes an SQL statement.")},
    {"executemany", (PyCFunction)connection_executemany, METH_VARARGS,
     PyDoc_STR("executemany($self, sql, parameters, /)\n--\n\nRepeatedly executes an SQL statement.")},
    {"executescript", (PyCFunction)connection_executescript, METH_O,
     PyDoc_STR("executescript($self, sql_script, /)\n--\n\nExecutes multiple SQL statements at once.")},
    {"getconfig", (PyCFunction)connection_getconfig, METH_VARARGS,
     PyDoc_STR("getconfig($self, op, /)\n--\n\nQuery a boolean connection configuration option.")},
    {"getlimit", (PyCFunction)connection_getlimit, METH_VARARGS,
     PyDoc_STR("getlimit($self, category, /)\n--\n\nGet connection run-time limits.")},
    {"interrupt", (PyCFunction)connection_interrupt, METH_NOARGS,
     PyDoc_STR("interrupt($self, /)\n--\n\nAbort any pending database operation.")},
    {"iterdump", (PyCFunction)(void (*)(void))connection_iterdump, KW,
     PyDoc_STR("iterdump($self, /, *, filter=None)\n--\n\n"
               "Returns iterator to the dump of the database in an SQL text format.")},
    {"load_extension", (PyCFunction)(void (*)(void))connection_load_extension, KW,
     PyDoc_STR("load_extension($self, name, /, *, entrypoint=None)\n--\n\n"
               "Load SQLite extension module.")},
    {"rollback", (PyCFunction)connection_rollback, METH_NOARGS,
     PyDoc_STR("rollback($self, /)\n--\n\nRoll back to the start of any pending transaction.\n\n"
               "If there is no open transaction, this method is a no-op.")},
    {"serialize", (PyCFunction)(void (*)(void))connection_serialize, KW,
     PyDoc_STR("serialize($self, /, *, name='main')\n--\n\nSerialize a database into a byte string.")},
    {"set_authorizer", (PyCFunction)(void (*)(void))connection_set_authorizer, KW,
     PyDoc_STR("set_authorizer($self, /, authorizer_callback)\n--\n\nSet authorizer callback.")},
    {"set_progress_handler", (PyCFunction)(void (*)(void))connection_set_progress_handler, KW,
     PyDoc_STR("set_progress_handler($self, /, progress_handler, n)\n--\n\n"
               "Set progress handler callback.")},
    {"set_trace_callback", (PyCFunction)(void (*)(void))connection_set_trace_callback, KW,
     PyDoc_STR("set_trace_callback($self, /, trace_callback)\n--\n\n"
               "Set a trace callback called for each SQL statement (passed as unicode).")},
    {"setconfig", (PyCFunction)connection_setconfig, METH_VARARGS,
     PyDoc_STR("setconfig($self, op, enable=True, /)\n--\n\n"
               "Set a boolean connection configuration option.")},
    {"setlimit", (PyCFunction)connection_setlimit, METH_VARARGS,
     PyDoc_STR("setlimit($self, category, limit, /)\n--\n\nSet connection run-time limits.")},
    {"__enter__", (PyCFunction)connection_enter, METH_NOARGS,
     PyDoc_STR("__enter__($self, /)\n--\n\nCalled when the connection is used as a context manager.")},
    {"__exit__", (PyCFunction)connection_exit, METH_VARARGS,
     PyDoc_STR("__exit__($self, type, value, traceback, /)\n--\n\n"
               "Called when the connection is used as a context manager.")},
    {NULL, NULL}
};
#undef KW

static struct PyMemberDef connection_members[] = {
    {"Warning", PYSQLITE_T_OBJECT, offsetof(pysqlite_Connection, Warning), PYSQLITE_READONLY},
    {"Error", PYSQLITE_T_OBJECT, offsetof(pysqlite_Connection, Error), PYSQLITE_READONLY},
    {"InterfaceError", PYSQLITE_T_OBJECT, offsetof(pysqlite_Connection, InterfaceError), PYSQLITE_READONLY},
    {"DatabaseError", PYSQLITE_T_OBJECT, offsetof(pysqlite_Connection, DatabaseError), PYSQLITE_READONLY},
    {"DataError", PYSQLITE_T_OBJECT, offsetof(pysqlite_Connection, DataError), PYSQLITE_READONLY},
    {"OperationalError", PYSQLITE_T_OBJECT, offsetof(pysqlite_Connection, OperationalError), PYSQLITE_READONLY},
    {"IntegrityError", PYSQLITE_T_OBJECT, offsetof(pysqlite_Connection, IntegrityError), PYSQLITE_READONLY},
    {"InternalError", PYSQLITE_T_OBJECT, offsetof(pysqlite_Connection, InternalError), PYSQLITE_READONLY},
    {"ProgrammingError", PYSQLITE_T_OBJECT, offsetof(pysqlite_Connection, ProgrammingError), PYSQLITE_READONLY},
    {"NotSupportedError", PYSQLITE_T_OBJECT, offsetof(pysqlite_Connection, NotSupportedError), PYSQLITE_READONLY},
    {NULL}
};

PyTypeObject pysqlite_ConnectionType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = MODULE_NAME ".Connection",
    .tp_basicsize = sizeof(pysqlite_Connection),
    .tp_dealloc = (destructor)connection_dealloc,
    .tp_call = (ternaryfunc)connection_call,
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE | Py_TPFLAGS_HAVE_GC,
    .tp_doc = PyDoc_STR("SQLite database connection object."),
    .tp_traverse = (traverseproc)connection_traverse,
    .tp_clear = (inquiry)connection_clear,
    .tp_weaklistoffset = offsetof(pysqlite_Connection, in_weakreflist),
    .tp_methods = connection_methods,
    .tp_members = connection_members,
    .tp_getset = connection_getset,
    .tp_init = (initproc)connection_init,
    .tp_new = PyType_GenericNew,
    .tp_finalize = (destructor)connection_finalize,
};

int
pysqlite_connection_setup_types(void)
{
    if (PyType_Ready(&statement_factory_type) < 0) {
        return -1;
    }
    return PyType_Ready(&pysqlite_ConnectionType);
}
