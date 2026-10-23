"""Writes rust/libsqlite3-sys/<line>/: libsqlite3-sys from crates.io, made to
link PotluckDB's SQLite. Apps use one through [patch.crates-io].

Each folder is the published libsqlite3-sys crate (MIT, the rusqlite
developers), checked against the crates.io index, with these changes:
- the bundled SQLite and SQLCipher sources are left out (never compiled here);
- build.rs: libsqlite3-sys's `main` is renamed `upstream_main`, and a new
  `main` runs potluckdb_core::configure() first (see potluckdb_core.rs);
- Cargo.toml: `publish = false`, and PotluckDB's description, licence and
  links. Name, version, `links`, features and dependencies stay as published,
  so the folder stands in for exactly that libsqlite3-sys version.

Usage:
    python3 rust/scripts/vendor_libsqlite3_sys.py            # write every line in VERSIONS
    python3 rust/scripts/vendor_libsqlite3_sys.py --check    # fail if a folder differs
"""
import argparse
import difflib
import hashlib
import io
import json
import pathlib
import re
import sys
import tarfile
import urllib.request

# One folder per libsqlite3-sys line that PotluckDB supports:
# 0.38: rusqlite 0.40, diesel 2.3; 0.37: rusqlite 0.39, sqlx 0.9 (and diesel).
VERSIONS = ["0.38.2", "0.37.0"]

ROOT = pathlib.Path(__file__).resolve().parent.parent  # rust/
SYS = ROOT / "libsqlite3-sys"
OURS = ["potluckdb_core.rs", "potluckdb_release.rs"]  # copied from rust/libsqlite3-sys/
KEEP = re.compile(r"^(build\.rs|Cargo\.toml|LICENSE|wrapper(_ext)?\.h|src/.*|bindgen-bindings/.*"
                  r"|sqlite3/bindgen_bundled_version(_ext)?\.rs)$")
USER_AGENT = "potluckdb-vendor (https://github.com/potluckdb/potluckdb)"

README = """# libsqlite3-sys {version}, linking PotluckDB's SQLite

This folder is [libsqlite3-sys {version}](https://crates.io/crates/libsqlite3-sys/{version})
from crates.io, changed to link PotluckDB's build of SQLite instead of its
bundled or the system SQLite. Apps use it through `[patch.crates-io]`; see
[rust/README.md](../../README.md).

It is written by `rust/scripts/vendor_libsqlite3_sys.py`; don't edit it by
hand. What changed from the published crate:

- `build.rs`: libsqlite3-sys's `main` is renamed `upstream_main`; the new
  `main` at the end runs `potluckdb_core::configure()` first, which finds or
  downloads PotluckDB's library and points libsqlite3-sys's own build logic
  at it.
- `potluckdb_core.rs`, `potluckdb_release.rs`: added.
- `Cargo.toml`: `publish = false`, description, licence and links.
- The bundled SQLite and SQLCipher sources are left out.

## Licence

- Files from libsqlite3-sys: MIT, see `LICENSE-MIT`.
- `potluckdb_core.rs`, `potluckdb_release.rs` and the end of `build.rs`:
  Apache-2.0, see the repository's `LICENSE`.
- The SQLite library linked at build time is not part of this folder. It
  comes with the PotluckDB binary licence (`LICENSE.txt` in its archive) and
  SQLite's public-domain notice (`THIRD_PARTY_NOTICES.txt`).
"""

BUILD_RS_TAIL = """
// PotluckDB (Apache-2.0): link PotluckDB's SQLite. `upstream_main` above is
// libsqlite3-sys's own `main`, unchanged; `configure` first sets the
// environment variables it reads (see potluckdb_core.rs).
#[path = "potluckdb_core.rs"]
mod potluckdb_core;

fn main() {
    potluckdb_core::configure();
    upstream_main();
}
"""


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def published_crate(version):
    """The .crate file of libsqlite3-sys `version`, checked against the index."""
    index = fetch("https://index.crates.io/li/bs/libsqlite3-sys").decode()
    entries = [json.loads(line) for line in index.splitlines() if line.strip()]
    entry = next((e for e in entries if e["vers"] == version), None)
    if entry is None:
        sys.exit(f"libsqlite3-sys {version} is not on crates.io")
    if entry.get("yanked"):
        sys.exit(f"libsqlite3-sys {version} is yanked")
    data = fetch(f"https://static.crates.io/crates/libsqlite3-sys/libsqlite3-sys-{version}.crate")
    if hashlib.sha256(data).hexdigest() != entry["cksum"]:
        sys.exit(f"libsqlite3-sys-{version}.crate does not match the crates.io index")
    return data, entry["cksum"]


