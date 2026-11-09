"""Static publication checks; no ArcPy import is performed."""

from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {"26", "27", "28", "29", "31"}


class PublicationSafetyTests(unittest.TestCase):
    def test_only_five_selected_scripts_and_valid_python(self):
        scripts = sorted((ROOT / "scripts").glob("[0-9][0-9]_*.py"))
        self.assertEqual({s.name[:2] for s in scripts}, EXPECTED)
        for script in scripts:
            with self.subTest(script=script.name):
                ast.parse(script.read_text(encoding="utf-8"), filename=str(script))

    def test_personal_paths_and_private_service_not_in_published_files(self):
        for script in (ROOT / "scripts").glob("[0-9][0-9]_*.py"):
            text = script.read_text(encoding="utf-8")
            with self.subTest(script=script.name):
                self.assertNotIn("Users\\Amir", text)
                self.assertNotIn("D:\\Polimi", text)
                self.assertNotIn("services7.arcgis.com", text)
                self.assertIn("GPEM_MAIN_GDB", text)
                self.assertIn("GPEM_CLEAR_OUTPUT", text)


if __name__ == "__main__":
    unittest.main()