"""Makes the native library for one target from its core archive and checks it.

- Linux and macOS: builds libpotluckdb_dotnet.so / .dylib from
  native/potluckdb_dotnet.c and the core's static library. It exports only
  potluckdb_dotnet_symbol(). Needs a C compiler (cc, or $CC) and nm.
- Windows: the core's bin/sqlite3.dll, renamed potluckdb_dotnet.dll.

The result goes to artifacts/native/<rid>/, with the core's BUILD-INFO.json,
LICENSE.txt and THIRD_PARTY_NOTICES.txt; scripts/pack.py packs it from there.

The check (also run on its own with --check) makes sure that the library:
- exports nothing that could clash with another SQLite in the process
  (Linux, macOS), or exports the SQLite API (Windows);
- has PotluckDB's own SONAME (Linux) or install name (macOS);
- runs on the oldest systems PotluckDB supports: glibc 2.28, macOS 11, and
  needs nothing but the C library (Linux), libSystem (macOS), kernel32 (Windows);
- is built for the target's CPU.

Usage: python3 scripts/native.py --target <target> [--version <version>]
       python3 scripts/native.py --target <target> --check <file>
Linux checks need readelf, nm and objdump; macOS checks need nm, otool and lipo.
"""
import argparse
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import ROOT, default_version, get_core  # noqa: E402
from targets import TARGETS, library_name  # noqa: E402

LOOKUP = "potluckdb_dotnet_symbol"
MIN_GLIBC = "2.28"
MIN_MACOS = "11.0"
GLIBC_NEEDS = {"libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0"}
ELF_MACHINE = {"x64": "Advanced Micro Devices X86-64", "arm64": "AArch64"}
MACHO_ARCH = {"x64": "x86_64", "arm64": "arm64"}


def run(*command):
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def version_tuple(v):
    return tuple(int(x) for x in v.split("."))


def exported_api(target, shared):
    """(name, is_function) for each symbol the core's shared library exports."""
    t = TARGETS[target]
    if t["os"] == "linux":
        lines = run("nm", "-D", "--defined-only", str(shared)).splitlines()
    else:
        lines = run("nm", "-gU", str(shared)).splitlines()
    symbols = []
    for line in lines:
        parts = line.split()
        if len(parts) != 3:
            continue
        kind, name = parts[1], parts[2]
        if t["os"] == "macos":
            name = name[1:]  # C names have a leading underscore on macOS
        if name.startswith(("sqlite3", "potluckdb_")):
            symbols.append((name, kind in "TtWw"))
    if not any(name == "potluckdb_version" for name, _ in symbols):
        raise SystemExit(f"{shared} does not export potluckdb_version: not a PotluckDB library")
    return sorted(symbols, key=lambda s: s[0].encode())  # strcmp order, as bsearch needs


def build_shim(target, core, out_file):
    t = TARGETS[target]
    shared = core / "lib" / ("libsqlite3.so.0" if t["os"] == "linux" else "libsqlite3.0.dylib")
    static = core / "lib" / "static" / "libsqlite3.a"
    cc = shlex.split(os.environ.get("CC", "cc"))
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        symbols = exported_api(target, shared)
        (tmp / "symbols.h").write_text(
            "".join(f"{'FUNCTION' if function else 'DATA'}({name})\n" for name, function in symbols))
        source = ROOT / "native" / "potluckdb_dotnet.c"
        common = ["-O2", "-fvisibility=hidden", "-Wall", "-Werror", "-I", str(tmp), str(source), str(static)]
        if t["os"] == "linux":
            (tmp / "exports.map").write_text(f"{{ global: {LOOKUP}; local: *; }};\n")
            command = cc + ["-shared", "-fPIC", "-o", str(out_file)] + common + [
                f"-Wl,-soname,{out_file.name}", f"-Wl,--version-script,{tmp / 'exports.map'}",
                "-Wl,--exclude-libs,ALL", "-Wl,--no-undefined", "-Wl,-z,now", "-Wl,-z,relro",
                "-Wl,-z,noexecstack", "-s", "-lm", "-ldl", "-lpthread"]
        else:
            command = cc + ["-dynamiclib", "-arch", MACHO_ARCH[t["cpu"]], f"-mmacosx-version-min={MIN_MACOS}",
                            "-o", str(out_file)] + common + [
                f"-Wl,-install_name,@rpath/{out_file.name}", f"-Wl,-exported_symbol,_{LOOKUP}", "-Wl,-x"]
        print(" ".join(command))
        subprocess.run(command, check=True)
    print(f"{out_file}: {len(symbols)} API symbols, {out_file.stat().st_size} bytes")


