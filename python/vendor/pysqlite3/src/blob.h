/* blob.h - the Blob type (incremental BLOB I/O)
 *
 * Part of pysqlite3 0.6.0 (which added it to pysqlite), altered for PotluckDB
 * (see ../README.md): renamed to Blob and opened with Connection.blobopen(),
 * like the standard library's sqlite3 module since Python 3.11.
 */

#ifndef PYSQLITE_BLOB_H
#define PYSQLITE_BLOB_H
#include "connection.h"

typedef struct {
    PyObject_HEAD
    pysqlite_Connection *connection;
    sqlite3_blob *blob;
    int offset;
    PyObject *in_weakreflist;
} pysqlite_Blob;

PyObject *pysqlite_blob_new(pysqlite_Connection *connection, sqlite3_blob *blob);
void pysqlite_close_all_blobs(pysqlite_Connection *self);

int pysqlite_blob_setup_types(void);

#endif
