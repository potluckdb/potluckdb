"""Checks that a program contains PotluckDB's SQLite and no other.

- Every copy of SQLite carries its source id ("<date> <time> <sha3 hash>",
  what sqlite_source_id() returns). The program must contain exactly the
  source ids of the core archive's static library, so no second SQLite (for
  example libsqlite3-sys's bundled one) is linked in.
- The program must not load a shared SQLite library (sqlite3.dll,
  libsqlite3.so, libsqlite3.dylib).
- Linux: SQLite's functions are defined once (one sqlite3_open_v2), and the
  program exports none of them. macOS: it exports none of them.

Usage: python3 rust/scripts/check_binary.py <program> <core archive>
"""
import pathlib
import re
import struct
import subprocess
import sys
import tarfile
import zipfile

SOURCE_ID = re.compile(rb"20\d\d-\d\d-\d\d \d\d:\d\d:\d\d [0-9a-f]{64}")


def static_library(archive):
    """The bytes of the archive's lib/static library."""
    path = str(archive)
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.endswith("/lib/static/sqlite3.lib"))
            return z.read(name)
    with tarfile.open(path) as t:
        member = next(m for m in t.getmembers() if m.name.endswith("/lib/static/libsqlite3.a"))
        return t.extractfile(member).read()


def pe_imports(data):
    """Names of the DLLs a Windows program imports."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    sections = struct.unpack_from("<H", data, pe + 6)[0]
    optional = pe + 24
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    magic = struct.unpack_from("<H", data, optional)[0]
    import_rva = struct.unpack_from("<I", data, optional + (120 if magic == 0x20B else 104))[0]

    def offset(rva):
        for i in range(sections):
            s = optional + optional_size + 40 * i
            size, va, _, raw = struct.unpack_from("<IIII", data, s + 8)
            if va <= rva < va + max(size, 1):
                return rva - va + raw
        raise ValueError(f"RVA {rva:#x} is in no section")

    names = []
    if import_rva:
        at = offset(import_rva)
        while True:
            entry = struct.unpack_from("<IIIII", data, at)
            if not any(entry):
                break
            start = offset(entry[3])
            names.append(data[start:data.index(b"\0", start)].decode("latin-1"))
            at += 20
    return names


def run(*command):
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def main(argv=None):
    program, archive = (pathlib.Path(a) for a in (argv or sys.argv[1:]))
    data = program.read_bytes()
    problems = []

    expected = set(SOURCE_ID.findall(static_library(archive)))
    found = set(SOURCE_ID.findall(data))
    print(f"SQLite source ids in the core library: {sorted(i.decode() for i in expected)}")
    print(f"SQLite source ids in {program.name}: {sorted(i.decode() for i in found)}")
    if len(expected) != 1:
        problems.append(f"the core library has {len(expected)} source ids, expected 1")
    if found != expected:
        problems.append("the program's SQLite source ids differ from the core library's")

    if data[:4] == b"\x7fELF":
        needed = re.findall(r"\(NEEDED\).*\[(.*)\]", run("readelf", "-d", str(program)))
        defined = run("nm", "--defined-only", str(program)).split("\n")
        opens = [line for line in defined if line.endswith(" sqlite3_open_v2")]
        exported = [line.split()[-1] for line in run("nm", "-D", "--defined-only", str(program)).split("\n")
                    if re.search(r" (sqlite3|potluckdb)\w*$", line)]
        print(f"needs: {', '.join(needed)}")
        print(f"defines sqlite3_open_v2 {len(opens)} time(s); exports {len(exported)} SQLite functions")
        if len(opens) != 1:
            problems.append(f"sqlite3_open_v2 is defined {len(opens)} times")
        if not any(line.endswith(" potluckdb_version") for line in defined):
            problems.append("potluckdb_version is not defined")
        if exported:
            problems.append(f"exports {exported[:5]}")
    elif data[:2] == b"MZ":
        needed = pe_imports(data)
        print(f"imports: {', '.join(needed)}")
    else:  # Mach-O
        needed = [line.split()[0] for line in run("otool", "-L", str(program)).splitlines()[1:]]
        exported = [s for s in run("nm", "-gU", str(program)).split() if re.match(r"_(sqlite3|potluckdb)", s)]
        print(f"needs: {', '.join(needed)}")
        if exported:
            problems.append(f"exports {exported[:5]}")
    shared = [n for n in needed if re.search(r"sqlite3", n, re.I)]
    if shared:
        problems.append(f"loads a shared SQLite: {shared}")

    for problem in problems:
        print(f"problem: {problem}")
    if problems:
        sys.exit(1)
    print(f"ok: {program.name} contains PotluckDB's SQLite and no other")


if __name__ == "__main__":
    main()
