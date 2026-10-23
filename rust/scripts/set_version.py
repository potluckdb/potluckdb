"""Sets the PotluckDB version of the Rust packages.

- rust/potluckdb/Cargo.toml (and the Cargo.lock files that list it): the
  version of the potluckdb crate;
- potluckdb_release.rs in rust/libsqlite3-sys/ and each of its folders: the
  release PotluckDB's libsqlite3-sys links, with the SHA-256 of every
  platform's archive when --sha256sums gives the release's SHA256SUMS;
- the READMEs: the version in their examples.

Usage: python3 rust/scripts/set_version.py 0.8.0-dev.1 [--sha256sums SHA256SUMS]
"""
import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent  # rust/
PLATFORMS = ["linux-x64-gnu", "linux-arm64-gnu", "linux-x64-musl", "linux-arm64-musl",
             "macos-arm64", "macos-x64", "windows-x64", "windows-arm64"]
VERSION = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")
RELEASE = """// The PotluckDB release this crate links, written by rust/scripts/set_version.py.
// In a release (git tag rust-v<version>) it also lists the SHA-256 of each
// platform's archive, so that the build accepts only those exact files;
// without them it checks the release's SHA256SUMS.
const POTLUCKDB_VERSION: &str = "{version}";
const POTLUCKDB_SHA256: &[(&str, &str)] = &[{sums}];
"""


def archive_sums(path, version):
    sums = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2:
            sums[parts[1].lstrip("*")] = parts[0].lower()
    found = []
    for platform in PLATFORMS:
        name = f"potluckdb-sqlite-{version}-{platform}.{'zip' if platform.startswith('windows') else 'tar.gz'}"
        if name not in sums:
            sys.exit(f"{path} does not list {name}")
        found.append((platform, sums[name]))
    return found


def write(path, text):
    if path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"updated {path.relative_to(ROOT.parent).as_posix()}")


def substitute(path, pattern, replacement, flags=0, count=0):
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(pattern, replacement, text, count=count, flags=flags)
    if n == 0:
        sys.exit(f"{path}: found no {pattern!r}")
    write(path, new)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("--sha256sums", help="the release's SHA256SUMS, to record each archive's SHA-256")
    args = parser.parse_args(argv)
    version = args.version.removeprefix("v")
    if not VERSION.match(version):
        sys.exit(f"not a version: {args.version}")

    substitute(ROOT / "potluckdb" / "Cargo.toml", r'^version = "[^"]*"$', f'version = "{version}"',
               flags=re.M, count=1)
    for lock in ROOT.rglob("Cargo.lock"):
        if "target" in lock.relative_to(ROOT).parts:
            continue
        text = lock.read_text(encoding="utf-8")
        write(lock, re.sub(r'(\[\[package\]\]\nname = "potluckdb"\nversion = )"[^"]*"\n(?!source)',
                           rf'\1"{version}"\n', text))

    sums = archive_sums(args.sha256sums, version) if args.sha256sums else []
    listed = "".join(f'\n    ("{platform}", "{sha}"),' for platform, sha in sums) + ("\n" if sums else "")
    release = RELEASE.format(version=version, sums=listed)
    sys_dir = ROOT / "libsqlite3-sys"
    for path in [sys_dir / "potluckdb_release.rs", *sorted(sys_dir.glob("*/potluckdb_release.rs"))]:
        write(path, release)

    for readme in [ROOT / "README.md", ROOT / "potluckdb" / "README.md"]:
        text = readme.read_text(encoding="utf-8")
        text = re.sub(r"rust-v\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", f"rust-v{version}", text)
        text = re.sub(r'potluckdb = "=[^"]*"', f'potluckdb = "={version}"', text)
        write(readme, text)


if __name__ == "__main__":
    main()
