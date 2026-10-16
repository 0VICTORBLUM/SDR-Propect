import unittest

from core import make_message, normalize, score_business


class LogicTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize("São Paulo - Drywall"), "sao paulo drywall")

    def test_drywall_score_recognizes_keyword(self):
        score, reason = score_business("Casa do Drywall", {"website": "https://example.com"}, "drywall")
        self.assertGreaterEqual(score, 30)
        self.assertIn("drywall", reason.lower())

    def test_impermeabilization_message_is_segment_specific(self):
        message = make_message("Empresa Alfa", "Impermeabilização", "Campinas")
        self.assertIn("impermeabilização", message.lower())
        self.assertIn("Empresa Alfa", message)


if __name__ == "__main__":
    unittest.main()
