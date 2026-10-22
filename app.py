import csv
import io
import os
import secrets
import hmac
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for, Response, abort, g
from werkzeug.security import check_password_hash, generate_password_hash
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

load_dotenv()
app = Flask(__name__)
_secret_key = os.getenv("SECRET_KEY")
_is_production = (
    os.getenv("RENDER", "").lower() == "true"
    or bool(os.getenv("RENDER_SERVICE_ID"))
    or os.getenv("FLASK_ENV") == "production"
)
if not _secret_key and _is_production:
    raise RuntimeError("SECRET_KEY must be set in the production environment.")
app.secret_key = _secret_key or secrets.token_hex(32)
_database_url = os.getenv("DATABASE_URL")
if not _database_url and _is_production:
    raise RuntimeError("DATABASE_URL must be set in the production environment.")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=_is_production or os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    SESSION_REFRESH_EACH_REQUEST=True,
    MAX_CONTENT_LENGTH=1024 * 1024,
)


@app.before_request
def protect_post_requests():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    if request.method == "POST":
        submitted = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not submitted or not expected or not hmac.compare_digest(submitted, expected):
            abort(400, description="Invalid or missing security token. Refresh the page and try again.")


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


def safe_next_url(target):
    """Accept only a local absolute path; reject external and scheme-relative redirects."""
    if not target or "\\" in target:
        return None
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return None
    return target


