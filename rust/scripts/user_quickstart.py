"""Runs the README's quickstarts the way a user does, after a release: new apps
with rusqlite and with sqlx, the potluckdb crate from crates.io, and
[patch.crates-io] pointing at the rust-v<version> tag on GitHub. The build
downloads PotluckDB's library from the GitHub release.

Usage: python3 rust/scripts/user_quickstart.py --version 0.8.0-dev.1
         [--repository https://github.com/potluckdb/potluckdb]
"""
import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent  # rust/
APPS = {
    # name: (dependencies, libsqlite3-sys line, main.rs)
    "rusqlite": ('rusqlite = { version = "0.40", features = ["bundled"] }', "0.38",
                 ROOT / "examples" / "quickstart" / "src" / "main.rs"),
    "sqlx": ('sqlx = { version = "0.9", default-features = false, features = ["runtime-tokio", "sqlite"] }\n'
             'tokio = { version = "1", features = ["macros", "rt"] }', "0.37",
             ROOT / "tests" / "sqlx" / "src" / "main.rs"),
}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--repository", default="https://github.com/potluckdb/potluckdb")
    parser.add_argument("--attempts", type=int, default=10, help="tries, a minute apart, while crates.io catches up")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        for name, (dependencies, line, main_rs) in APPS.items():
            app = pathlib.Path(tmp) / name
            (app / "src").mkdir(parents=True)
            shutil.copy(main_rs, app / "src" / "main.rs")
            (app / "Cargo.toml").write_text(f"""[package]
name = "quickstart-{name}"
version = "0.0.0"
edition = "2021"

[dependencies]
{dependencies}
potluckdb = "={args.version}"

[patch.crates-io]
libsqlite3-sys = {{ git = "{args.repository}", tag = "rust-v{args.version}", version = "{line}" }}
""", encoding="utf-8")
            for attempt in range(1, args.attempts + 1):
                print(f"$ cargo run ({name}, attempt {attempt})", flush=True)
                result = subprocess.run(["cargo", "run", "--quiet"], cwd=app, text=True, capture_output=True)
                print(result.stdout + result.stderr, flush=True)
                if result.returncode == 0 or attempt == args.attempts:
                    break
                time.sleep(60)
            words = result.stdout.split()
            if result.returncode or not words or words[0] != args.version:
                sys.exit(f"the {name} quickstart did not print PotluckDB {args.version}")
            print(f"ok: the {name} quickstart runs on PotluckDB {args.version}, SQLite {words[1]}")


if __name__ == "__main__":
    main()
