/*
** The native library of PotluckDB's .NET package on Linux and macOS:
** libpotluckdb_dotnet.so and libpotluckdb_dotnet.dylib.
**
** It contains the PotluckDB library, linked in from the core's static library
** (lib/static/libsqlite3.a), whose symbols are hidden. This file adds the only
** symbol the library exports: potluckdb_dotnet_symbol(), which returns the
** address of a function or variable of the SQLite and PotluckDB C API, by
** name. The .NET side hands these addresses to SQLitePCLRaw.
**
** As nothing else is exported, this copy of SQLite can't be mistaken for
** another one in the same process, nor another one for it: its calls to its
** own functions are bound when it is linked, and its file name and SONAME
** (install name on macOS) are PotluckDB's own. See ../DESIGN.md.
**
** symbols.h lists the API: one FUNCTION(name) or DATA(name) line per symbol
** that the core's shared library exports, sorted by name. scripts/native.py
** writes it at build time.
*/
#include <stdlib.h>
#include <string.h>

/* Only the addresses are taken, so the declared types don't matter. */
#define FUNCTION(name) extern void name(void);
#define DATA(name) extern char name[];
#include "symbols.h"
#undef FUNCTION
#undef DATA

struct symbol {
	const char *name;
	void *address;
};

#define FUNCTION(name) {#name, (void *)name},
#define DATA(name) {#name, (void *)name},
static const struct symbol symbols[] = {
#include "symbols.h"
};
#undef FUNCTION
#undef DATA

static int compare(const void *name, const void *entry) {
	return strcmp((const char *)name, ((const struct symbol *)entry)->name);
}

/* The address of the API function or variable called name, or NULL if this
** build of the library doesn't have it. */
__attribute__((visibility("default"))) void *potluckdb_dotnet_symbol(const char *name) {
	const struct symbol *found = bsearch(name, symbols, sizeof symbols / sizeof symbols[0], sizeof symbols[0], compare);
	return found ? found->address : NULL;
}
