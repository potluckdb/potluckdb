/* module.c - the module itself
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
 * Altered for PotluckDB (see ../README.md): the module is named
 * potluckdb._sqlite3 and has the names, constants and behaviour of the standard
 * library's _sqlite3 for the Python version it is built for (error and
 * extended error codes, limit and configuration constants, threadsafety from
 * SQLite's threading mode, LEGACY_TRANSACTION_CONTROL, connect() deprecations);
 * it also exposes PotluckDB's version (core_version) and the package version.
 */

#include "connection.h"
#include "statement.h"
#include "cursor.h"
#include "prepare_protocol.h"
#include "microprotocols.h"
#include "row.h"
#include "blob.h"
#include "potluckdb.h"

#ifndef POTLUCKDB_PACKAGE_VERSION
#  define POTLUCKDB_PACKAGE_VERSION "0+unknown"
#endif

pysqlite_state pysqlite_global_state;

/* ---------------------------------------------------------------------- */
/* Module functions                                                        */

static PyObject *
module_connect(PyObject *module, PyObject *const *args, Py_ssize_t nargsf, PyObject *kwnames)
{
    Py_ssize_t nargs = PyVectorcall_NARGS(nargsf);
    PyObject *factory = (PyObject *)&pysqlite_ConnectionType;
    const Py_ssize_t factory_pos = 5;

#if PYSQLITE_PY313
    if (nargs > 1 && nargs <= 8) {
        if (PyErr_WarnEx(PyExc_DeprecationWarning,
                "Passing more than 1 positional argument to sqlite3.connect()"
                " is deprecated. Parameters 'timeout', 'detect_types', "
                "'isolation_level', 'check_same_thread', 'factory', "
                "'cached_statements' and 'uri' will become keyword-only "
                "parameters in Python 3.15.", 1)) {
            return NULL;
        }
    }
#endif
    if (nargs > factory_pos) {
        factory = args[factory_pos];
    }
    else if (kwnames != NULL) {
        for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(kwnames); i++) {
            if (PyUnicode_CompareWithASCIIString(PyTuple_GET_ITEM(kwnames, i), "factory") == 0) {
                factory = args[nargs + i];
                break;
            }
        }
    }
    return PyObject_Vectorcall(factory, args, nargsf, kwnames);
}

static PyObject *
module_complete_statement(PyObject *module, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"statement", NULL};
    const char *statement;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s:complete_statement", kwlist, &statement)) {
        return NULL;
    }
    return PyBool_FromLong(sqlite3_complete(statement));
}

#if !PYSQLITE_PY312
static PyObject *
module_enable_shared_cache(PyObject *module, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"do_enable", NULL};
    int do_enable;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "i:enable_shared_cache", kwlist, &do_enable)) {
        return NULL;
    }
    if (sqlite3_enable_shared_cache(do_enable) != SQLITE_OK) {
        PyErr_SetString(pysqlite_get_state()->OperationalError,
                        "Changing the shared_cache flag failed");
        return NULL;
    }
    Py_RETURN_NONE;
}
#endif