def edit_build_rs(text, version):
    count = len(re.findall(r"^fn main\(\) \{$", text, flags=re.M))
    if count != 1:
        sys.exit(f"libsqlite3-sys {version}: build.rs has {count} `fn main() {{` lines, expected 1")
    return re.sub(r"^fn main\(\) \{$", "fn upstream_main() {", text, flags=re.M) + BUILD_RS_TAIL


def edit_cargo_toml(text, version, cksum):
    replacements = {
        "description": '"libsqlite3-sys, linking PotluckDB\'s SQLite instead of the bundled or system one. '
                       'The library is downloaded at build time and comes with the PotluckDB binary licence. '
                       'Use it through [patch.crates-io]."',
        "license": '"MIT AND Apache-2.0"',
        "repository": '"https://github.com/potluckdb/potluckdb"',
    }
    for key, value in replacements.items():
        text, count = re.subn(rf"^{key} = .*$", f"{key} = {value}", text, count=1, flags=re.M)
        if count != 1:
            sys.exit(f"libsqlite3-sys {version}: Cargo.toml has no `{key}`")
    text, count = re.subn(r'^(version = "[^"]+")$',
                          r'\1\npublish = false\nhomepage = "https://docs.potluckdb.com"', text, count=1, flags=re.M)
    if count != 1:
        sys.exit(f"libsqlite3-sys {version}: Cargo.toml has no version")
    header = (f"# libsqlite3-sys {version} from crates.io, made to link PotluckDB's SQLite by\n"
              "# rust/scripts/vendor_libsqlite3_sys.py. Don't edit it by hand.\n"
              f"# SHA-256 of the published crate: {cksum}\n#\n")
    return header + text


def render(version):
    """{relative path: bytes} of the folder for `version`."""
    data, cksum = published_crate(version)
    prefix = f"libsqlite3-sys-{version}/"
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.startswith(prefix):
                continue
            name = member.name[len(prefix):]
            if KEEP.match(name):
                files[name] = tar.extractfile(member).read()
    for required in ["build.rs", "Cargo.toml", "LICENSE", "src/lib.rs", "sqlite3/bindgen_bundled_version.rs"]:
        if required not in files:
            sys.exit(f"libsqlite3-sys {version}: the crate has no {required}")
    files["build.rs"] = edit_build_rs(files["build.rs"].decode(), version).encode()
    files["Cargo.toml"] = edit_cargo_toml(files["Cargo.toml"].decode(), version, cksum).encode()
    files["LICENSE-MIT"] = files.pop("LICENSE")
    files["README.md"] = README.format(version=version).encode()
    for name in OURS:
        files[name] = (SYS / name).read_bytes()
    return files


def folder(version):
    return SYS / ".".join(version.split(".")[:2])


def existing(path):
    if not path.is_dir():
        return {}
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="only check that the folders are up to date")
    args = parser.parse_args(argv)
    stale = []
    for version in VERSIONS:
        wanted = render(version)
        path = folder(version)
        have = existing(path)
        if have == wanted:
            print(f"{path.relative_to(ROOT.parent).as_posix()}: up to date (libsqlite3-sys {version})")
            continue
        if args.check:
            for name in sorted(set(have) | set(wanted)):
                if have.get(name) != wanted.get(name):
                    stale.append(f"{path.name}/{name}")
                    old = have.get(name, b"").decode(errors="replace").splitlines()
                    new = wanted.get(name, b"").decode(errors="replace").splitlines()
                    sys.stdout.writelines(line + "\n" for line in list(difflib.unified_diff(
                        old, new, f"committed/{name}", f"generated/{name}", lineterm=""))[:40])
            continue
        for name in set(have) - set(wanted):
            (path / name).unlink()
        for name, content in wanted.items():
            target = path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        print(f"{path.relative_to(ROOT.parent).as_posix()}: written from libsqlite3-sys {version}")
    if stale:
        sys.exit("out of date (run python3 rust/scripts/vendor_libsqlite3_sys.py): " + ", ".join(stale))


if __name__ == "__main__":
    main()
