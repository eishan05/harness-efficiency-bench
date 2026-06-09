import unittest

from config_migrator import migrate_config


class ConfigMigratorTest(unittest.TestCase):
    def test_migrates_legacy_fields_and_preserves_unknown_keys(self):
        legacy = {
            "version": 1,
            "timeout_ms": 2500,
            "max_retries": 4,
            "enable_cache": True,
            "owner": "platform",
        }

        migrated = migrate_config(legacy)

        self.assertEqual(migrated["version"], 2)
        self.assertEqual(migrated["timeout_seconds"], 3)
        self.assertEqual(migrated["retry_policy"], {"attempts": 4})
        self.assertEqual(migrated["features"], {"cache": True})
        self.assertEqual(migrated["owner"], "platform")

    def test_removes_legacy_keys_from_result(self):
        migrated = migrate_config({"timeout_ms": 1000, "max_retries": 2, "enable_cache": False})

        self.assertNotIn("timeout_ms", migrated)
        self.assertNotIn("max_retries", migrated)
        self.assertNotIn("enable_cache", migrated)

    def test_does_not_mutate_input(self):
        legacy = {"timeout_ms": 1500, "owner": "search"}
        original = dict(legacy)

        migrate_config(legacy)

        self.assertEqual(legacy, original)


if __name__ == "__main__":
    unittest.main()
