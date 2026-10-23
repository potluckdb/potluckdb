/* blob.c - the Blob type (incremental BLOB I/O)
 *
 * Part of pysqlite3 0.6.0 (which added it to pysqlite), altered for PotluckDB
 * (see ../README.md): rewritten to match the standard library's sqlite3.Blob
 * (Python 3.11+): read/write/seek/tell, len(), indexing and slicing with
 * steps, context manager, closed-blob and closed-database checks, and the
 * standard messages.
 */

#include "blob.h"
#include "util.h"

static void
close_blob(pysqlite_Blob *self)
{
    if (self->blob) {
        sqlite3_blob *blob = self->blob;
        self->blob = NULL;
        Py_BEGIN_ALLOW_THREADS
        sqlite3_blob_close(blob);
        Py_END_ALLOW_THREADS
    }
}

PyObject *
pysqlite_blob_new(pysqlite_Connection *connection, sqlite3_blob *blob)
{
    pysqlite_Blob *self = PyObject_GC_New(pysqlite_Blob, &pysqlite_BlobType);
    if (self == NULL) {
        Py_BEGIN_ALLOW_THREADS
        sqlite3_blob_close(blob);
        Py_END_ALLOW_THREADS
        return NULL;
    }
    self->connection = (pysqlite_Connection *)Py_NewRef(connection);
    self->blob = blob;
    self->offset = 0;
    self->in_weakreflist = NULL;
    PyObject_GC_Track(self);

    PyObject *ref = PyWeakref_NewRef((PyObject *)self, NULL);
    if (ref == NULL || PyList_Append(connection->blobs, ref) < 0) {
        Py_XDECREF(ref);
        Py_DECREF(self);
        return NULL;
    }
    Py_DECREF(ref);
    return (PyObject *)self;
}

void
pysqlite_close_all_blobs(pysqlite_Connection *self)
{
    if (self->blobs == NULL) {
        return;
    }
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(self->blobs); i++) {
        PyObject *blob;
        if (pysqlite_weakref_get_ref(PyList_GET_ITEM(self->blobs, i), &blob) <= 0) {
            PyErr_Clear();
            continue;
        }
        close_blob((pysqlite_Blob *)blob);
        Py_DECREF(blob);
    }
}

static int
blob_traverse(pysqlite_Blob *self, visitproc visit, void *arg)
{
    Py_VISIT(self->connection);
    return 0;
}

static int
blob_clear(pysqlite_Blob *self)
{
    Py_CLEAR(self->connection);
    return 0;
}

