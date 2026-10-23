/* compat.h - helpers so one source tree builds for CPython 3.10 to 3.14
 *
 * Added for PotluckDB (not part of pysqlite3 0.6.0); distributed under the
 * same zlib licence as the rest of this directory.
 *
 * The extension is compiled once per Python version, so behaviour that
 * differs between versions of the standard sqlite3 module is selected at
 * compile time with the PYSQLITE_PY3xx macros below.
 */

#ifndef PYSQLITE_COMPAT_H
#define PYSQLITE_COMPAT_H
#define PY_SSIZE_T_CLEAN
#include "Python.h"

#define PYSQLITE_PY311 (PY_VERSION_HEX >= 0x030B0000)
#define PYSQLITE_PY312 (PY_VERSION_HEX >= 0x030C0000)
#define PYSQLITE_PY313 (PY_VERSION_HEX >= 0x030D0000)
#define PYSQLITE_PY314 (PY_VERSION_HEX >= 0x030E0000)

/* PyMemberDef types (T_OBJECT reads a NULL member as None). */
#include "structmember.h"
#define PYSQLITE_T_OBJECT T_OBJECT
#define PYSQLITE_T_LONG T_LONG
#define PYSQLITE_READONLY READONLY

/* The exception currently raised, as one object (3.12 API). */
static inline PyObject *
pysqlite_get_raised(void)
{
#if PYSQLITE_PY312
    return PyErr_GetRaisedException();
#else
    PyObject *type, *value, *tb;
    PyErr_Fetch(&type, &value, &tb);
    if (type == NULL) {
        return NULL;
    }
    PyErr_NormalizeException(&type, &value, &tb);
    if (tb != NULL && value != NULL) {
        PyException_SetTraceback(value, tb);
    }
    Py_XDECREF(type);
    Py_XDECREF(tb);
    return value;
#endif
}

static inline void
pysqlite_set_raised(PyObject *exc)
{
#if PYSQLITE_PY312
    PyErr_SetRaisedException(exc);
#else
    if (exc == NULL) {
        PyErr_Clear();
        return;
    }
    PyObject *type = (PyObject *)Py_TYPE(exc);
    PyObject *tb = PyException_GetTraceback(exc);
    Py_INCREF(type);
    PyErr_Restore(type, exc, tb);
#endif
}

/* Raise the current exception with `exc` (if any) as its __context__. */
static inline void
pysqlite_chain_exceptions(PyObject *exc)
{
    if (exc == NULL) {
        return;
    }
    if (!PyErr_Occurred()) {
        pysqlite_set_raised(exc);
        return;
    }
    PyObject *current = pysqlite_get_raised();
    PyException_SetContext(current, exc);  /* steals exc */
    pysqlite_set_raised(current);
}

static inline int
pysqlite_long_as_int(PyObject *obj)
{
#if PYSQLITE_PY313
    return PyLong_AsInt(obj);
#else
    int overflow;
    long value = PyLong_AsLongAndOverflow(obj, &overflow);
    if (overflow || value > INT_MAX || value < INT_MIN) {
        PyErr_SetString(PyExc_OverflowError,
                        "Python int too large to convert to C int");
        return -1;
    }
    return (int)value;
#endif
}

/* 1 and a new reference in *result if obj has attribute name; 0 and NULL if
 * it has not; -1 on error. */
static inline int
pysqlite_get_optional_attr(PyObject *obj, PyObject *name, PyObject **result)
{
#if PYSQLITE_PY313
    return PyObject_GetOptionalAttr(obj, name, result);
#else
    *result = PyObject_GetAttr(obj, name);
    if (*result != NULL) {
        return 1;
    }
    if (PyErr_ExceptionMatches(PyExc_AttributeError)) {
        PyErr_Clear();
        return 0;
    }
    return -1;
#endif
}

/* Like PyMapping_GetOptionalItemString (3.13). */
static inline int
pysqlite_mapping_get_optional_item(PyObject *mapping, const char *key,
                                   PyObject **result)
{
#if PYSQLITE_PY313
    return PyMapping_GetOptionalItemString(mapping, key, result);
#else
    *result = PyMapping_GetItemString(mapping, key);
    if (*result != NULL) {
        return 1;
    }
    if (PyErr_ExceptionMatches(PyExc_KeyError)) {
        PyErr_Clear();
        return 0;
    }
    return -1;
#endif
}

static inline int
pysqlite_dict_get_item_ref(PyObject *dict, PyObject *key, PyObject **result)
{
#if PYSQLITE_PY313
    return PyDict_GetItemRef(dict, key, result);
#else
    PyObject *item = PyDict_GetItemWithError(dict, key);
    if (item == NULL) {
        *result = NULL;
        return PyErr_Occurred() ? -1 : 0;
    }
    *result = Py_NewRef(item);
    return 1;
#endif
}

/* 1 and a new reference if the referent is alive, 0 if it is dead. */
static inline int
pysqlite_weakref_get_ref(PyObject *ref, PyObject **result)
{
#if PYSQLITE_PY313
    return PyWeakref_GetRef(ref, result);
#else
    PyObject *obj = PyWeakref_GetObject(ref);
    if (obj == NULL) {
        *result = NULL;
        return -1;
    }
    if (obj == Py_None) {
        *result = NULL;
        return 0;
    }
    *result = Py_NewRef(obj);
    return 1;
#endif
}

static inline PyObject *
pysqlite_import_attr(const char *module_name, const char *attr)
{
    PyObject *module = PyImport_ImportModule(module_name);
    if (module == NULL) {
        return NULL;
    }
    PyObject *value = PyObject_GetAttrString(module, attr);
    Py_DECREF(module);
    return value;
}

static inline int
pysqlite_is_finalizing(void)
{
#if PYSQLITE_PY313
    return Py_IsFinalizing();
#else
    return _Py_IsFinalizing();
#endif
}

/* Report the current exception through sys.unraisablehook. Before 3.14 the
 * hook gets `obj` as its object; from 3.14 a message naming obj (like the
 * standard library's sqlite3 module). */
static inline void
pysqlite_write_unraisable(const char *format_with_R, PyObject *obj)
{
#if PYSQLITE_PY314
    PyErr_FormatUnraisable(format_with_R, obj);
#else
    (void)format_with_R;
    PyErr_WriteUnraisable(obj);
#endif
}

/* UTF-8 of a str that must not contain NUL characters. */
static inline const char *
pysqlite_utf8_no_nul(PyObject *str)
{
    Py_ssize_t size;
    const char *utf8 = PyUnicode_AsUTF8AndSize(str, &size);
    if (utf8 == NULL) {
        return NULL;
    }
    if (strlen(utf8) != (size_t)size) {
        PyErr_SetString(PyExc_ValueError, "embedded null character");
        return NULL;
    }
    return utf8;
}

#endif
