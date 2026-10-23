/* microprotocols.c - minimalist and non-validating protocols implementation
 *
 * Copyright (C) 2003-2004 Federico Di Gregorio <fog@debian.org>
 *
 * This file is part of psycopg and was adapted for pysqlite. Federico Di
 * Gregorio gave the permission to use it within pysqlite under the following
 * license:
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
 * Altered for PotluckDB (see ../README.md): the adapter registry lives
 * in the module state; lookups pass on errors; adapt() moved to module.c.
 */

#include "microprotocols.h"
#include "prepare_protocol.h"

int
pysqlite_microprotocols_init(PyObject *module)
{
    pysqlite_state *state = pysqlite_get_state();
    state->adapters = PyDict_New();
    if (state->adapters == NULL) {
        return -1;
    }
    return PyModule_AddObjectRef(module, "adapters", state->adapters);
}

int
pysqlite_microprotocols_add(PyTypeObject *type, PyObject *proto, PyObject *cast)
{
    PyObject *key = PyTuple_Pack(2, (PyObject *)type, proto);
    if (key == NULL) {
        return -1;
    }
    int rc = PyDict_SetItem(pysqlite_get_state()->adapters, key, cast);
    Py_DECREF(key);
    return rc;
}

/* Calls method(arg); returns NULL without an exception if it returned None
 * or raised TypeError (the protocol does not apply). */
static PyObject *
try_adapter(PyObject *method, PyObject *arg)
{
    PyObject *adapted = PyObject_CallOneArg(method, arg);
    if (adapted == Py_None) {
        Py_DECREF(adapted);
        return NULL;
    }
    if (adapted == NULL && PyErr_ExceptionMatches(PyExc_TypeError)) {
        PyErr_Clear();
    }
    return adapted;
}

PyObject *
pysqlite_microprotocols_adapt(PyObject *obj, PyObject *proto, PyObject *alt)
{
    pysqlite_state *state = pysqlite_get_state();

    /* 1. an adapter registered for (type(obj), proto) */
    PyObject *key = PyTuple_Pack(2, (PyObject *)Py_TYPE(obj), proto);
    if (key == NULL) {
        return NULL;
    }
    PyObject *adapter;
    int found = pysqlite_dict_get_item_ref(state->adapters, key, &adapter);
    Py_DECREF(key);
    if (found < 0) {
        return NULL;
    }
    if (found) {
        PyObject *adapted = PyObject_CallOneArg(adapter, obj);
        Py_DECREF(adapter);
        return adapted;
    }

    /* 2. proto.__adapt__(obj) */
    if (pysqlite_get_optional_attr(proto, state->str___adapt__, &adapter) < 0) {
        return NULL;
    }
    if (adapter) {
        PyObject *adapted = try_adapter(adapter, obj);
        Py_DECREF(adapter);
        if (adapted != NULL || PyErr_Occurred()) {
            return adapted;
        }
    }

    /* 3. obj.__conform__(proto) */
    if (pysqlite_get_optional_attr(obj, state->str___conform__, &adapter) < 0) {
        return NULL;
    }
    if (adapter) {
        PyObject *adapted = try_adapter(adapter, proto);
        Py_DECREF(adapter);
        if (adapted != NULL || PyErr_Occurred()) {
            return adapted;
        }
    }

    if (alt) {
        return Py_NewRef(alt);
    }
    PyErr_SetString(state->ProgrammingError, "can't adapt");
    return NULL;
}
