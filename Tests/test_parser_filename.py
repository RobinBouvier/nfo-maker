import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "NFO-MAKER"))

from nfo_gen.parser_filename import parse_filename


class TestParseFilename(unittest.TestCase):
    def test_parse_example(self):
        parsed = parse_filename(
            "Kingsman le Cercle d Or 2017 1080p FR EN X264 AC3-mHDgz.mkv"
        )
        self.assertEqual(parsed.title, "Kingsman le Cercle d Or")
        self.assertEqual(parsed.year, 2017)
        self.assertIn("FR", parsed.languages)
        self.assertIn("EN", parsed.languages)


if __name__ == "__main__":
    unittest.main()
