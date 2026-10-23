/* cursor.h - definitions for the cursor type
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
 * Altered for PotluckDB (see ../README.md): no row prefetching; the
 * statement is stepped as rows are fetched.
 */

#ifndef PYSQLITE_CURSOR_H
#define PYSQLITE_CURSOR_H
#include "statement.h"
#include "connection.h"

typedef struct {
    PyObject_HEAD
    pysqlite_Connection *connection;
    PyObject *description;
    PyObject *row_cast_map;
#if PYSQLITE_PY313
    uint32_t arraysize;
#else
    int arraysize;
#endif
    PyObject *lastrowid;
    long rowcount;
    PyObject *row_factory;
    pysqlite_Statement *statement;
    int closed;
    int locked;
    int initialized;

    PyObject *in_weakreflist;
} pysqlite_Cursor;

PyObject *pysqlite_query_execute(pysqlite_Cursor *self, int multiple, PyObject *sql,
                                 PyObject *parameters);

int pysqlite_cursor_setup_types(void);

#endif
