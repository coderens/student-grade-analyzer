import unittest

from app import password_validation_error, safe_csv_cell, safe_next_url


class SecurityHelperTests(unittest.TestCase):
    def test_external_redirects_are_rejected(self):
        self.assertIsNone(safe_next_url("https://example.com"))
        self.assertIsNone(safe_next_url("//example.com/path"))
        self.assertIsNone(safe_next_url("/\\\\example.com"))

    def test_local_redirect_is_allowed(self):
        self.assertEqual(safe_next_url("/student/portal?tab=grades"), "/student/portal?tab=grades")

    def test_csv_formula_prefixes_are_neutralized(self):
        for value in ("=1+1", "+SUM(A1:A2)", "-1+2", "@cmd", "  =1+1"):
            with self.subTest(value=value):
                self.assertTrue(safe_csv_cell(value).startswith("'"))

    def test_regular_csv_values_are_preserved(self):
        self.assertEqual(safe_csv_cell("Alex Student"), "Alex Student")
        self.assertEqual(safe_csv_cell(95.5), 95.5)

    def test_password_length_policy(self):
        self.assertIsNotNone(password_validation_error("short"))
        self.assertIsNotNone(password_validation_error(" " * 12))
        self.assertIsNone(password_validation_error("a-long-enough-passphrase"))


if __name__ == "__main__":
    unittest.main()
