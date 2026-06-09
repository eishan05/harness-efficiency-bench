import unittest

from link_normalizer import normalize_links


class LinkNormalizerTest(unittest.TestCase):
    def test_normalizes_relative_links_only(self):
        markdown = (
            "See [guide](docs/setup.md), [site](https://example.com), "
            "[anchor](#top), and [mail](mailto:test@example.com)."
        )

        normalized = normalize_links(markdown, "https://docs.example.com/project/")

        self.assertIn("[guide](https://docs.example.com/project/docs/setup.md)", normalized)
        self.assertIn("[site](https://example.com)", normalized)
        self.assertIn("[anchor](#top)", normalized)
        self.assertIn("[mail](mailto:test@example.com)", normalized)

    def test_resolves_dot_segments(self):
        normalized = normalize_links(
            "[api](../api/./index.md)",
            "https://docs.example.com/project/guide/",
        )

        self.assertEqual(normalized, "[api](https://docs.example.com/project/api/index.md)")

    def test_leaves_fenced_code_blocks_unchanged(self):
        markdown = """Before
```md
[debug](docs/internal.md)
```
After [real](docs/real.md)
"""

        normalized = normalize_links(markdown, "https://docs.example.com/project/")

        self.assertIn("[debug](docs/internal.md)", normalized)
        self.assertIn("[real](https://docs.example.com/project/docs/real.md)", normalized)


if __name__ == "__main__":
    unittest.main()
