import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import release_notes  # noqa: E402


class RenderTest(unittest.TestCase):
    def notes(self, *items):
        return [(pathlib.Path(f"{i}.md"), kind, text) for i, (kind, text) in enumerate(items)]

    def test_first_added_note_is_the_summary(self):
        entry = release_notes.render("1.2.3", "2026-10-23", self.notes(
            ("added", "First thing."), ("added", "Second thing."), ("fixed", "A fix.")))
        self.assertEqual(entry.splitlines()[:3], ["## 1.2.3 (2026-10-23)", "", "First thing."])
        self.assertIn("### Highlights\n\n- Second thing.", entry)
        self.assertIn("### Fixes\n\n- A fix.", entry)
        self.assertNotIn("- First thing.", entry)

    def test_explicit_summary_keeps_all_added_notes(self):
        entry = release_notes.render("1.2.3", "2026-10-23", self.notes(
            ("summary", "The summary."), ("added", "Only thing.")))
        self.assertIn("The summary.", entry)
        self.assertIn("- Only thing.", entry)

    def test_bad_type_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "x.md"
            path.write_text("type: feature\n\nText.")
            with self.assertRaises(SystemExit):
                release_notes.parse(path)


if __name__ == "__main__":
    unittest.main()