def build(target, version):
    core = get_core(target, version)
    out_dir = ROOT / "artifacts" / "native" / TARGETS[target]["rid"]
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    out_file = out_dir / library_name(target)
    if TARGETS[target]["os"] == "windows":
        shutil.copyfile(core / "bin" / "sqlite3.dll", out_file)
        print(f"{out_file}: the core's bin/sqlite3.dll, renamed")
    else:
        build_shim(target, core, out_file)
    for file in ("BUILD-INFO.json", "LICENSE.txt", "THIRD_PARTY_NOTICES.txt"):
        shutil.copyfile(core / file, out_dir / file)
    return out_file


# --- checks -----------------------------------------------------------------

def check_linux(file, t):
    problems = []
    exported = [l.split()[-1] for l in run("nm", "-D", "--defined-only", str(file)).splitlines() if l.strip()]
    print(f"exports: {', '.join(exported)}")
    if exported != [LOOKUP]:
        problems.append(f"exports {exported}, not only {LOOKUP}")
    dynamic = run("readelf", "-d", str(file))
    soname = re.findall(r"\(SONAME\)\s+Library soname: \[(.+)\]", dynamic)
    needed = set(re.findall(r"\(NEEDED\)\s+Shared library: \[(.+)\]", dynamic))
    print(f"SONAME: {soname}; needs: {', '.join(sorted(needed))}")
    if soname != [file.name]:
        problems.append(f"SONAME is {soname}, not {file.name}")
    if "TEXTREL" in dynamic:
        problems.append("has text relocations")
    machine = re.search(r"Machine:\s+(.+)", run("readelf", "-h", str(file))).group(1).strip()
    if machine != ELF_MACHINE[t["cpu"]]:
        problems.append(f"built for {machine}, not {t['cpu']}")
    glibc = sorted(set(re.findall(r"\bGLIBC_(\d+(?:\.\d+)*)\b", run("objdump", "-T", str(file)))), key=version_tuple)
    if t["libc"] == "glibc":
        print(f"needs glibc {glibc[-1] if glibc else '(any)'}")
        if glibc and version_tuple(glibc[-1]) > version_tuple(MIN_GLIBC):
            problems.append(f"needs glibc {glibc[-1]}, more than {MIN_GLIBC}")
        if not needed <= GLIBC_NEEDS:
            problems.append(f"needs {', '.join(sorted(needed - GLIBC_NEEDS))}")
    else:
        if glibc:
            problems.append(f"musl build needs glibc {glibc[-1]}")
        if len(needed) != 1 or not next(iter(needed)).startswith("libc.musl-"):
            problems.append(f"needs {', '.join(sorted(needed))}, not only musl's libc")
    return problems


