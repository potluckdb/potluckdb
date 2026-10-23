"""Puts native libraries made elsewhere (CI artifacts from scripts/native.py)
into artifacts/native/<rid>/, where scripts/pack.py looks for them. Each one
is a folder with BUILD-INFO.json, anywhere under <dir>; the target in
BUILD-INFO.json says which platform it is for.

Usage: python3 scripts/collect.py <dir>
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import ROOT  # noqa: E402
from targets import TARGETS, library_name  # noqa: E402


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    found = 0
    for info in sorted(Path(sys.argv[1]).rglob("BUILD-INFO.json")):
        target = json.loads(info.read_text(encoding="utf-8"))["target"]
        if target not in TARGETS or not (info.parent / library_name(target)).exists():
            raise SystemExit(f"{info.parent} holds no native library for a known target ({target})")
        destination = ROOT / "artifacts" / "native" / TARGETS[target]["rid"]
        shutil.rmtree(destination, ignore_errors=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(info.parent, destination)
        print(f"{target}: {destination}")
        found += 1
    if not found:
        raise SystemExit(f"no native libraries under {sys.argv[1]}")


if __name__ == "__main__":
    main()
