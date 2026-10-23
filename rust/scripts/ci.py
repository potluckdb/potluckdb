"""The CI steps for one platform, run from anywhere:

1. set the packages' version (scripts/set_version.py), recording the
   archives' SHA-256 when the core folder has SHA256SUMS;
2. test the potluckdb crate (cargo test);
3. run the quickstart with rusqlite (bundled feature on) and with sqlx, and
   check each program has PotluckDB's SQLite and no other (check_binary.py);
4. run rusqlite's own test suite (rusqlite_suite.py);
5. check that an app without the [patch.crates-io] entry fails to build with
   potluckdb's explanation;
6. build the quickstart the way users do, downloading the archive, from a
   local web server standing in for the GitHub release; and check that a
   changed archive is refused.

Usage: python3 rust/scripts/ci.py --version 0.8.0-dev.1 --core-dir <folder with the release's archives>
         [--target <rust target>] [--skip-suite]
"""
import argparse
import functools
import http.server
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent  # rust/
SCRIPTS = ROOT / "scripts"


def step(title):
    print(f"\n=== {title}", flush=True)


def run(command, cwd=ROOT, env=None, check=True, capture=False):
    print("$ " + " ".join(str(c) for c in command), flush=True)
    result = subprocess.run([str(c) for c in command], cwd=cwd, env=env, text=True, encoding="utf-8",
                            errors="replace", stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.STDOUT if capture else None)
    if capture:
        print(result.stdout, end="", flush=True)
    if check and result.returncode:
        sys.exit(f"failed ({result.returncode}): {' '.join(str(c) for c in command)}")
    return result


def host_platform():
    import platform
    machine = platform.machine().lower()
    cpu = "arm64" if machine in ("arm64", "aarch64") else "x64"
    if sys.platform == "darwin":
        return f"macos-{cpu}"
    if sys.platform == "win32":
        return f"windows-{cpu}"
    libc = "musl" if pathlib.Path("/etc/alpine-release").exists() or "musl" in os.popen("ldd --version 2>&1").read() else "gnu"
    return f"linux-{cpu}-{libc}"


def target_platform(target):
    """The PotluckDB platform of a Rust target triple."""
    arch, _, rest = target.partition("-")
    cpu = {"x86_64": "x64", "aarch64": "arm64"}[arch]
    if "apple-darwin" in rest:
        return f"macos-{cpu}"
    if "windows-msvc" in rest:
        return f"windows-{cpu}"
    return f"linux-{cpu}-{'musl' if rest.endswith('musl') else 'gnu'}"


def build_info(archive):
    path = str(archive)
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            return json.loads(z.read(next(n for n in z.namelist() if n.endswith("/BUILD-INFO.json"))))
    with tarfile.open(path) as t:
        member = next(m for m in t.getmembers() if m.name.endswith("/BUILD-INFO.json"))
        return json.load(t.extractfile(member))


def quickstart(workspace, package, cargo_args, target_dir, triple, expected, archive, env):
    run(["cargo", "build", "--locked", "-p", package, *cargo_args], cwd=workspace, env=env)
    exe = target_dir / (triple or "") / "debug" / (package + (".exe" if archive.name.endswith(".zip") else ""))
    output = run([exe], env=env, capture=True).stdout.strip()
    if output != expected:
        sys.exit(f"{binary} printed {output!r}, expected {expected!r}")
    run([sys.executable, SCRIPTS / "check_binary.py", exe, archive])


def serve(directory):
    """Serves `directory` on a local port; returns its URL."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--core-dir", required=True, type=pathlib.Path)
    parser.add_argument("--target", help="Rust target triple, when not the host's")
    parser.add_argument("--skip-suite", action="store_true", help="skip rusqlite's test suite")
    args = parser.parse_args(argv)
    version = args.version
    core_dir = args.core_dir.resolve()
    platform = target_platform(args.target) if args.target else host_platform()
    archive = core_dir / f"potluckdb-sqlite-{version}-{platform}.{'zip' if platform.startswith('windows') else 'tar.gz'}"
    if not archive.is_file():
        sys.exit(f"no {archive}")
    expected = f"{version} {build_info(archive)['sqlite_version']}"
    env = dict(os.environ, POTLUCKDB_CORE_DIR=str(core_dir))
    env.pop("POTLUCKDB_CORE_VERSION", None)
    cargo_args = ["--target", args.target] if args.target else []
    target_dir = pathlib.Path(env["CARGO_TARGET_DIR"]) if env.get("CARGO_TARGET_DIR") else None
    print(f"PotluckDB {version}, platform {platform}, expecting the quickstart to print {expected!r}")

    step("Version")
    sums = core_dir / "SHA256SUMS"
    run([sys.executable, SCRIPTS / "set_version.py", version, *(["--sha256sums", sums] if sums.is_file() else [])])

    step("potluckdb crate tests")
    run(["cargo", "test", "--locked", *cargo_args], env=env)

    step("Quickstart with rusqlite")
    quickstart(ROOT, "quickstart", cargo_args, target_dir or ROOT / "target", args.target, expected, archive, env)

    step("Quickstart with sqlx")
    sqlx = ROOT / "tests" / "sqlx"
    quickstart(sqlx, "quickstart-sqlx", cargo_args, target_dir or sqlx / "target", args.target, expected, archive, env)

    if not args.skip_suite:
        step("rusqlite's test suite")
        suite_env = dict(env, CARGO_TARGET_DIR=str((target_dir or ROOT / "target") / "rusqlite-suite-build"))
        run([sys.executable, SCRIPTS / "rusqlite_suite.py", "--features", "bundled-full",
             *(["--target", args.target] if args.target else [])], env=suite_env)

    step("An app without the [patch.crates-io] entry fails to build, with an explanation")
    result = run(["cargo", "check", "--locked", *cargo_args], cwd=ROOT / "tests" / "no-patch", env=env,
                 check=False, capture=True)
    if result.returncode == 0 or "error: potluckdb: this build has the standard libsqlite3-sys" not in result.stdout:
        sys.exit("the build without [patch.crates-io] did not fail with potluckdb's explanation")

    step("Quickstart downloading the archive, as users do (local stand-in for the GitHub release)")
    with tempfile.TemporaryDirectory() as tmp:
        release = pathlib.Path(tmp) / "releases" / f"v{version}"
        release.mkdir(parents=True)
        shutil.copy(archive, release)
        if sums.is_file():
            shutil.copy(sums, release)
        download_env = {k: v for k, v in env.items() if k != "POTLUCKDB_CORE_DIR"}
        download_env["POTLUCKDB_DOWNLOAD_URL"] = serve(release.parent)
        download_env["CARGO_TARGET_DIR"] = str(pathlib.Path(tmp) / "target")
        quickstart(ROOT, "quickstart", cargo_args, pathlib.Path(tmp) / "target", args.target, expected, archive,
                   download_env)
        with open(release / archive.name, "ab") as f:
            f.write(b"changed")
        result = run(["cargo", "build", "--locked", "-p", "quickstart", *cargo_args],
                     env=dict(download_env, CARGO_TARGET_DIR=str(pathlib.Path(tmp) / "target-changed")),
                     check=False, capture=True)
        if result.returncode == 0 or "does not match the SHA-256" not in result.stdout:
            sys.exit("a changed archive was not refused")

    print(f"\nok: all Rust checks passed on {platform}")


if __name__ == "__main__":
    main()
