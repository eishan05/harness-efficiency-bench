import unittest

from registry import load_plugins


class RegistryTest(unittest.TestCase):
    def test_discovers_all_registering_modules(self):
        self.assertEqual(load_plugins("plugins"), {"alpha": "alpha-v1", "beta": "beta-v2"})

    def test_registry_is_fresh_each_time(self):
        first = load_plugins("plugins")
        first["alpha"] = "changed"

        self.assertEqual(load_plugins("plugins")["alpha"], "alpha-v1")


if __name__ == "__main__":
    unittest.main()