static PyObject *
module_register_adapter(PyObject *module, PyObject *args)
{
    PyTypeObject *type;
    PyObject *caster;
    if (!PyArg_ParseTuple(args, "OO:register_adapter", &type, &caster)) {
        return NULL;
    }
    /* Adapting a built-in type disables the fast path for those types. */
    if (type == &PyLong_Type || type == &PyFloat_Type
        || type == &PyUnicode_Type || type == &PyByteArray_Type) {
        pysqlite_get_state()->BaseTypeAdapted = 1;
    }
    if (pysqlite_microprotocols_add(type, (PyObject *)&pysqlite_PrepareProtocolType, caster) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
module_register_converter(PyObject *module, PyObject *args)
{
    PyObject *name, *callable;
    if (!PyArg_ParseTuple(args, "UO:register_converter", &name, &callable)) {
        return NULL;
    }
    PyObject *upper = PyObject_CallMethodNoArgs(name, pysqlite_get_state()->str_upper);
    if (upper == NULL) {
        return NULL;
    }
    int rc = PyDict_SetItem(pysqlite_get_state()->converters, upper, callable);
    Py_DECREF(upper);
    if (rc < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
module_enable_callback_tracebacks(PyObject *module, PyObject *args)
{
    int enable;
    if (!PyArg_ParseTuple(args, "i:enable_callback_tracebacks", &enable)) {
        return NULL;
    }
    pysqlite_get_state()->enable_callback_tracebacks = enable;
    Py_RETURN_NONE;
}

static PyObject *
module_adapt(PyObject *module, PyObject *args)
{
    PyObject *obj, *proto = (PyObject *)&pysqlite_PrepareProtocolType, *alt = NULL;
    if (!PyArg_ParseTuple(args, "O|OO:adapt", &obj, &proto, &alt)) {
        return NULL;
    }
    return pysqlite_microprotocols_adapt(obj, proto, alt);
}

static PyMethodDef module_methods[] = {
    {"adapt", (PyCFunction)module_adapt, METH_VARARGS,
     PyDoc_STR("adapt($module, obj, proto=PrepareProtocolType, alt=<unrepresentable>, /)\n--\n\n"
               "Adapt given object to given protocol.")},
    {"complete_statement", (PyCFunction)(void (*)(void))module_complete_statement,
     METH_VARARGS | METH_KEYWORDS,
     PyDoc_STR("complete_statement($module, /, statement)\n--\n\n"
               "Checks if a string contains a complete SQL statement.")},
    {"connect", (PyCFunction)(void (*)(void))module_connect, METH_FASTCALL | METH_KEYWORDS,
     PyDoc_STR("connect($module, /, database, timeout=5.0, detect_types=0,\n"
               "        isolation_level='', check_same_thread=True,\n"
               "        factory=ConnectionType, cached_statements=128, uri=False, *,\n"
               "        autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL)\n--\n\n"
               "Open a connection to the SQLite database file 'database'.\n\n"
               "You can use \":memory:\" to open a database connection to a database that\n"
               "resides in RAM instead of on disk.")},
    {"enable_callback_tracebacks", (PyCFunction)module_enable_callback_tracebacks, METH_VARARGS,
     PyDoc_STR("enable_callback_tracebacks($module, enable, /)\n--\n\n"
               "Enable or disable callback functions throwing errors to stderr.")},
#if !PYSQLITE_PY312
    {"enable_shared_cache", (PyCFunction)(void (*)(void))module_enable_shared_cache,
     METH_VARARGS | METH_KEYWORDS,
     PyDoc_STR("enable_shared_cache($module, /, do_enable)\n--\n\n"
               "Enable or disable shared cache mode for the calling thread.")},
#endif
    {"register_adapter", (PyCFunction)module_register_adapter, METH_VARARGS,
     PyDoc_STR("register_adapter($module, type, adapter, /)\n--\n\n"
               "Register a function to adapt Python objects to SQLite values.")},
    {"register_converter", (PyCFunction)module_register_converter, METH_VARARGS,
     PyDoc_STR("register_converter($module, typename, converter, /)\n--\n\n"
               "Register a function to convert SQLite values to Python objects.")},
    {NULL, NULL}
};

/* ---------------------------------------------------------------------- */
/* Constants                                                               */

static const struct {
    const char *name;
    long value;
} error_codes[] = {
#define ERROR_CODE(code) {#code, code}
    /* primary result codes */
    ERROR_CODE(SQLITE_ABORT),
    ERROR_CODE(SQLITE_AUTH),
    ERROR_CODE(SQLITE_BUSY),
    ERROR_CODE(SQLITE_CANTOPEN),
    ERROR_CODE(SQLITE_CONSTRAINT),
    ERROR_CODE(SQLITE_CORRUPT),
    ERROR_CODE(SQLITE_DONE),
    ERROR_CODE(SQLITE_EMPTY),
    ERROR_CODE(SQLITE_ERROR),
    ERROR_CODE(SQLITE_FORMAT),
    ERROR_CODE(SQLITE_FULL),
    ERROR_CODE(SQLITE_INTERNAL),
    ERROR_CODE(SQLITE_INTERRUPT),
    ERROR_CODE(SQLITE_IOERR),
    ERROR_CODE(SQLITE_LOCKED),
    ERROR_CODE(SQLITE_MISMATCH),
    ERROR_CODE(SQLITE_MISUSE),
    ERROR_CODE(SQLITE_NOLFS),
    ERROR_CODE(SQLITE_NOMEM),
    ERROR_CODE(SQLITE_NOTADB),
    ERROR_CODE(SQLITE_NOTFOUND),
    ERROR_CODE(SQLITE_OK),
    ERROR_CODE(SQLITE_PERM),
    ERROR_CODE(SQLITE_PROTOCOL),
    ERROR_CODE(SQLITE_RANGE),
    ERROR_CODE(SQLITE_READONLY),
    ERROR_CODE(SQLITE_ROW),
    ERROR_CODE(SQLITE_SCHEMA),
    ERROR_CODE(SQLITE_TOOBIG),
    ERROR_CODE(SQLITE_NOTICE),
    ERROR_CODE(SQLITE_WARNING),
    /* extended result codes */
    ERROR_CODE(SQLITE_ABORT_ROLLBACK),
    ERROR_CODE(SQLITE_BUSY_RECOVERY),
    ERROR_CODE(SQLITE_CANTOPEN_FULLPATH),
    ERROR_CODE(SQLITE_CANTOPEN_ISDIR),
    ERROR_CODE(SQLITE_CANTOPEN_NOTEMPDIR),
    ERROR_CODE(SQLITE_CORRUPT_VTAB),
    ERROR_CODE(SQLITE_IOERR_ACCESS),
    ERROR_CODE(SQLITE_IOERR_BLOCKED),
    ERROR_CODE(SQLITE_IOERR_CHECKRESERVEDLOCK),
    ERROR_CODE(SQLITE_IOERR_CLOSE),
    ERROR_CODE(SQLITE_IOERR_DELETE),
    ERROR_CODE(SQLITE_IOERR_DELETE_NOENT),
    ERROR_CODE(SQLITE_IOERR_DIR_CLOSE),
    ERROR_CODE(SQLITE_IOERR_DIR_FSYNC),
    ERROR_CODE(SQLITE_IOERR_FSTAT),
    ERROR_CODE(SQLITE_IOERR_FSYNC),
    ERROR_CODE(SQLITE_IOERR_LOCK),
    ERROR_CODE(SQLITE_IOERR_NOMEM),
    ERROR_CODE(SQLITE_IOERR_RDLOCK),
    ERROR_CODE(SQLITE_IOERR_READ),
    ERROR_CODE(SQLITE_IOERR_SEEK),
    ERROR_CODE(SQLITE_IOERR_SHMLOCK),
    ERROR_CODE(SQLITE_IOERR_SHMMAP),
    ERROR_CODE(SQLITE_IOERR_SHMOPEN),
    ERROR_CODE(SQLITE_IOERR_SHMSIZE),
    ERROR_CODE(SQLITE_IOERR_SHORT_READ),
    ERROR_CODE(SQLITE_IOERR_TRUNCATE),
    ERROR_CODE(SQLITE_IOERR_UNLOCK),
    ERROR_CODE(SQLITE_IOERR_WRITE),
    ERROR_CODE(SQLITE_LOCKED_SHAREDCACHE),
    ERROR_CODE(SQLITE_READONLY_CANTLOCK),
    ERROR_CODE(SQLITE_READONLY_RECOVERY),
    ERROR_CODE(SQLITE_CONSTRAINT_CHECK),
    ERROR_CODE(SQLITE_CONSTRAINT_COMMITHOOK),
    ERROR_CODE(SQLITE_CONSTRAINT_FOREIGNKEY),
    ERROR_CODE(SQLITE_CONSTRAINT_FUNCTION),
    ERROR_CODE(SQLITE_CONSTRAINT_NOTNULL),
    ERROR_CODE(SQLITE_CONSTRAINT_PRIMARYKEY),
    ERROR_CODE(SQLITE_CONSTRAINT_TRIGGER),
    ERROR_CODE(SQLITE_CONSTRAINT_UNIQUE),
    ERROR_CODE(SQLITE_CONSTRAINT_VTAB),
    ERROR_CODE(SQLITE_READONLY_ROLLBACK),
    ERROR_CODE(SQLITE_IOERR_MMAP),
    ERROR_CODE(SQLITE_NOTICE_RECOVER_ROLLBACK),
    ERROR_CODE(SQLITE_NOTICE_RECOVER_WAL),
    ERROR_CODE(SQLITE_BUSY_SNAPSHOT),
    ERROR_CODE(SQLITE_IOERR_GETTEMPPATH),
    ERROR_CODE(SQLITE_WARNING_AUTOINDEX),
    ERROR_CODE(SQLITE_CANTOPEN_CONVPATH),
    ERROR_CODE(SQLITE_IOERR_CONVPATH),
    ERROR_CODE(SQLITE_CONSTRAINT_ROWID),
    ERROR_CODE(SQLITE_READONLY_DBMOVED),
    ERROR_CODE(SQLITE_AUTH_USER),
    ERROR_CODE(SQLITE_IOERR_VNODE),
    ERROR_CODE(SQLITE_IOERR_AUTH),
    ERROR_CODE(SQLITE_OK_LOAD_PERMANENTLY),
    ERROR_CODE(SQLITE_IOERR_BEGIN_ATOMIC),
    ERROR_CODE(SQLITE_IOERR_COMMIT_ATOMIC),
    ERROR_CODE(SQLITE_IOERR_ROLLBACK_ATOMIC),
    ERROR_CODE(SQLITE_ERROR_MISSING_COLLSEQ),
    ERROR_CODE(SQLITE_ERROR_RETRY),
    ERROR_CODE(SQLITE_READONLY_CANTINIT),
    ERROR_CODE(SQLITE_READONLY_DIRECTORY),
    ERROR_CODE(SQLITE_CORRUPT_SEQUENCE),
    ERROR_CODE(SQLITE_LOCKED_VTAB),
    ERROR_CODE(SQLITE_CANTOPEN_DIRTYWAL),
    ERROR_CODE(SQLITE_ERROR_SNAPSHOT),
    ERROR_CODE(SQLITE_CANTOPEN_SYMLINK),
    ERROR_CODE(SQLITE_CONSTRAINT_PINNED),
    ERROR_CODE(SQLITE_OK_SYMLINK),
    ERROR_CODE(SQLITE_BUSY_TIMEOUT),
    ERROR_CODE(SQLITE_CORRUPT_INDEX),
    ERROR_CODE(SQLITE_IOERR_DATA),
    ERROR_CODE(SQLITE_IOERR_CORRUPTFS),
#undef ERROR_CODE
    {NULL, 0},
};

const char *
pysqlite_error_name(int rc)
{
    for (int i = 0; error_codes[i].name != NULL; i++) {
        if (error_codes[i].value == rc) {
            return error_codes[i].name;
        }
    }
    return NULL;
}

static const struct {
    const char *name;
    int value;
} int_constants[] = {
#define CONSTANT(c) {#c, c}
    CONSTANT(PARSE_DECLTYPES),
    CONSTANT(PARSE_COLNAMES),
    /* authorizer return values and action codes */
    CONSTANT(SQLITE_DENY),
    CONSTANT(SQLITE_IGNORE),
    CONSTANT(SQLITE_CREATE_INDEX),
    CONSTANT(SQLITE_CREATE_TABLE),
    CONSTANT(SQLITE_CREATE_TEMP_INDEX),
    CONSTANT(SQLITE_CREATE_TEMP_TABLE),
    CONSTANT(SQLITE_CREATE_TEMP_TRIGGER),
    CONSTANT(SQLITE_CREATE_TEMP_VIEW),
    CONSTANT(SQLITE_CREATE_TRIGGER),
    CONSTANT(SQLITE_CREATE_VIEW),
    CONSTANT(SQLITE_DELETE),
    CONSTANT(SQLITE_DROP_INDEX),
    CONSTANT(SQLITE_DROP_TABLE),
    CONSTANT(SQLITE_DROP_TEMP_INDEX),
    CONSTANT(SQLITE_DROP_TEMP_TABLE),
    CONSTANT(SQLITE_DROP_TEMP_TRIGGER),
    CONSTANT(SQLITE_DROP_TEMP_VIEW),
    CONSTANT(SQLITE_DROP_TRIGGER),
    CONSTANT(SQLITE_DROP_VIEW),
    CONSTANT(SQLITE_INSERT),
    CONSTANT(SQLITE_PRAGMA),
    CONSTANT(SQLITE_READ),
    CONSTANT(SQLITE_SELECT),
    CONSTANT(SQLITE_TRANSACTION),
    CONSTANT(SQLITE_UPDATE),
    CONSTANT(SQLITE_ATTACH),
    CONSTANT(SQLITE_DETACH),
    CONSTANT(SQLITE_ALTER_TABLE),
    CONSTANT(SQLITE_REINDEX),
    CONSTANT(SQLITE_ANALYZE),
    CONSTANT(SQLITE_CREATE_VTABLE),
    CONSTANT(SQLITE_DROP_VTABLE),
    CONSTANT(SQLITE_FUNCTION),
    CONSTANT(SQLITE_SAVEPOINT),
    CONSTANT(SQLITE_RECURSIVE),
    /* run-time limit categories */
    CONSTANT(SQLITE_LIMIT_LENGTH),
    CONSTANT(SQLITE_LIMIT_SQL_LENGTH),
    CONSTANT(SQLITE_LIMIT_COLUMN),
    CONSTANT(SQLITE_LIMIT_EXPR_DEPTH),
    CONSTANT(SQLITE_LIMIT_COMPOUND_SELECT),
    CONSTANT(SQLITE_LIMIT_VDBE_OP),
    CONSTANT(SQLITE_LIMIT_FUNCTION_ARG),
    CONSTANT(SQLITE_LIMIT_ATTACHED),
    CONSTANT(SQLITE_LIMIT_LIKE_PATTERN_LENGTH),
    CONSTANT(SQLITE_LIMIT_VARIABLE_NUMBER),
    CONSTANT(SQLITE_LIMIT_TRIGGER_DEPTH),
    CONSTANT(SQLITE_LIMIT_WORKER_THREADS),
    /* connection configuration options */
    CONSTANT(SQLITE_DBCONFIG_ENABLE_FKEY),
    CONSTANT(SQLITE_DBCONFIG_ENABLE_TRIGGER),
    CONSTANT(SQLITE_DBCONFIG_ENABLE_FTS3_TOKENIZER),
    CONSTANT(SQLITE_DBCONFIG_ENABLE_LOAD_EXTENSION),
    CONSTANT(SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE),
    CONSTANT(SQLITE_DBCONFIG_ENABLE_QPSG),
    CONSTANT(SQLITE_DBCONFIG_TRIGGER_EQP),
    CONSTANT(SQLITE_DBCONFIG_RESET_DATABASE),
    CONSTANT(SQLITE_DBCONFIG_DEFENSIVE),
    CONSTANT(SQLITE_DBCONFIG_WRITABLE_SCHEMA),
    CONSTANT(SQLITE_DBCONFIG_DQS_DDL),
    CONSTANT(SQLITE_DBCONFIG_DQS_DML),
    CONSTANT(SQLITE_DBCONFIG_LEGACY_ALTER_TABLE),
    CONSTANT(SQLITE_DBCONFIG_ENABLE_VIEW),
    CONSTANT(SQLITE_DBCONFIG_LEGACY_FILE_FORMAT),
    CONSTANT(SQLITE_DBCONFIG_TRUSTED_SCHEMA),
#undef CONSTANT
    {NULL, 0},
};

/* DB-API threadsafety level for SQLite's compiled-in threading mode. */
static int
get_threadsafety(void)
{
    switch (sqlite3_threadsafe()) {
        case 0:  return 0;  /* single-thread */
        case 1:  return 3;  /* serialized: share module, connections, cursors */
        case 2:  return 1;  /* multi-thread: share the module only */
        default:
            PyErr_Format(pysqlite_get_state()->InterfaceError,
                         "Unable to interpret SQLite threadsafety mode. Got %d, "
                         "expected 0, 1, or 2", sqlite3_threadsafe());
            return -1;
    }
}

/* ---------------------------------------------------------------------- */
/* Initialisation                                                          */

static struct PyModuleDef module_def = {
    PyModuleDef_HEAD_INIT,
    .m_name = "_sqlite3",
    .m_doc = "PotluckDB's build of the sqlite3 C module (pysqlite3, modified).",
    .m_size = -1,
    .m_methods = module_methods,
};

static int
add_exception(PyObject *module, PyObject **slot, const char *name, PyObject *base)
{
    *slot = PyErr_NewException(name, base, NULL);
    if (*slot == NULL) {
        return -1;
    }
    return PyModule_AddObjectRef(module, strrchr(name, '.') + 1, *slot);
}

#define INTERN(state, s)                                         \
    do {                                                         \
        if ((state->str_##s = PyUnicode_InternFromString(#s)) == NULL) \
            goto error;                                          \
    } while (0)

PyMODINIT_FUNC
PyInit__sqlite3(void)
{
    pysqlite_state *state = pysqlite_get_state();

    if (sqlite3_libversion_number() < 3025000) {
        PyErr_SetString(PyExc_ImportError, MODULE_NAME ": SQLite 3.25.0 or higher required");
        return NULL;
    }
    int rc = sqlite3_initialize();
    if (rc != SQLITE_OK) {
        PyErr_SetString(PyExc_ImportError, sqlite3_errstr(rc));
        return NULL;
    }

    PyObject *module = PyModule_Create(&module_def);
    if (module == NULL) {
        return NULL;
    }

    if (pysqlite_row_setup_types() < 0
        || pysqlite_cursor_setup_types() < 0
        || pysqlite_connection_setup_types() < 0
        || pysqlite_statement_setup_types() < 0
        || pysqlite_prepare_protocol_setup_types() < 0
        || pysqlite_blob_setup_types() < 0) {
        goto error;
    }
    if (PyModule_AddType(module, &pysqlite_BlobType) < 0
        || PyModule_AddType(module, &pysqlite_ConnectionType) < 0
        || PyModule_AddType(module, &pysqlite_CursorType) < 0
        || PyModule_AddType(module, &pysqlite_PrepareProtocolType) < 0
        || PyModule_AddType(module, &pysqlite_RowType) < 0) {
        goto error;
    }

    /* DB-API exception hierarchy */
    if (add_exception(module, &state->Error, MODULE_NAME ".Error", PyExc_Exception) < 0
        || add_exception(module, &state->Warning, MODULE_NAME ".Warning", PyExc_Exception) < 0
        || add_exception(module, &state->InterfaceError, MODULE_NAME ".InterfaceError", state->Error) < 0
        || add_exception(module, &state->DatabaseError, MODULE_NAME ".DatabaseError", state->Error) < 0
        || add_exception(module, &state->InternalError, MODULE_NAME ".InternalError", state->DatabaseError) < 0
        || add_exception(module, &state->OperationalError, MODULE_NAME ".OperationalError", state->DatabaseError) < 0
        || add_exception(module, &state->ProgrammingError, MODULE_NAME ".ProgrammingError", state->DatabaseError) < 0
        || add_exception(module, &state->IntegrityError, MODULE_NAME ".IntegrityError", state->DatabaseError) < 0
        || add_exception(module, &state->DataError, MODULE_NAME ".DataError", state->DatabaseError) < 0
        || add_exception(module, &state->NotSupportedError, MODULE_NAME ".NotSupportedError", state->DatabaseError) < 0) {
        goto error;
    }

    INTERN(state, __adapt__);
    INTERN(state, __conform__);
    INTERN(state, executescript);
    INTERN(state, finalize);
    INTERN(state, inverse);
    INTERN(state, step);
    INTERN(state, upper);
    INTERN(state, value);

    for (int i = 0; error_codes[i].name != NULL; i++) {
        if (PyModule_AddIntConstant(module, error_codes[i].name, error_codes[i].value) < 0) {
            goto error;
        }
    }
    for (int i = 0; int_constants[i].name != NULL; i++) {
        if (PyModule_AddIntConstant(module, int_constants[i].name, int_constants[i].value) < 0) {
            goto error;
        }
    }

    if (PyModule_AddStringConstant(module, "sqlite_version", sqlite3_libversion()) < 0
        || PyModule_AddIntConstant(module, "LEGACY_TRANSACTION_CONTROL", LEGACY_TRANSACTION_CONTROL) < 0
        || PyModule_AddStringConstant(module, "core_version", potluckdb_version()) < 0
        || PyModule_AddStringConstant(module, "__version__", POTLUCKDB_PACKAGE_VERSION) < 0) {
        goto error;
    }
#if PYSQLITE_PY312 && !PYSQLITE_PY314
    if (PyModule_AddStringConstant(module, "_deprecated_version", PYSQLITE_VERSION) < 0) {
        goto error;
    }
#elif !PYSQLITE_PY312
    if (PyModule_AddStringConstant(module, "version", PYSQLITE_VERSION) < 0) {
        goto error;
    }
#endif

    int threadsafety = get_threadsafety();
    if (threadsafety < 0 || PyModule_AddIntConstant(module, "threadsafety", threadsafety) < 0) {
        goto error;
    }

    if (pysqlite_microprotocols_init(module) < 0) {
        goto error;
    }
    state->converters = PyDict_New();
    if (state->converters == NULL
        || PyModule_AddObjectRef(module, "converters", state->converters) < 0) {
        goto error;
    }
    state->lru_cache = pysqlite_import_attr("functools", "lru_cache");
    if (state->lru_cache == NULL) {
        goto error;
    }
    return module;

error:
    Py_DECREF(module);
    return NULL;
}
