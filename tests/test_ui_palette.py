"""Check the contrast of the functional colors shipped in the coordinator interface."""
from pathlib import Path
import re
import unittest


def luminance(value):
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    channels = [int(value[i:i+2], 16) / 255 for i in (0, 2, 4)]
    red, green, blue = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055)**2.4 for x in channels]
    return .2126*red + .7152*green + .0722*blue


class PaletteTest(unittest.TestCase):
    def test_text_and_control_contrast(self):
        style = (Path(__file__).resolve().parents[1] / "web/src/style.css").read_text()
        colors = dict(re.findall(r"--([a-z-]+):\s*#([a-fA-F0-9]+);", style))
        pairs = [("ink", "paper", 4.5), ("muted", "subtle", 4.5), ("action", "paper", 4.5),
                 ("action", "selected", 4.5), ("amber", "warm", 4.5), ("problem", "problem-bg", 4.5),
                 ("control", "paper", 3), ("focus", "paper", 3)]
        for foreground, background, minimum in pairs:
            with self.subTest(foreground=foreground, background=background):
                low, high = sorted(luminance(colors[c]) for c in (foreground, background))
                self.assertGreaterEqual((high + .05) / (low + .05), minimum)
