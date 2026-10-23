/* util.h - various utility functions
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
 * SQLite result code; errors can be raised from a result code alone.
 */

#ifndef PYSQLITE_UTIL_H
#define PYSQLITE_UTIL_H
#include "module.h"

/* Raise the DB-API exception for the connection's last error. */
void pysqlite_set_error_from_db(sqlite3 *db);
/* Raise the DB-API exception for a result code. */
void pysqlite_set_error_from_code(int code);

/* A Python int as a 64-bit SQLite integer; -1 with an exception on error. */
sqlite_int64 pysqlite_long_as_int64(PyObject *value);

#endif
