import unittest

from app import app, get_letter_grade, get_status, validate_student_form, is_safe_redirect_target


class GradePilotValidationTests(unittest.TestCase):
    def valid_form(self):
        return {
            "student_number": "STU-001",
            "first_name": "Alex",
            "last_name": "Santos",
            "email": "alex@example.com",
            "attendance": "90",
            "programming": "90",
            "database": "80",
            "mathematics": "85",
            "networking": "88",
            "web_development": "92",
        }

    def test_grade_boundaries(self):
        self.assertEqual(get_letter_grade(90), "A")
        self.assertEqual(get_letter_grade(80), "B")
        self.assertEqual(get_letter_grade(70), "C")
        self.assertEqual(get_letter_grade(60), "D")
        self.assertEqual(get_letter_grade(59.99), "F")

    def test_pass_requires_grade_and_attendance(self):
        self.assertEqual(get_status(75, 80), "PASSED")
        self.assertEqual(get_status(90, 79.99), "FAILED")
        self.assertEqual(get_status(74.99, 100), "FAILED")

    def test_rejects_nan_grade(self):
        form = self.valid_form()
        form["programming"] = "nan"
        _, errors = validate_student_form(form)
        self.assertTrue(any("Programming grade" in error for error in errors))

    def test_rejects_infinite_attendance(self):
        form = self.valid_form()
        form["attendance"] = "inf"
        _, errors = validate_student_form(form)
        self.assertTrue(any("Attendance" in error for error in errors))

    def test_rejects_out_of_range_grade(self):
        form = self.valid_form()
        form["database"] = "101"
        _, errors = validate_student_form(form)
        self.assertTrue(any("Database grade" in error for error in errors))

    def test_rejects_external_login_redirect(self):
        with app.test_request_context("/", base_url="https://gradepilot.example/"):
            self.assertFalse(is_safe_redirect_target("https://evil.example/"))
            self.assertFalse(is_safe_redirect_target("//evil.example/"))
            self.assertTrue(is_safe_redirect_target("/students"))

    def test_rejects_overlong_student_number(self):
        form = self.valid_form()
        form["student_number"] = "S" * 41
        _, errors = validate_student_form(form)
        self.assertTrue(any("Student number" in error for error in errors))


    def test_tracker_id_migration_is_unique_and_non_null(self):
        with open("schema.sql", encoding="utf-8") as schema_file:
            schema = schema_file.read()
        self.assertIn("tracker_id UUID", schema)
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS admins_tracker_id_idx", schema)

    def test_personal_activity_route_requires_login(self):
        response = app.test_client().get("/my-activity")
        self.assertEqual(response.status_code, 302)

    def test_excel_sign_in_report_requires_login(self):
        response = app.test_client().get("/admin/sign-in-report.xlsx")
        self.assertEqual(response.status_code, 302)

    def test_sign_in_report_schema_has_account_type_and_tracker(self):
        with open("schema.sql", encoding="utf-8") as schema_file:
            schema = schema_file.read()
        self.assertIn("CREATE TABLE IF NOT EXISTS sign_in_logs", schema)
        self.assertIn("account_type VARCHAR(10)", schema)
        self.assertIn("tracker_id UUID NOT NULL", schema)


    def test_tracker_id_migration_is_unique_and_non_null(self):
        with open("schema.sql", encoding="utf-8") as schema_file:
            schema = schema_file.read()
        self.assertIn("tracker_id UUID", schema)
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS admins_tracker_id_idx", schema)

    def test_personal_activity_route_requires_login(self):
        response = app.test_client().get("/my-activity")
        self.assertEqual(response.status_code, 302)


if __name__ == "__main__":
    unittest.main()