def safe_csv_cell(value):
    """Prevent spreadsheet formula execution from untrusted text fields in CSV exports."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def _auth_identifier_hash(identifier):
    normalized = (identifier or "").strip().casefold()
    return hmac.new(app.secret_key.encode("utf-8"), normalized.encode("utf-8"), "sha256").hexdigest()


def login_is_throttled(identifier):
    key = _auth_identifier_hash(identifier)
    with db_connection() as conn:
        row = conn.execute(
            """SELECT 1 FROM auth_login_attempts
               WHERE identifier_hash = %s
                 AND (locked_until > CURRENT_TIMESTAMP OR
                      (attempt_count >= 8 AND first_attempt_at > CURRENT_TIMESTAMP - INTERVAL '15 minutes'))
               LIMIT 1""",
            (key,),
        ).fetchone()
    return row is not None


def record_login_failure(identifier):
    key = _auth_identifier_hash(identifier)
    with db_connection() as conn:
        conn.execute(
            """INSERT INTO auth_login_attempts (identifier_hash, attempt_count, first_attempt_at, locked_until)
               VALUES (%s, 1, CURRENT_TIMESTAMP, NULL)
               ON CONFLICT (identifier_hash) DO UPDATE SET
                 attempt_count = CASE
                   WHEN auth_login_attempts.first_attempt_at < CURRENT_TIMESTAMP - INTERVAL '15 minutes' THEN 1
                   ELSE auth_login_attempts.attempt_count + 1 END,
                 first_attempt_at = CASE
                   WHEN auth_login_attempts.first_attempt_at < CURRENT_TIMESTAMP - INTERVAL '15 minutes' THEN CURRENT_TIMESTAMP
                   ELSE auth_login_attempts.first_attempt_at END,
                 locked_until = CASE
                   WHEN (CASE
                     WHEN auth_login_attempts.first_attempt_at < CURRENT_TIMESTAMP - INTERVAL '15 minutes' THEN 1
                     ELSE auth_login_attempts.attempt_count + 1 END) >= 8
                   THEN CURRENT_TIMESTAMP + INTERVAL '15 minutes'
                   ELSE NULL END""",
            (key,),
        )
        # Periodically discard old pseudonymous throttling records.
        conn.execute("DELETE FROM auth_login_attempts WHERE first_attempt_at < CURRENT_TIMESTAMP - INTERVAL '1 day'")


def clear_login_failures(identifier):
    key = _auth_identifier_hash(identifier)
    with db_connection() as conn:
        conn.execute("DELETE FROM auth_login_attempts WHERE identifier_hash = %s", (key,))


def password_validation_error(password):
    if len(password) < 12:
        return "Password must be at least 12 characters long."
    if len(password) > 128:
        return "Password must be no longer than 128 characters."
    if not password.strip():
        return "Password cannot contain only spaces."
    return None


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": session.get("csrf_token", "")}


SUBJECTS = ["Programming", "Database", "Mathematics", "Networking", "Web Development"]


def db_connection():
    dsn = _database_url or "postgresql://postgres:postgres@localhost:5432/student_grades"
    return psycopg.connect(dsn, row_factory=dict_row)


def get_letter_grade(average):
    if average >= 90:
        return "A"
    elif average >= 80:
        return "B"
    elif average >= 70:
        return "C"
    elif average >= 60:
        return "D"
    return "F"


def get_status(average, attendance):
    return "PASSED" if average >= 75 and attendance >= 80 else "FAILED"


def get_performance(average):
    if average >= 95:
        return "Outstanding"
    elif average >= 90:
        return "Excellent"
    elif average >= 85:
        return "Very Good"
    elif average >= 80:
        return "Good"
    elif average >= 75:
        return "Satisfactory"
    elif average >= 60:
        return "Needs Improvement"
    return "Poor"


def get_scholarship(average, attendance):
    return "Qualified" if average >= 90 and attendance >= 90 else "Not Qualified"


def get_warning(average, attendance):
    if average < 75 and attendance < 80:
        return "Low grades and low attendance"
    elif average < 75:
        return "Low grades"
    elif attendance < 80:
        return "Low attendance"
    return "No warning"


def get_subject_remark(grade):
    if grade >= 90:
        return "Excellent"
    elif grade >= 75:
        return "Passed"
    return "Needs Improvement"


def enrich_student(student):
    student = dict(student)
    grades = [float(student[s.lower().replace(' ', '_')]) for s in SUBJECTS]
    average = round(sum(grades) / len(grades), 2)
    attendance = float(student["attendance"])
    student["average"] = average
    student["letter_grade"] = get_letter_grade(average)
    student["status"] = get_status(average, attendance)
    student["performance"] = get_performance(average)
    student["scholarship"] = get_scholarship(average, attendance)
    student["warning"] = get_warning(average, attendance)
    student["subject_remarks"] = {s: get_subject_remark(grades[i]) for i, s in enumerate(SUBJECTS)}
    return student


def fetch_students(search=""):
    with db_connection() as conn:
        if search:
            pattern = f"%{search}%"
            rows = conn.execute("""SELECT * FROM students
                WHERE student_number ILIKE %s OR first_name ILIKE %s OR last_name ILIKE %s OR email ILIKE %s
                ORDER BY last_name, first_name""", (pattern, pattern, pattern, pattern)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM students ORDER BY last_name, first_name").fetchall()
    return [enrich_student(r) for r in rows]


def login_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def init_db():
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, encoding="utf-8") as file:
        schema = file.read()
    with db_connection() as conn:
        conn.execute(schema)


@app.cli.command("init-db")
def init_db_command():
    """Create the database tables. Create the PostgreSQL database first."""
    init_db()
    print("Database tables created successfully.")


@app.cli.command("create-admin")
def create_admin_command():
    """Interactively create an administrator account."""
    import getpass
    username = input("Admin username: ").strip()
    password = getpass.getpass("Admin password (minimum 12 characters): ")
    if not username or password_validation_error(password):
        raise SystemExit("Username is required and password must be 12-128 characters and not blank.")
    init_db()
    with db_connection() as conn:
        exists = conn.execute("SELECT id FROM admins WHERE username = %s", (username,)).fetchone()
        if exists:
            raise SystemExit("That username already exists.")
        conn.execute("INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
                     (username, generate_password_hash(password)))
    print("Administrator created successfully.")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if login_is_throttled(username):
            flash("Unable to sign in right now. Please wait 15 minutes and try again.", "error")
            return render_template("login.html"), 429
        with db_connection() as conn:
            admin = conn.execute("SELECT * FROM admins WHERE username = %s", (username,)).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            clear_login_failures(username)
            session.clear()
            session.permanent = True
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            destination = safe_next_url(request.args.get("next"))
            return redirect(destination or url_for("dashboard"))
        record_login_failure(username)
        flash("Invalid username or password. If you don’t have an account, please contact the IT Department to request administrator access.", "error")
    return render_template("login.html")


@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    students = fetch_students()
    total = len(students)
    passed = sum(s["status"] == "PASSED" for s in students)
    failed = total - passed
    excellent = sum(s["average"] >= 90 for s in students)
    class_average = round(sum(s["average"] for s in students) / total, 2) if total else 0
    highest = max(students, key=lambda s: s["average"], default=None)
    lowest = min(students, key=lambda s: s["average"], default=None)
    stats = {
        "total": total, "passed": passed, "failed": failed,
        "pass_rate": round(passed / total * 100, 1) if total else 0,
        "fail_rate": round(failed / total * 100, 1) if total else 0,
        "excellent": excellent, "class_average": class_average,
        "highest": highest, "lowest": lowest,
        "overall_performance": get_performance(class_average) if total else "No data"
    }
    subject_averages = []
    for subject in SUBJECTS:
        key = subject.lower().replace(" ", "_")
        subject_averages.append(round(sum(float(s[key]) for s in students) / total, 2) if total else 0)
    return render_template("dashboard.html", stats=stats, students=students[:8], subjects=SUBJECTS,
                           subject_averages=subject_averages)


def validate_student_form(form):
    data = {}
    errors = []
    for field, label, maximum in [("student_number", "Student number", 40), ("first_name", "First name", 100), ("last_name", "Last name", 100)]:
        value = form.get(field, "").strip()
        if not value:
            errors.append(f"{label} is required.")
        elif len(value) > maximum:
            errors.append(f"{label} must be {maximum} characters or fewer.")
        data[field] = value
    data["email"] = form.get("email", "").strip().lower() or None
    if data["email"] and (len(data["email"]) > 255 or "@" not in data["email"] or "." not in data["email"].split("@")[-1]):
        errors.append("Enter a valid email address (maximum 255 characters) or leave it blank.")
    try:
        data["attendance"] = float(form.get("attendance", ""))
        if not 0 <= data["attendance"] <= 100:
            errors.append("Attendance must be between 0 and 100.")
    except ValueError:
        data["attendance"] = 0
        errors.append("Attendance must be a number.")
    for subject in SUBJECTS:
        key = subject.lower().replace(" ", "_")
        try:
            data[key] = float(form.get(key, ""))
            if not 0 <= data[key] <= 100:
                errors.append(f"{subject} grade must be between 0 and 100.")
        except ValueError:
            data[key] = 0
            errors.append(f"{subject} grade must be a number.")
    return data, errors


@app.route("/students")
@login_required
def students_page():
    return render_template("students.html", students=fetch_students(request.args.get("q", "")),
                           subjects=SUBJECTS, search=request.args.get("q", ""))


@app.route("/students/add", methods=["GET", "POST"])
@login_required
def add_student():
    if request.method == "POST":
        data, errors = validate_student_form(request.form)
        if errors:
            for error in errors: flash(error, "error")
            return render_template("student_form.html", student=data, subjects=SUBJECTS, page_title="Add student")
        try:
            with db_connection() as conn:
                conn.execute("""INSERT INTO students (student_number, first_name, last_name, email, attendance,
                    programming, database, mathematics, networking, web_development)
                    VALUES (%(student_number)s, %(first_name)s, %(last_name)s, %(email)s, %(attendance)s,
                    %(programming)s, %(database)s, %(mathematics)s, %(networking)s, %(web_development)s)""", data)
            flash("Student added successfully.", "success")
            return redirect(url_for("students_page"))
        except psycopg.errors.UniqueViolation:
            flash("Student number already exists. Use a unique student number.", "error")
        except psycopg.errors.ForeignKeyViolation:
            flash("Could not save student. Please check the submitted information.", "error")
        return render_template("student_form.html", student=data, subjects=SUBJECTS, page_title="Add student")
    return render_template("student_form.html", student={}, subjects=SUBJECTS, page_title="Add student")


@app.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
@login_required
def edit_student(student_id):
    with db_connection() as conn:
        existing = conn.execute("SELECT * FROM students WHERE id = %s", (student_id,)).fetchone()
    if not existing: abort(404)
    if request.method == "POST":
        data, errors = validate_student_form(request.form)
        if errors:
            for error in errors: flash(error, "error")
            data["id"] = student_id
            return render_template("student_form.html", student=data, subjects=SUBJECTS, page_title="Edit student")
        try:
            with db_connection() as conn:
                conn.execute("""UPDATE students SET student_number=%(student_number)s, first_name=%(first_name)s,
                    last_name=%(last_name)s, email=%(email)s, attendance=%(attendance)s, programming=%(programming)s,
                    database=%(database)s, mathematics=%(mathematics)s, networking=%(networking)s,
                    web_development=%(web_development)s, updated_at=CURRENT_TIMESTAMP WHERE id=%(id)s""",
                    {**data, "id": student_id})
            flash("Student updated successfully.", "success")
            return redirect(url_for("students_page"))
        except psycopg.errors.UniqueViolation:
            flash("Student number already exists. Use a unique student number.", "error")
            data["id"] = student_id
            return render_template("student_form.html", student=data, subjects=SUBJECTS, page_title="Edit student")
    return render_template("student_form.html", student=existing, subjects=SUBJECTS, page_title="Edit student")


@app.post("/students/<int:student_id>/delete")
@login_required
def delete_student(student_id):
    with db_connection() as conn:
        result = conn.execute("DELETE FROM students WHERE id = %s", (student_id,))
    flash("Student deleted." if result.rowcount else "Student record not found.", "success" if result.rowcount else "error")
    return redirect(url_for("students_page"))


@app.route("/students/<int:student_id>")
@login_required
def student_detail(student_id):
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM students WHERE id = %s", (student_id,)).fetchone()
    if not row: abort(404)
    return render_template("student_detail.html", student=enrich_student(row), subjects=SUBJECTS)


@app.get("/export/students.csv")
@login_required
def export_csv():
    students = fetch_students()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student Number", "First Name", "Last Name", "Email", "Attendance", *SUBJECTS,
                     "Average", "Letter Grade", "Academic Status", "Performance", "Scholarship", "Warning"])
    for s in students:
        row = [s["student_number"], s["first_name"], s["last_name"], s["email"] or "", s["attendance"],
               *[s[sub.lower().replace(" ", "_")] for sub in SUBJECTS], s["average"], s["letter_grade"],
               s["status"], s["performance"], s["scholarship"], s["warning"]]
        writer.writerow([safe_csv_cell(value) for value in row])
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=student_grade_report.csv"})


@app.get("/export/students.pdf")
@login_required
def export_pdf():
    students = fetch_students()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=24, leftMargin=24, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    elements = [Paragraph("Student Grade Management and Performance Analyzer", styles["Title"]),
                Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Normal"]), Spacer(1, 12)]
    data = [["Student No.", "Student Name", "Average", "Letter", "Status", "Performance", "Attendance", "Scholarship"]]
    for s in students:
        data.append([s["student_number"], f'{s["first_name"]} {s["last_name"]}', f'{s["average"]:.2f}',
                     s["letter_grade"], s["status"], s["performance"], f'{s["attendance"]:.1f}%', s["scholarship"]])
    table = Table(data, repeatRows=1, colWidths=[75, 125, 55, 45, 55, 95, 65, 80])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3b63")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d8dee8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fa")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6)
    ]))
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return Response(buffer.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=student_grade_report.pdf"})


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="The requested page or student record was not found."), 404


@app.errorhandler(500)
def server_error(_error):
    return render_template("error.html", code=500, message="An unexpected error occurred. Please try again or contact the system administrator."), 500



def student_login_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        account_id = session.get("student_account_id")
        student_id = session.get("student_id")
        if not account_id or not student_id:
            return redirect(url_for("student_login", next=request.path))
        # Re-check status so an administrator can revoke access immediately.
        with db_connection() as conn:
            account = conn.execute(
                "SELECT id FROM student_accounts WHERE id = %s AND student_id = %s AND is_active = TRUE",
                (account_id, student_id),
            ).fetchone()
        if not account:
            session.clear()
            flash("Your session is no longer active. Please sign in again.", "error")
            return redirect(url_for("student_login"))
        return view(*args, **kwargs)
    return wrapped


PRIVACY_NOTICE_VERSION = "1.0"


@app.get("/privacy")
def privacy_notice():
    return render_template("privacy.html", privacy_notice_version=PRIVACY_NOTICE_VERSION)


@app.route("/student/login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if login_is_throttled(email):
            flash("Unable to sign in right now. Please wait 15 minutes and try again.", "error")
            return render_template("student_login.html"), 429
        with db_connection() as conn:
            account = conn.execute(
                "SELECT sa.id, sa.password_hash, sa.is_active, s.id AS student_id, s.first_name, s.last_name "
                "FROM student_accounts sa JOIN students s ON s.id = sa.student_id WHERE LOWER(sa.email) = %s",
                (email,)
            ).fetchone()
        if account and check_password_hash(account["password_hash"], password) and account["is_active"]:
            clear_login_failures(email)
            session.clear()
            session.permanent = True
            session["student_account_id"] = account["id"]
            session["student_id"] = account["student_id"]
            session["student_name"] = account["first_name"] + " " + account["last_name"]
            destination = safe_next_url(request.args.get("next"))
            return redirect(destination or url_for("student_portal"))
        record_login_failure(email)
        flash("Unable to sign in. Check your credentials or contact the school administrator if your account is awaiting approval.", "error")
    return render_template("student_login.html")


@app.route("/student/register", methods=["GET", "POST"])
def student_register():
    if request.method == "POST":
        student_number = request.form.get("student_number", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not student_number or not email:
            flash("Please complete every field.", "error")
        elif password_validation_error(password):
            flash(password_validation_error(password), "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        elif request.form.get("privacy_ack") != "on":
            flash("Please read and acknowledge the privacy notice before registering.", "error")
        else:
            try:
                with db_connection() as conn:
                    student = conn.execute(
                        "SELECT id FROM students WHERE student_number = %s AND LOWER(email) = %s",
                        (student_number, email)
                    ).fetchone()
                    if not student:
                        flash("We could not submit a registration request with those details. Check them or contact the school administrator.", "error")
                    else:
                        existing = conn.execute(
                            "SELECT id FROM student_accounts WHERE student_id = %s OR LOWER(email) = %s",
                            (student["id"], email)
                        ).fetchone()
                        if existing:
                            flash("We could not submit a registration request with those details. Check them or contact the school administrator.", "error")
                        else:
                            conn.execute(
                                "INSERT INTO student_accounts (student_id, email, password_hash, is_active, privacy_notice_version, privacy_notice_acknowledged_at) "
                                "VALUES (%s, %s, %s, FALSE, %s, CURRENT_TIMESTAMP)",
                                (student["id"], email, generate_password_hash(password), PRIVACY_NOTICE_VERSION)
                            )
                            flash("Your registration request has been submitted. A school administrator must approve access before you can view student records.", "success")
                            return redirect(url_for("student_login"))
            except psycopg.errors.UniqueViolation:
                flash("An account already exists for this student or email. Please sign in.", "error")
    return render_template("student_register.html")


@app.route("/admin/accounts/create", methods=["GET", "POST"])
@login_required
def create_admin_account():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not username:
            flash("Username is required.", "error")
        elif len(username) > 80:
            flash("Username must be 80 characters or fewer.", "error")
        elif password_validation_error(password):
            flash(password_validation_error(password), "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        else:
            try:
                with db_connection() as conn:
                    conn.execute("INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
                                 (username, generate_password_hash(password)))
                flash("Administrator account created successfully.", "success")
                return redirect(url_for("dashboard"))
            except psycopg.errors.UniqueViolation:
                flash("That administrator username already exists.", "error")
    return render_template("admin_register.html")


@app.route("/admin/student-accounts")
@login_required
def manage_student_accounts():
    with db_connection() as conn:
        pending_accounts = conn.execute(
            """SELECT sa.id, sa.email, sa.created_at, s.student_number, s.first_name, s.last_name
               FROM student_accounts sa JOIN students s ON s.id = sa.student_id
               WHERE sa.is_active = FALSE ORDER BY sa.created_at"""
        ).fetchall()
        active_accounts = conn.execute(
            """SELECT sa.id, sa.email, sa.created_at, s.student_number, s.first_name, s.last_name
               FROM student_accounts sa JOIN students s ON s.id = sa.student_id
               WHERE sa.is_active = TRUE ORDER BY s.last_name, s.first_name"""
        ).fetchall()
    return render_template("admin_student_accounts.html", pending_accounts=pending_accounts,
                           active_accounts=active_accounts)


@app.post("/admin/student-accounts/<int:account_id>/approve")
@login_required
def approve_student_account(account_id):
    with db_connection() as conn:
        result = conn.execute(
            "UPDATE student_accounts SET is_active = TRUE WHERE id = %s AND is_active = FALSE",
            (account_id,)
        )
    flash("Student account approved." if result.rowcount else "Pending account not found.",
          "success" if result.rowcount else "error")
    return redirect(url_for("manage_student_accounts"))


@app.post("/admin/student-accounts/<int:account_id>/disable")
@login_required
def disable_student_account(account_id):
    with db_connection() as conn:
        result = conn.execute(
            "UPDATE student_accounts SET is_active = FALSE WHERE id = %s AND is_active = TRUE",
            (account_id,)
        )
    flash("Student account access disabled." if result.rowcount else "Active account not found.",
          "success" if result.rowcount else "error")
    return redirect(url_for("manage_student_accounts"))


@app.route("/student/portal")
@student_login_required
def student_portal():
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM students WHERE id = %s", (session["student_id"],)).fetchone()
    if not row:
        session.clear()
        flash("Your student record could not be found. Contact the school administrator.", "error")
        return redirect(url_for("student_login"))
    return render_template("student_portal.html", student=enrich_student(row), subjects=SUBJECTS)


@app.post("/student/logout")
@student_login_required
def student_logout():
    session.clear()
    return redirect(url_for("student_login"))

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