def check_macos(file, t):
    problems = []
    exported = [l.split()[-1] for l in run("nm", "-gU", str(file)).splitlines() if l.strip()]
    print(f"exports: {', '.join(exported)}")
    if exported != [f"_{LOOKUP}"]:
        problems.append(f"exports {exported}, not only _{LOOKUP}")
    install_name = run("otool", "-D", str(file)).splitlines()[-1].strip()
    deps = [l.split(" (")[0].strip() for l in run("otool", "-L", str(file)).splitlines()[1:]]
    deps = [d for d in deps if d != install_name]
    print(f"install name: {install_name}; needs: {', '.join(deps)}")
    if install_name != f"@rpath/{file.name}":
        problems.append(f"install name is {install_name}, not @rpath/{file.name}")
    if deps != ["/usr/lib/libSystem.B.dylib"]:
        problems.append(f"needs {deps}, not only libSystem")
    minos = re.search(r"cmd LC_BUILD_VERSION\n(?:.*\n)*?\s*minos (\S+)|cmd LC_VERSION_MIN_MACOSX\n(?:.*\n)*?\s*version (\S+)",
                      run("otool", "-l", str(file)))
    minos = minos and (minos.group(1) or minos.group(2))
    print(f"minimum macOS: {minos}")
    if not minos or version_tuple(minos) > version_tuple(MIN_MACOS):
        problems.append(f"needs macOS {minos}, more than {MIN_MACOS}")
    archs = run("lipo", "-archs", str(file)).strip()
    if archs != MACHO_ARCH[t["cpu"]]:
        problems.append(f"built for {archs}, not {t['cpu']}")
    return problems


def pe_info(file):
    """CPU, imported DLLs and exported names of a Windows DLL, from its PE headers."""
    b = file.read_bytes()
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    if b[pe:pe + 4] != b"PE\0\0":
        raise SystemExit(f"{file} is not a PE file")
    machine, sections = struct.unpack_from("<HH", b, pe + 4)
    optional_size = struct.unpack_from("<H", b, pe + 20)[0]
    optional = pe + 24
    directories = optional + (112 if struct.unpack_from("<H", b, optional)[0] == 0x20B else 96)
    # Each section header: virtual address, size of raw data, pointer to raw data.
    table = [struct.unpack_from("<III", b, optional + optional_size + 40 * i + 12) for i in range(sections)]

    def offset(rva):
        for va, size, raw in table:
            if va <= rva < va + size:
                return rva - va + raw
        raise SystemExit(f"{file}: RVA {rva:#x} is in no section")

    def string(at):
        return b[at:b.index(0, at)].decode("latin1")

    names = []
    export_rva = struct.unpack_from("<I", b, directories)[0]
    if export_rva:
        d = offset(export_rva)
        count, names_rva = struct.unpack_from("<I", b, d + 24)[0], struct.unpack_from("<I", b, d + 32)[0]
        names = [string(offset(struct.unpack_from("<I", b, offset(names_rva) + 4 * i)[0])) for i in range(count)]
    imports = []
    import_rva = struct.unpack_from("<I", b, directories + 8)[0]
    if import_rva:
        d = offset(import_rva)
        while struct.unpack_from("<I", b, d + 12)[0]:
            imports.append(string(offset(struct.unpack_from("<I", b, d + 12)[0])))
            d += 20
    return {0x8664: "x64", 0xAA64: "arm64"}.get(machine, hex(machine)), imports, names


def check_windows(file, t):
    problems = []
    machine, imports, names = pe_info(file)
    print(f"CPU: {machine}; needs: {', '.join(imports)}; exports {len(names)} names")
    if machine != t["cpu"]:
        problems.append(f"built for {machine}, not {t['cpu']}")
    if [i.lower() for i in imports] != ["kernel32.dll"]:
        problems.append(f"needs {imports}, not only kernel32.dll")
    for name in ("potluckdb_version", "sqlite3_open_v2", "sqlite3_prepare_v2"):
        if name not in names:
            problems.append(f"does not export {name}")
    return problems


def check(file, target):
    t = TARGETS[target]
    print(f"checking {file} ({target})")
    problems = {"linux": check_linux, "macos": check_macos, "windows": check_windows}[t["os"]](Path(file), t)
    for problem in problems:
        print(f"problem: {problem}", file=sys.stderr)
    if problems:
        raise SystemExit(1)
    print("ok: can't clash with another SQLite in the process, and fits the oldest supported systems")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--target", required=True, choices=TARGETS)
    parser.add_argument("--version", default=None)
    parser.add_argument("--check", metavar="FILE", help="only check this file")
    args = parser.parse_args()
    if args.check:
        check(args.check, args.target)
    else:
        check(build(args.target, args.version or default_version()), args.target)


if __name__ == "__main__":
    main()
