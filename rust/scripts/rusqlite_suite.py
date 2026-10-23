"""Runs rusqlite's own test suite against PotluckDB's SQLite.

Downloads the published rusqlite crate (checked against the crates.io index)
into rust/target/rusqlite-suite/, patches libsqlite3-sys to PotluckDB's
(rust/libsqlite3-sys/<line>), and runs `cargo test` with the locked
dependencies in rust/tests/rusqlite-suite/Cargo.lock. Fails on any failure
not listed in rust/tests/rusqlite-suite/known-failures.txt.

Usage: python3 rust/scripts/rusqlite_suite.py [--features bundled-full] [--update-lock]
"""
import argparse
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request

RUSQLITE = "0.40.2"
LINE = "0.38"  # the libsqlite3-sys line rusqlite 0.40 uses
ROOT = pathlib.Path(__file__).resolve().parent.parent  # rust/
SUITE = ROOT / "tests" / "rusqlite-suite"
USER_AGENT = "potluckdb-tests (https://github.com/potluckdb/potluckdb)"


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def unpack_rusqlite(work):
    index = fetch("https://index.crates.io/ru/sq/rusqlite").decode()
    entry = next(e for e in map(json.loads, filter(str.strip, index.splitlines())) if e["vers"] == RUSQLITE)
    data = fetch(f"https://static.crates.io/crates/rusqlite/rusqlite-{RUSQLITE}.crate")
    if hashlib.sha256(data).hexdigest() != entry["cksum"]:
        sys.exit(f"rusqlite-{RUSQLITE}.crate does not match the crates.io index")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        tar.extractall(work, filter="data")
    crate = work / f"rusqlite-{RUSQLITE}"
    manifest = crate / "Cargo.toml"
    sys_path = (ROOT / "libsqlite3-sys" / LINE).as_posix()
    manifest.write_text(manifest.read_text(encoding="utf-8")
                        + f'\n[patch.crates-io]\nlibsqlite3-sys = {{ path = "{sys_path}" }}\n\n[workspace]\n',
                        encoding="utf-8")
    return crate


def parse(output):
    """{"<test binary>: <test name>": "ok" | "FAILED" | "ignored"}"""
    results, binary = {}, "?"
    for line in output.splitlines():
        running = re.match(r"\s*Running (?:unittests )?(\S+)", line)
        if running:
            binary = running.group(1)
        elif re.match(r"\s*Doc-tests ", line):
            binary = "doc-tests"
        result = re.match(r"test (.+?) \.\.\. (ok|FAILED|ignored)", line)
        if result:
            results[f"{binary}: {result.group(1)}"] = result.group(2)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", default="bundled-full")
    parser.add_argument("--target", help="Rust target triple, when not the host's")
    parser.add_argument("--update-lock", action="store_true",
                        help="resolve the dependencies again and save the lock file")
    args = parser.parse_args(argv)

    crate = unpack_rusqlite(ROOT / "target" / "rusqlite-suite")
    lock = SUITE / "Cargo.lock"
    if not args.update_lock:
        shutil.copyfile(lock, crate / "Cargo.lock")
    command = ["cargo", "test", "--no-fail-fast", "--features", args.features]
    if args.target:
        command += ["--target", args.target]
    if not args.update_lock:
        command.insert(2, "--locked")
    print("$ " + " ".join(command), flush=True)
    env = dict(os.environ, RUST_BACKTRACE="0")
    process = subprocess.run(command, cwd=crate, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace")
    print(process.stdout)
    if args.update_lock:
        shutil.copyfile(crate / "Cargo.lock", lock)

    results = parse(process.stdout)
    known = {}
    for line in (SUITE / "known-failures.txt").read_text(encoding="utf-8").splitlines():
        name, _, reason = line.partition("#")
        if name.strip():
            known[name.strip()] = reason.strip()
    failed = sorted(name for name, result in results.items() if result == "FAILED")
    unexpected = [name for name in failed if name not in known]
    fixed = sorted(name for name in known if results.get(name) == "ok")
    counts = {r: sum(1 for v in results.values() if v == r) for r in ("ok", "FAILED", "ignored")}
    print(f"rusqlite {RUSQLITE} test suite on PotluckDB's SQLite (features: {args.features}): "
          f"{counts['ok']} passed, {counts['FAILED']} failed ({len(failed) - len(unexpected)} known), "
          f"{counts['ignored']} ignored")
    for name in failed:
        print(f"  failed: {name}" + (f"  (known: {known[name]})" if name in known else "  (NOT KNOWN)"))
    for name in fixed:
        print(f"  passes now, remove from known-failures.txt: {name}")
    if not results:
        sys.exit("no test results: the suite did not build")
    if unexpected:
        sys.exit(f"{len(unexpected)} unexpected failures")
    if process.returncode and not failed:
        sys.exit(f"cargo test exited with {process.returncode}")


if __name__ == "__main__":
    main()
