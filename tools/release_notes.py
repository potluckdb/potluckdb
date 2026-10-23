"""Turn the change notes in changes/ into release notes and a CHANGELOG entry.

Every change that users can notice adds one file to changes/ (see
changes/README.md). A release collects them, writes the notes, prepends them
to CHANGELOG.md and deletes the collected files.

Usage:
    python tools/release_notes.py --version 0.8.0-dev.1 [--extra-changes DIR ...]
                                  [--notes-out notes.md] [--date YYYY-MM-DD] [--dry-run]
    python tools/release_notes.py --version x --check   (validate only)
"""
import argparse
import datetime
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECTIONS = [  # (type in a change note, heading in the release notes)
    ("added", "Highlights"),
    ("changed", "Changes"),
    ("fixed", "Fixes"),
    ("compatibility", "Compatibility"),
    ("known-issue", "Known issues"),
]
VERIFY = """### Checksums and signatures

Every file is listed with its SHA-256 in `SHA256SUMS`, and each one has a
Sigstore signature (`<file>.sigstore.json`) made by PotluckDB's release
workflow. To check a download:

```sh
sha256sum --check --ignore-missing SHA256SUMS
cosign verify-blob --bundle <file>.sigstore.json \\
  --certificate-identity-regexp '^https://github.com/potluckdb/core/' \\
  --certificate-oidc-issuer https://token.actions.githubusercontent.com <file>
```
"""


def parse(path):
    """A change note: a `type:` line, a blank line, then the text."""
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if not lines or not lines[0].startswith("type:"):
        sys.exit(f"{path}: first line must be 'type: <{'|'.join(t for t, _ in SECTIONS)}|summary>'")
    kind = lines[0].split(":", 1)[1].strip()
    if kind not in {t for t, _ in SECTIONS} | {"summary"}:
        sys.exit(f"{path}: unknown type {kind!r}")
    text = " ".join(line.strip() for line in lines[1:] if line.strip())
    if not text:
        sys.exit(f"{path}: no text")
    return kind, text


def collect(dirs):
    notes = []
    for directory in dirs:
        for path in sorted(directory.glob("*.md")):
            if path.name != "README.md":
                notes.append((path, *parse(path)))
    return notes


def render(version, date, notes):
    by_kind = {}
    for _, kind, text in notes:
        by_kind.setdefault(kind, []).append(text)
    summary = by_kind.get("summary", by_kind.get("added", ["Maintenance release."]))[0]
    out = [f"## {version} ({date})", "", summary, ""]
    for kind, heading in SECTIONS:
        items = by_kind.get(kind, [])
        if kind == "added" and "summary" not in by_kind:
            items = items[1:]  # the first one is the summary already
        if items:
            out += [f"### {heading}", ""] + [f"- {item}" for item in items] + [""]
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--extra-changes", type=pathlib.Path, action="append", default=[])
    parser.add_argument("--notes-out", type=pathlib.Path)
    parser.add_argument("--date", default=datetime.date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true", help="only validate the change notes")
    args = parser.parse_args(argv)

    notes = collect([ROOT / "changes", *args.extra_changes])
    if args.check:
        print(f"ok: {len(notes)} valid change notes")
        return
    if not notes:
        sys.exit("no change notes: a release needs at least one user-visible change")
    entry = render(args.version, args.date, notes)
    if args.dry_run:
        print(entry)
        return
    changelog = ROOT / "CHANGELOG.md"
    head, _, rest = changelog.read_text(encoding="utf-8").partition("\n## ")
    changelog.write_text(head.rstrip() + "\n\n" + entry + ("\n## " + rest if rest else ""), encoding="utf-8")
    if args.notes_out:
        args.notes_out.write_text(entry.split("\n", 2)[2] + "\n" + VERIFY, encoding="utf-8")
    for path, _, _ in notes:
        path.unlink()
    print(f"release notes for {args.version}: {len(notes)} change notes")


if __name__ == "__main__":
    main()
