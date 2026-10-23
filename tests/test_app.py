import unittest

from app import app, get_letter_grade, get_status, validate_student_form, validate_student_profile_form, percentage_to_grade_point, validate_grade, is_safe_redirect_target


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
        self.assertIn("owner_admin_id BIGINT REFERENCES admins(id) ON DELETE SET NULL", schema)
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS students_owner_number_idx", schema)
        self.assertIn("owner_admin_id IS NULL", schema)

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


    def test_forgot_password_page_requests_registered_contact(self):
        response = app.test_client().get("/forgot-password")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="contact"', response.data)
        self.assertIn(b"Your Gmail address", response.data)
        self.assertIn(b"STEP 1 OF 3", response.data)

    def test_password_recovery_pages_enforce_three_step_user_flow(self):
        with open("templates/verify_reset_code.html", encoding="utf-8") as template_file:
            verify_template = template_file.read()
        with open("templates/reset_password.html", encoding="utf-8") as template_file:
            reset_template = template_file.read()
        self.assertIn("STEP 2 OF 3", verify_template)
        self.assertIn('autocomplete="one-time-code"', verify_template)
        self.assertIn("STEP 3 OF 3", reset_template)
        self.assertIn("Your email is verified", reset_template)

    def test_student_auth_routes_are_separate_and_protected(self):
        client = app.test_client()
        self.assertEqual(client.get("/student/portal").status_code, 302)
        self.assertEqual(client.get("/admin/student-accounts").status_code, 302)
        self.assertEqual(client.get("/student/login").status_code, 200)
        self.assertEqual(client.get("/student/register").status_code, 200)

    def test_student_accounts_schema_requires_approval(self):
        with open("schema.sql", encoding="utf-8") as schema_file:
            schema = schema_file.read()
        self.assertIn("CREATE TABLE IF NOT EXISTS student_accounts", schema)
        self.assertIn("DEFAULT 'pending'", schema)
        self.assertIn("CHECK (status IN ('pending', 'approved'))", schema)


    def test_subject_based_grade_conversion(self):
        self.assertEqual(percentage_to_grade_point(97), 1.00)
        self.assertEqual(percentage_to_grade_point(88), 1.75)
        self.assertEqual(percentage_to_grade_point(75), 3.00)
        self.assertEqual(percentage_to_grade_point(74.99), 5.00)

    def test_grade_input_rejects_non_finite_and_out_of_range_values(self):
        self.assertIsNone(validate_grade("nan"))
        self.assertIsNone(validate_grade("inf"))
        self.assertIsNone(validate_grade("101"))
        self.assertEqual(validate_grade("88.5"), 88.5)

    def test_student_profile_does_not_require_fixed_subject_grades(self):
        profile = {
            "student_number": "STU-002", "first_name": "Jamie", "last_name": "Reyes",
            "email": "jamie@example.com", "attendance": "95"
        }
        data, errors = validate_student_profile_form(profile)
        self.assertEqual(errors, [])
        self.assertEqual(data["student_number"], "STU-002")

    def test_subject_and_grade_history_schema_exists(self):
        with open("schema.sql", encoding="utf-8") as schema_file:
            schema = schema_file.read()
        self.assertIn("CREATE TABLE IF NOT EXISTS subjects", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS student_subjects", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS grade_records", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS grade_record_history", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS grading_policies", schema)

    def test_grade_import_and_export_routes_require_admin_login(self):
        client = app.test_client()
        self.assertEqual(client.get("/admin/grade-import").status_code, 302)
        self.assertEqual(client.get("/export/grade-report.xlsx").status_code, 302)
        self.assertEqual(client.get("/admin/grade-import-template.csv").status_code, 302)


    def test_new_subject_templates_compile(self):
        for template_name in (
            "base.html", "dashboard.html", "student_form.html", "students.html",
            "student_detail.html", "student_portal.html", "subjects.html",
            "subject_detail.html", "enrollment_grades.html", "grade_import.html"
        ):
            with self.subTest(template=template_name):
                app.jinja_env.get_template(template_name)

    def test_brand_name_is_updated_in_base_template(self):
        template = app.jinja_env.get_template("base.html")
        self.assertIsNotNone(template)
        with open("templates/base.html", encoding="utf-8") as template_file:
            source = template_file.read()
        self.assertIn("passASADO or FAILet", source)
        self.assertNotIn("GradePilot", source)

if __name__ == "__main__":
    unittest.main()
