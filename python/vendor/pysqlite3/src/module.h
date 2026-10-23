/* module.h - definitions for the module
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
 * Altered for PotluckDB (see ../README.md): module state gathered in one
 * struct, and definitions for the features of Python 3.11 to 3.14's sqlite3.
 */

#ifndef PYSQLITE_MODULE_H
#define PYSQLITE_MODULE_H
#include "compat.h"
#include "sqlite3.h"

#define PYSQLITE_VERSION "2.6.0"
#define LEGACY_TRANSACTION_CONTROL -1

#ifndef MODULE_NAME
#  define MODULE_NAME "potluckdb"
#endif

#if SQLITE_VERSION_NUMBER < 3025000
#  error "SQLite 3.25.0 or newer is required"
#endif

typedef struct {
    PyObject *DataError;
    PyObject *DatabaseError;
    PyObject *Error;
    PyObject *IntegrityError;
    PyObject *InterfaceError;
    PyObject *InternalError;
    PyObject *NotSupportedError;
    PyObject *OperationalError;
    PyObject *ProgrammingError;
    PyObject *Warning;

    /* Column type name (upper case) -> converter callable. */
    PyObject *converters;
    /* (type, protocol) -> adapter callable. */
    PyObject *adapters;
    /* functools.lru_cache, used for the statement cache. */
    PyObject *lru_cache;

    int BaseTypeAdapted;
    int enable_callback_tracebacks;

    PyObject *str___adapt__;
    PyObject *str___conform__;
    PyObject *str_executescript;
    PyObject *str_finalize;
    PyObject *str_inverse;
    PyObject *str_step;
    PyObject *str_upper;
    PyObject *str_value;
} pysqlite_state;

/* The module uses single-phase initialisation, so there is one state. */
extern pysqlite_state pysqlite_global_state;
#define pysqlite_get_state() (&pysqlite_global_state)

extern PyTypeObject pysqlite_BlobType;
extern PyTypeObject pysqlite_ConnectionType;
extern PyTypeObject pysqlite_CursorType;
extern PyTypeObject pysqlite_PrepareProtocolType;
extern PyTypeObject pysqlite_RowType;
extern PyTypeObject pysqlite_StatementType;

extern const char *pysqlite_error_name(int rc);

#define PARSE_DECLTYPES 1
#define PARSE_COLNAMES 2
#endif
