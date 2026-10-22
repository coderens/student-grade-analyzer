import csv
import io
import os
import secrets
import hmac
from datetime import datetime

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
app.secret_key = os.getenv("SECRET_KEY", "change-this-development-secret-before-deployment")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


@app.before_request
def protect_post_requests():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    if request.method == "POST":
        submitted = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not submitted or not expected or not hmac.compare_digest(submitted, expected):
            abort(400, description="Invalid or missing security token. Refresh the page and try again.")


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": session.get("csrf_token", "")}


SUBJECTS = ["Programming", "Database", "Mathematics", "Networking", "Web Development"]


def db_connection():
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/student_grades")
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
    password = getpass.getpass("Admin password (minimum 10 characters): ")
    if not username or len(password) < 10:
        raise SystemExit("Username is required and password must be at least 10 characters.")
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
        with db_connection() as conn:
            admin = conn.execute("SELECT * FROM admins WHERE username = %s", (username,)).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            session.clear()
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            return redirect(request.args.get("next") or url_for("dashboard"))
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
    for field, label in [("student_number", "Student number"), ("first_name", "First name"), ("last_name", "Last name")]:
        value = form.get(field, "").strip()
        if not value:
            errors.append(f"{label} is required.")
        data[field] = value
    data["email"] = form.get("email", "").strip() or None
    if data["email"] and ("@" not in data["email"] or "." not in data["email"].split("@")[-1]):
        errors.append("Enter a valid email address or leave it blank.")
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
        writer.writerow([s["student_number"], s["first_name"], s["last_name"], s["email"] or "", s["attendance"],
                         *[s[sub.lower().replace(" ", "_")] for sub in SUBJECTS], s["average"], s["letter_grade"],
                         s["status"], s["performance"], s["scholarship"], s["warning"]])
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
    return render_template("error.html", code=500, message="An unexpected error occurred. Check the terminal for details."), 500


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "true").lower() == "true")
