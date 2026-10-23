/* connection.h - definitions for the connection type
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
 * Altered for PotluckDB (see ../README.md): callback contexts, the
 * autocommit attribute, and the statement cache as an LRU cache function.
 */

#ifndef PYSQLITE_CONNECTION_H
#define PYSQLITE_CONNECTION_H
#include "module.h"
#include "pythread.h"

/* What a callback registered with SQLite (function, aggregate, collation,
 * trace, progress, authorizer) needs; freed when SQLite drops it. */
typedef struct {
    PyObject *callable;
    Py_ssize_t refcount;
} pysqlite_callback_context;

enum autocommit_mode {
    AUTOCOMMIT_LEGACY = LEGACY_TRANSACTION_CONTROL,
    AUTOCOMMIT_ENABLED = 1,
    AUTOCOMMIT_DISABLED = 0,
};

typedef struct {
    PyObject_HEAD
    sqlite3 *db;

    /* 0, PARSE_DECLTYPES, PARSE_COLNAMES or both */
    int detect_types;

    /* NULL for autocommit, otherwise "", "DEFERRED", "IMMEDIATE" or
     * "EXCLUSIVE" (static strings) */
    const char *isolation_level;
    enum autocommit_mode autocommit;

    int check_same_thread;
    int initialized;
    unsigned long thread_ident;

    /* functools.lru_cache-wrapped statement factory */
    PyObject *statement_cache;

    /* weak references to cursors and blobs of this connection */
    PyObject *cursors;
    PyObject *blobs;
    int created_cursors;

    PyObject *row_factory;
    PyObject *text_factory;

    pysqlite_callback_context *trace_ctx;
    pysqlite_callback_context *progress_ctx;
    pysqlite_callback_context *authorizer_ctx;

    /* Exception classes (borrowed references), for the DB-API extension */
    PyObject *Warning;
    PyObject *Error;
    PyObject *InterfaceError;
    PyObject *DatabaseError;
    PyObject *DataError;
    PyObject *OperationalError;
    PyObject *IntegrityError;
    PyObject *InternalError;
    PyObject *ProgrammingError;
    PyObject *NotSupportedError;

    PyObject *in_weakreflist;
} pysqlite_Connection;

int pysqlite_check_thread(pysqlite_Connection *self);
int pysqlite_check_connection(pysqlite_Connection *con);

/* Shared with cursor.c */
PyObject *pysqlite_connection_cursor_new(pysqlite_Connection *self, PyObject *factory);

int pysqlite_connection_setup_types(void);

#endif
