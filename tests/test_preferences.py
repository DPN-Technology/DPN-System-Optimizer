"""Appearance persistence and validation regression tests."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dpn_optimizer.preferences import (
    AppearancePreferences, load_preferences, save_preferences,
)


class AppearancePreferenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "settings" / "appearance.json"

    def test_missing_preferences_use_defaults(self):
        self.assertEqual(load_preferences(self.path), AppearancePreferences())

    def test_round_trip_preserves_all_choices(self):
        expected = AppearancePreferences(False, True, False, "Low")
        save_preferences(expected, self.path)
        self.assertEqual(load_preferences(self.path), expected)

    def test_invalid_data_is_reported(self):
        self.path.parent.mkdir()
        for content in ('{', '[]', '{"binary_rain": "false"}',
                        '{"intensity": "Unlimited"}'):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_preferences(self.path)

    def test_unknown_fields_allow_future_compatibility(self):
        self.path.parent.mkdir()
        self.path.write_text('{"future": 42, "intensity": "High"}', encoding="utf-8")
        self.assertEqual(load_preferences(self.path).intensity, "High")

    def test_failed_replace_preserves_old_settings_and_cleans_temporary_file(self):
        save_preferences(AppearancePreferences(), self.path)
        with patch("dpn_optimizer.preferences.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                save_preferences(AppearancePreferences(reduced_motion=True), self.path)
        self.assertEqual(load_preferences(self.path), AppearancePreferences())
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
