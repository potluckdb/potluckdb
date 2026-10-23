"""Release check for one potluckdb command archive: unpack it, check its
version, and sync two folders through a folder bucket.

Usage: python tests/release/cli_smoke.py <archive> <expected version>

Runs on Python 3.6 and newer, so it also runs in the oldest Linux images
the command supports.
"""
import pathlib
import platform
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def unpack(archive, into):
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(str(archive)) as z:
            z.extractall(str(into))
    else:
        with tarfile.open(str(archive)) as t:
            options = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
            t.extractall(str(into), **options)
    (root,) = [p for p in into.iterdir() if p.is_dir()]
    return root


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file() and ".potluckdb" not in p.parts}


def main():
    archive, expected = pathlib.Path(sys.argv[1]).resolve(), sys.argv[2]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        root = unpack(archive, tmp / "unpacked")
        exe = root / "bin" / ("potluckdb.exe" if platform.system() == "Windows" else "potluckdb")

        def run(*args):
            result = subprocess.run([str(exe)] + [str(a) for a in args], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, universal_newlines=True)
            if result.returncode != 0:
                sys.exit("potluckdb %s failed:\n%s" % (" ".join(str(a) for a in args), result.stdout))
            return result.stdout

        shown = run("--version")
        if expected not in shown:
            sys.exit("potluckdb --version says %r, expected %s" % (shown.strip(), expected))
        a, b, bucket = tmp / "a", tmp / "b", tmp / "bucket"
        (a / "docs").mkdir(parents=True)
        (a / "notes.txt").write_text("hello")
        (a / "docs" / "data.bin").write_bytes(bytes(range(256)) * 1000)
        run("sync", a, bucket)
        run("sync", b, bucket)
        (b / "notes.txt").write_text("edited on b")
        run("sync", b)
        run("sync", a)
        if files(a) != files(b) or files(a)["notes.txt"] != b"edited on b":
            sys.exit("the two folders did not end with the same files")
        history = run("history", a)
        if len(history.strip().splitlines()) != 2:
            sys.exit("expected 2 versions in the history:\n" + history)
        print("ok: potluckdb %s syncs two folders" % expected)


if __name__ == "__main__":
    main()
