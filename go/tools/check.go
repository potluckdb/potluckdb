package main

// Checks a program built with the driver: it contains one copy of SQLite,
// and that copy is PotluckDB's; it loads no SQLite shared library; and it
// exports none of the library's symbols. On Linux it also counts the
// symbols themselves.

import (
	"bytes"
	"debug/elf"
	"debug/macho"
	"debug/pe"
	"fmt"
	"os"
	"regexp"
	"strings"
)

// Every build of SQLite holds its source id, the date and hash of its
// source code, so a program with a second SQLite holds a second id.
var (
	sourceIDDefineRE = regexp.MustCompile(`#define SQLITE_SOURCE_ID\s+"([^"]+)"`)
	sourceIDRE       = regexp.MustCompile(`20[0-9]{2}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} [0-9a-f]{40,64}`)
)

// sqliteMagic starts every SQLite database file; SQLite's code holds it
// once or more, depending on the compiler.
var sqliteMagic = []byte("SQLite format 3\x00")

type binaryFacts struct {
	Lines    []string // what was checked, for the log
	Problems []string
}

func (f *binaryFacts) ok(format string, args ...any) {
	f.Lines = append(f.Lines, fmt.Sprintf(format, args...))
}
func (f *binaryFacts) bad(format string, args ...any) {
	f.Problems = append(f.Problems, fmt.Sprintf(format, args...))
}

// checkBinary checks a program against the release's sqlite3.h and the
// static library it should hold.
func checkBinary(file string, header, lib []byte) (*binaryFacts, error) {
	data, err := os.ReadFile(file)
	if err != nil {
		return nil, err
	}
	facts := &binaryFacts{}
	m := sourceIDDefineRE.FindSubmatch(header)
	if m == nil {
		return nil, fmt.Errorf("sqlite3.h has no SQLITE_SOURCE_ID")
	}
	ours := string(m[1])
	ids := map[string]bool{}
	for _, id := range sourceIDRE.FindAll(data, -1) {
		ids[string(id)] = true
	}
	switch {
	case !ids[ours]:
		facts.bad("the program does not hold PotluckDB's SQLite (source id %s)", ours)
	case len(ids) > 1:
		facts.bad("the program holds more than one SQLite (source ids: %v)", ids)
	default:
		facts.ok("one SQLite, PotluckDB's (source id %s)", ours)
	}
	inLib, inProgram := bytes.Count(lib, sqliteMagic), bytes.Count(data, sqliteMagic)
	if inProgram < 1 || inProgram > inLib {
		facts.bad("SQLite's file header string occurs %d times, the library has it %d times", inProgram, inLib)
	} else {
		facts.ok("SQLite's file header string occurs %d times (the library: %d)", inProgram, inLib)
	}
	var libs []string
	var exported []string
	if f, err := elf.Open(file); err == nil {
		defer f.Close()
		libs, _ = f.ImportedLibraries()
		dyn, _ := f.DynamicSymbols()
		for _, s := range dyn {
			if s.Section != elf.SHN_UNDEF {
				exported = append(exported, s.Name)
			}
		}
		syms, err := f.Symbols()
		if err != nil {
			facts.bad("no symbol table: %v", err)
		} else {
			defined := map[string]int{}
			for _, s := range syms {
				if s.Section != elf.SHN_UNDEF && elf.ST_TYPE(s.Info) == elf.STT_FUNC {
					defined[s.Name]++
				}
			}
			count := 0
			for name, n := range defined {
				if strings.HasPrefix(name, "sqlite3_") {
					count += n
				}
			}
			for _, name := range []string{"sqlite3_open_v2", "sqlite3_libversion", "potluckdb_version"} {
				if defined[name] == 1 {
					facts.ok("symbols: %s is defined once", name)
				} else {
					facts.bad("symbols: %s is defined %d times", name, defined[name])
				}
			}
			facts.ok("symbols: %d sqlite3_* functions, all from the one library", count)
		}
	} else if f, err := macho.Open(file); err == nil {
		defer f.Close()
		libs, _ = f.ImportedLibraries()
		if f.Symtab != nil {
			defined := map[string]int{}
			for _, s := range f.Symtab.Syms {
				if s.Sect != 0 {
					defined[strings.TrimPrefix(s.Name, "_")]++
				}
			}
			for _, name := range []string{"sqlite3_open_v2", "potluckdb_version"} {
				switch n := defined[name]; {
				case n > 1:
					facts.bad("symbols: %s is defined %d times", name, n)
				case n == 1:
					facts.ok("symbols: %s is defined once", name)
				}
			}
		}
		exported = machoExports(f)
	} else if f, err := pe.Open(file); err == nil {
		defer f.Close()
		libs = peImportedDLLs(f)
	} else {
		return nil, fmt.Errorf("%s is not an ELF, Mach-O or PE file", file)
	}
	for _, lib := range libs {
		if l := strings.ToLower(lib); strings.Contains(l, "sqlite") {
			facts.bad("it loads a SQLite shared library: %s", lib)
		}
	}
	facts.ok("loads no SQLite shared library (needs: %s)", strings.Join(libs, ", "))
	// The library's own names (sqlite3_open, potluckdb_version), not the
	// driver's helpers (_sqlite3_open_v2). Mach-O adds a "_" to C names.
	var leaked []string
	for _, name := range exported {
		if strings.HasPrefix(name, "sqlite3_") || strings.HasPrefix(name, "potluckdb_") {
			leaked = append(leaked, name)
		}
	}
	if len(leaked) > 0 {
		facts.bad("exports %d library symbols, e.g. %s", len(leaked), strings.Join(leaked[:min(5, len(leaked))], ", "))
	} else {
		facts.ok("exports none of the library's symbols")
	}
	return facts, nil
}

// machoExports lists the external symbols a Mach-O file defines, without
// the "_" that Mach-O adds to C names.
func machoExports(f *macho.File) []string {
	var names []string
	if f.Symtab == nil {
		return nil
	}
	for _, s := range f.Symtab.Syms {
		const nExt, nTypeMask, nSect = 0x01, 0x0e, 0x0e
		if s.Type&nExt != 0 && s.Type&nTypeMask == nSect {
			names = append(names, strings.TrimPrefix(s.Name, "_"))
		}
	}
	return names
}

// peImportedDLLs lists the DLLs a PE file imports from (debug/pe's
// ImportedLibraries does not read them).
func peImportedDLLs(f *pe.File) []string {
	syms, _ := f.ImportedSymbols()
	seen := map[string]bool{}
	var dlls []string
	for _, s := range syms {
		if _, dll, ok := strings.Cut(s, ":"); ok && !seen[strings.ToLower(dll)] {
			seen[strings.ToLower(dll)] = true
			dlls = append(dlls, dll)
		}
	}
	return dlls
}
