/* row.c - an enhanced tuple for database rows
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
 * Altered for PotluckDB (see ../README.md): garbage-collector support,
 * rows of a cursor without a description, positional-only constructor,
 * errors from hashing are passed on.
 */


#include "row.h"
#include "cursor.h"

static int
row_traverse(pysqlite_Row *self, visitproc visit, void *arg)
{
    Py_VISIT(self->data);
    Py_VISIT(self->description);
    return 0;
}

static int
row_clear(pysqlite_Row *self)
{
    Py_CLEAR(self->data);
    Py_CLEAR(self->description);
    return 0;
}

static void
pysqlite_row_dealloc(pysqlite_Row *self)
{
    PyObject_GC_UnTrack(self);
    row_clear(self);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

static PyObject *
pysqlite_row_new(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
    PyObject *cursor, *data;

    if (kwargs != NULL && PyDict_GET_SIZE(kwargs) != 0) {
        PyErr_SetString(PyExc_TypeError, "Row() takes no keyword arguments");
        return NULL;
    }
    if (!PyArg_ParseTuple(args, "O!O!:Row", &pysqlite_CursorType, &cursor, &PyTuple_Type, &data)) {
        return NULL;
    }

    pysqlite_Row *self = (pysqlite_Row *)type->tp_alloc(type, 0);
    if (self == NULL) {
        return NULL;
    }
    self->data = Py_NewRef(data);
    PyObject *description = ((pysqlite_Cursor *)cursor)->description;
    self->description = Py_NewRef(description ? description : Py_None);
    return (PyObject *)self;
}

static PyObject *
pysqlite_row_item(pysqlite_Row *self, Py_ssize_t idx)
{
    return Py_XNewRef(PyTuple_GetItem(self->data, idx));
}

static int
equal_ignore_case(PyObject *left, PyObject *right)
{
    int eq = PyObject_RichCompareBool(left, right, Py_EQ);
    if (eq) {
        return eq;  /* equal, or an error */
    }
    if (!PyUnicode_Check(left) || !PyUnicode_Check(right)) {
        return 0;
    }
    if (!PyUnicode_IS_ASCII(left) || !PyUnicode_IS_ASCII(right)) {
        return 0;
    }
    Py_ssize_t len = PyUnicode_GET_LENGTH(left);
    if (PyUnicode_GET_LENGTH(right) != len) {
        return 0;
    }
    const Py_UCS1 *p1 = PyUnicode_1BYTE_DATA(left);
    const Py_UCS1 *p2 = PyUnicode_1BYTE_DATA(right);
    for (; len; len--, p1++, p2++) {
        if (Py_TOLOWER(*p1) != Py_TOLOWER(*p2)) {
            return 0;
        }
    }
    return 1;
}

static PyObject *
pysqlite_row_subscript(pysqlite_Row *self, PyObject *idx)
{
    if (PyLong_Check(idx)) {
        Py_ssize_t i = PyNumber_AsSsize_t(idx, PyExc_IndexError);
        if (i == -1 && PyErr_Occurred()) {
            return NULL;
        }
        if (i < 0) {
            i += PyTuple_GET_SIZE(self->data);
        }
        return Py_XNewRef(PyTuple_GetItem(self->data, i));
    }
    if (PyUnicode_Check(idx)) {
        if (self->description == Py_None) {
            PyErr_Format(PyExc_IndexError, "No item with key %R", idx);
            return NULL;
        }
        Py_ssize_t n = PyTuple_GET_SIZE(self->description);
        for (Py_ssize_t i = 0; i < n; i++) {
            PyObject *name = PyTuple_GET_ITEM(PyTuple_GET_ITEM(self->description, i), 0);
            int eq = equal_ignore_case(idx, name);
            if (eq < 0) {
                return NULL;
            }
            if (eq) {
                return Py_XNewRef(PyTuple_GetItem(self->data, i));
            }
        }
        PyErr_SetString(PyExc_IndexError, "No item with that key");
        return NULL;
    }
    if (PySlice_Check(idx)) {
        return PyObject_GetItem(self->data, idx);
    }
    PyErr_SetString(PyExc_IndexError, "Index must be int or string");
    return NULL;
}

static Py_ssize_t
pysqlite_row_length(pysqlite_Row *self)
{
    return PyTuple_GET_SIZE(self->data);
}

static PyObject *
pysqlite_row_keys(pysqlite_Row *self, PyObject *Py_UNUSED(ignored))
{
    PyObject *list = PyList_New(0);
    if (list == NULL || self->description == Py_None) {
        return list;
    }
    Py_ssize_t n = PyTuple_GET_SIZE(self->description);
    for (Py_ssize_t i = 0; i < n; i++) {
        PyObject *name = PyTuple_GET_ITEM(PyTuple_GET_ITEM(self->description, i), 0);
        if (PyList_Append(list, name) < 0) {
            Py_DECREF(list);
            return NULL;
        }
    }
    return list;
}

static PyObject *
pysqlite_iter(pysqlite_Row *self)
{
    return PyObject_GetIter(self->data);
}

static Py_hash_t
pysqlite_row_hash(pysqlite_Row *self)
{
    Py_hash_t h1 = PyObject_Hash(self->description);
    if (h1 == -1) {
        return -1;
    }
    Py_hash_t h2 = PyObject_Hash(self->data);
    if (h2 == -1) {
        return -1;
    }
    return h1 ^ h2;
}

static PyObject *
pysqlite_row_richcompare(pysqlite_Row *self, PyObject *other, int op)
{
    if (op != Py_EQ && op != Py_NE) {
        Py_RETURN_NOTIMPLEMENTED;
    }
    if (!PyObject_TypeCheck(other, &pysqlite_RowType)) {
        Py_RETURN_NOTIMPLEMENTED;
    }
    pysqlite_Row *o = (pysqlite_Row *)other;
    int eq = PyObject_RichCompareBool(self->description, o->description, Py_EQ);
    if (eq < 0) {
        return NULL;
    }
    if (eq) {
        return PyObject_RichCompare(self->data, o->data, op);
    }
    return PyBool_FromLong(op != Py_EQ);
}

static PyMappingMethods pysqlite_row_as_mapping = {
    .mp_length = (lenfunc)pysqlite_row_length,
    .mp_subscript = (binaryfunc)pysqlite_row_subscript,
};

static PySequenceMethods pysqlite_row_as_sequence = {
    .sq_length = (lenfunc)pysqlite_row_length,
    .sq_item = (ssizeargfunc)pysqlite_row_item,
};

static PyMethodDef pysqlite_row_methods[] = {
    {"keys", (PyCFunction)pysqlite_row_keys, METH_NOARGS,
     PyDoc_STR("keys($self, /)\n--\n\nReturns the keys of the row.")},
    {NULL, NULL}
};

PyTypeObject pysqlite_RowType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = MODULE_NAME ".Row",
    .tp_basicsize = sizeof(pysqlite_Row),
    .tp_dealloc = (destructor)pysqlite_row_dealloc,
    .tp_as_sequence = &pysqlite_row_as_sequence,
    .tp_as_mapping = &pysqlite_row_as_mapping,
    .tp_hash = (hashfunc)pysqlite_row_hash,
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE | Py_TPFLAGS_HAVE_GC,
    .tp_traverse = (traverseproc)row_traverse,
    .tp_clear = (inquiry)row_clear,
    .tp_richcompare = (richcmpfunc)pysqlite_row_richcompare,
    .tp_iter = (getiterfunc)pysqlite_iter,
    .tp_methods = pysqlite_row_methods,
    .tp_new = pysqlite_row_new,
};

int
pysqlite_row_setup_types(void)
{
    return PyType_Ready(&pysqlite_RowType);
}