static void
blob_dealloc(pysqlite_Blob *self)
{
    PyObject_GC_UnTrack(self);
    close_blob(self);
    if (self->in_weakreflist != NULL) {
        PyObject_ClearWeakRefs((PyObject *)self);
    }
    blob_clear(self);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

/* 1 if the blob can be used, else 0 with an exception. */
static int
check_blob(pysqlite_Blob *self)
{
    if (!pysqlite_check_connection(self->connection)
        || !pysqlite_check_thread(self->connection)) {
        return 0;
    }
    if (self->blob == NULL) {
        PyErr_SetString(pysqlite_get_state()->ProgrammingError,
                        "Cannot operate on a closed blob.");
        return 0;
    }
    return 1;
}

static PyObject *
blob_close(pysqlite_Blob *self, PyObject *Py_UNUSED(ignored))
{
    if (!pysqlite_check_connection(self->connection)
        || !pysqlite_check_thread(self->connection)) {
        return NULL;
    }
    close_blob(self);
    Py_RETURN_NONE;
}

static PyObject *
read_single(pysqlite_Blob *self, Py_ssize_t offset)
{
    unsigned char byte = 0;
    int rc;
    Py_BEGIN_ALLOW_THREADS
    rc = sqlite3_blob_read(self->blob, &byte, 1, (int)offset);
    Py_END_ALLOW_THREADS
    if (rc != SQLITE_OK) {
        pysqlite_set_error_from_db(self->connection->db);
        return NULL;
    }
    return PyLong_FromUnsignedLong(byte);
}

static PyObject *
read_multiple(pysqlite_Blob *self, Py_ssize_t length, Py_ssize_t offset)
{
    PyObject *buffer = PyBytes_FromStringAndSize(NULL, length);
    if (buffer == NULL) {
        return NULL;
    }
    char *raw = PyBytes_AS_STRING(buffer);
    int rc;
    Py_BEGIN_ALLOW_THREADS
    rc = sqlite3_blob_read(self->blob, raw, (int)length, (int)offset);
    Py_END_ALLOW_THREADS
    if (rc != SQLITE_OK) {
        Py_DECREF(buffer);
        pysqlite_set_error_from_db(self->connection->db);
        return NULL;
    }
    return buffer;
}

static PyObject *
blob_read(pysqlite_Blob *self, PyObject *args)
{
    int length = -1;
    if (!PyArg_ParseTuple(args, "|i:read", &length)) {
        return NULL;
    }
    if (!check_blob(self)) {
        return NULL;
    }
    /* Never read past the end; a negative length reads to the end. */
    int max_len = sqlite3_blob_bytes(self->blob) - self->offset;
    if (length < 0 || length > max_len) {
        length = max_len;
    }
    if (length == 0) {
        return PyBytes_FromStringAndSize(NULL, 0);
    }
    PyObject *buffer = read_multiple(self, length, self->offset);
    if (buffer == NULL) {
        return NULL;
    }
    self->offset += length;
    return buffer;
}

static int
inner_write(pysqlite_Blob *self, const void *buf, Py_ssize_t len, Py_ssize_t offset)
{
    Py_ssize_t remaining = sqlite3_blob_bytes(self->blob) - offset;
    if (len > remaining) {
        PyErr_SetString(PyExc_ValueError, "data longer than blob length");
        return -1;
    }
    int rc;
    Py_BEGIN_ALLOW_THREADS
    rc = sqlite3_blob_write(self->blob, buf, (int)len, (int)offset);
    Py_END_ALLOW_THREADS
    if (rc != SQLITE_OK) {
        pysqlite_set_error_from_db(self->connection->db);
        return -1;
    }
    return 0;
}

static PyObject *
blob_write(pysqlite_Blob *self, PyObject *arg)
{
    Py_buffer data;
    if (PyObject_GetBuffer(arg, &data, PyBUF_SIMPLE) < 0) {
        return NULL;
    }
    if (!check_blob(self)) {
        PyBuffer_Release(&data);
        return NULL;
    }
    int rc = inner_write(self, data.buf, data.len, self->offset);
    if (rc == 0) {
        self->offset += (int)data.len;
    }
    PyBuffer_Release(&data);
    if (rc < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
blob_seek(pysqlite_Blob *self, PyObject *args)
{
    int offset, origin = 0;
    if (!PyArg_ParseTuple(args, "i|i:seek", &offset, &origin)) {
        return NULL;
    }
    if (!check_blob(self)) {
        return NULL;
    }
    int blob_len = sqlite3_blob_bytes(self->blob);
    switch (origin) {
        case SEEK_SET:
            break;
        case SEEK_CUR:
            if (offset > INT_MAX - self->offset) {
                goto overflow;
            }
            offset += self->offset;
            break;
        case SEEK_END:
            if (offset > INT_MAX - blob_len) {
                goto overflow;
            }
            offset += blob_len;
            break;
        default:
            PyErr_SetString(PyExc_ValueError,
                            "'origin' should be os.SEEK_SET, os.SEEK_CUR, or os.SEEK_END");
            return NULL;
    }
    if (offset < 0 || offset > blob_len) {
        PyErr_SetString(PyExc_ValueError, "offset out of blob range");
        return NULL;
    }
    self->offset = offset;
    Py_RETURN_NONE;

overflow:
    PyErr_SetString(PyExc_OverflowError, "seek offset results in overflow");
    return NULL;
}

static PyObject *
blob_tell(pysqlite_Blob *self, PyObject *Py_UNUSED(ignored))
{
    if (!check_blob(self)) {
        return NULL;
    }
    return PyLong_FromLong(self->offset);
}

static PyObject *
blob_enter(pysqlite_Blob *self, PyObject *Py_UNUSED(ignored))
{
    if (!check_blob(self)) {
        return NULL;
    }
    return Py_NewRef((PyObject *)self);
}

static PyObject *
blob_exit(pysqlite_Blob *self, PyObject *args)
{
    PyObject *type, *value, *tb;
    if (!PyArg_ParseTuple(args, "OOO:__exit__", &type, &value, &tb)) {
        return NULL;
    }
    if (!check_blob(self)) {
        return NULL;
    }
    close_blob(self);
    Py_RETURN_FALSE;
}

static Py_ssize_t
blob_length(pysqlite_Blob *self)
{
    if (!check_blob(self)) {
        return -1;
    }
    return sqlite3_blob_bytes(self->blob);
}

static Py_ssize_t
get_subscript_index(pysqlite_Blob *self, PyObject *item)
{
    Py_ssize_t i = PyNumber_AsSsize_t(item, PyExc_IndexError);
    if (i == -1 && PyErr_Occurred()) {
        return -1;
    }
    int blob_len = sqlite3_blob_bytes(self->blob);
    if (i < 0) {
        i += blob_len;
    }
    if (i < 0 || i >= blob_len) {
        PyErr_SetString(PyExc_IndexError, "Blob index out of range");
        return -1;
    }
    return i;
}

static int
get_slice_info(pysqlite_Blob *self, PyObject *item, Py_ssize_t *start, Py_ssize_t *stop,
               Py_ssize_t *step, Py_ssize_t *slicelen)
{
    if (PySlice_Unpack(item, start, stop, step) < 0) {
        return -1;
    }
    *slicelen = PySlice_AdjustIndices(sqlite3_blob_bytes(self->blob), start, stop, *step);
    return 0;
}

static PyObject *
subscript_slice(pysqlite_Blob *self, PyObject *item)
{
    Py_ssize_t start, stop, step, len;
    if (get_slice_info(self, item, &start, &stop, &step, &len) < 0) {
        return NULL;
    }
    if (len == 0) {
        return PyBytes_FromStringAndSize(NULL, 0);
    }
    if (step < 0) {
        PyErr_SetString(PyExc_ValueError, "Blob doesn't support slices with a negative step");
        return NULL;
    }
    if (step == 1) {
        return read_multiple(self, len, start);
    }
    PyObject *blob = read_multiple(self, stop - start, start);
    if (blob == NULL) {
        return NULL;
    }
    PyObject *result = PyBytes_FromStringAndSize(NULL, len);
    if (result != NULL) {
        const char *src = PyBytes_AS_STRING(blob);
        char *dst = PyBytes_AS_STRING(result);
        for (Py_ssize_t i = 0, j = 0; i < len; i++, j += step) {
            dst[i] = src[j];
        }
    }
    Py_DECREF(blob);
    return result;
}

static PyObject *
blob_subscript(pysqlite_Blob *self, PyObject *item)
{
    if (!check_blob(self)) {
        return NULL;
    }
    if (PyIndex_Check(item)) {
        Py_ssize_t i = get_subscript_index(self, item);
        if (i < 0) {
            return NULL;
        }
        return read_single(self, i);
    }
    if (PySlice_Check(item)) {
        return subscript_slice(self, item);
    }
    PyErr_SetString(PyExc_TypeError, "Blob indices must be integers");
    return NULL;
}

static int
ass_subscript_index(pysqlite_Blob *self, PyObject *item, PyObject *value)
{
    if (value == NULL) {
        PyErr_SetString(PyExc_TypeError, "Blob doesn't support item deletion");
        return -1;
    }
    if (!PyLong_Check(value)) {
        PyErr_Format(PyExc_TypeError, "'%s' object cannot be interpreted as an integer",
                     Py_TYPE(value)->tp_name);
        return -1;
    }
    Py_ssize_t i = get_subscript_index(self, item);
    if (i < 0) {
        return -1;
    }
    long v = PyLong_AsLong(value);
    if (v == -1 && PyErr_Occurred()) {
        PyErr_Clear();  /* overflow reads as "out of range" */
        v = -1;
    }
    if (v < 0 || v > 255) {
        PyErr_SetString(PyExc_ValueError, "byte must be in range(0, 256)");
        return -1;
    }
    unsigned char byte = (unsigned char)v;
    return inner_write(self, &byte, 1, i);
}

static int
ass_subscript_slice(pysqlite_Blob *self, PyObject *item, PyObject *value)
{
    if (value == NULL) {
        PyErr_SetString(PyExc_TypeError, "Blob doesn't support slice deletion");
        return -1;
    }
    Py_ssize_t start, stop, step, len;
    if (get_slice_info(self, item, &start, &stop, &step, &len) < 0) {
        return -1;
    }
    Py_buffer vbuf;
    if (PyObject_GetBuffer(value, &vbuf, PyBUF_SIMPLE) < 0) {
        return -1;
    }
    int rc = -1;
    if (vbuf.len != len) {
        PyErr_SetString(PyExc_IndexError, "Blob slice assignment is wrong size");
    }
    else if (len == 0) {
        rc = 0;
    }
    else if (step < 0) {
        PyErr_SetString(PyExc_ValueError, "Blob doesn't support slices with a negative step");
    }
    else if (step == 1) {
        rc = inner_write(self, vbuf.buf, len, start);
    }
    else {
        PyObject *current = read_multiple(self, stop - start, start);
        if (current != NULL) {
            char *buf = PyBytes_AS_STRING(current);
            for (Py_ssize_t i = 0, j = 0; i < len; i++, j += step) {
                buf[j] = ((const char *)vbuf.buf)[i];
            }
            rc = inner_write(self, buf, stop - start, start);
            Py_DECREF(current);
        }
    }
    PyBuffer_Release(&vbuf);
    return rc;
}

static int
blob_ass_subscript(pysqlite_Blob *self, PyObject *item, PyObject *value)
{
    if (!check_blob(self)) {
        return -1;
    }
    if (PyIndex_Check(item)) {
        return ass_subscript_index(self, item, value);
    }
    if (PySlice_Check(item)) {
        return ass_subscript_slice(self, item, value);
    }
    PyErr_SetString(PyExc_TypeError, "Blob indices must be integers");
    return -1;
}

static PyMethodDef blob_methods[] = {
    {"close", (PyCFunction)blob_close, METH_NOARGS,
     PyDoc_STR("close($self, /)\n--\n\nClose the blob.")},
    {"read", (PyCFunction)blob_read, METH_VARARGS,
     PyDoc_STR("read($self, length=-1, /)\n--\n\nRead data at the current offset position.")},
    {"write", (PyCFunction)blob_write, METH_O,
     PyDoc_STR("write($self, data, /)\n--\n\nWrite data at the current offset.")},
    {"seek", (PyCFunction)blob_seek, METH_VARARGS,
     PyDoc_STR("seek($self, offset, origin=0, /)\n--\n\n"
               "Set the current access position to offset.")},
    {"tell", (PyCFunction)blob_tell, METH_NOARGS,
     PyDoc_STR("tell($self, /)\n--\n\nReturn the current access position for the blob.")},
    {"__enter__", (PyCFunction)blob_enter, METH_NOARGS,
     PyDoc_STR("__enter__($self, /)\n--\n\nBlob context manager enter.")},
    {"__exit__", (PyCFunction)blob_exit, METH_VARARGS,
     PyDoc_STR("__exit__($self, type, val, tb, /)\n--\n\nBlob context manager exit.")},
    {NULL, NULL}
};

static PyMappingMethods blob_as_mapping = {
    .mp_length = (lenfunc)blob_length,
    .mp_subscript = (binaryfunc)blob_subscript,
    .mp_ass_subscript = (objobjargproc)blob_ass_subscript,
};

PyTypeObject pysqlite_BlobType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = MODULE_NAME ".Blob",
    .tp_basicsize = sizeof(pysqlite_Blob),
    .tp_dealloc = (destructor)blob_dealloc,
    .tp_as_mapping = &blob_as_mapping,
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC | Py_TPFLAGS_DISALLOW_INSTANTIATION,
    .tp_traverse = (traverseproc)blob_traverse,
    .tp_clear = (inquiry)blob_clear,
    .tp_weaklistoffset = offsetof(pysqlite_Blob, in_weakreflist),
    .tp_methods = blob_methods,
};

int
pysqlite_blob_setup_types(void)
{
    return PyType_Ready(&pysqlite_BlobType);
}
