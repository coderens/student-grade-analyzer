import csv
import io
import os
import secrets
import hmac
import math
from urllib.parse import urljoin, urlparse
from datetime import datetime

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for, Response, abort, g
from werkzeug.security import check_password_hash, generate_password_hash
from psycopg.types.json import Jsonb
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.worksheet.table import Table, TableStyleInfo
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

load_dotenv()
app = Flask(__name__)
_secret_key = os.getenv("SECRET_KEY")
_is_production = os.getenv("RENDER", "").lower() == "true" or os.getenv("FLASK_ENV", "").lower() == "production"
if not _secret_key and _is_production:
    raise RuntimeError("SECRET_KEY must be set in the production environment.")
app.secret_key = _secret_key or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_is_production,
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
)


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



def percentage_to_grade_point(percentage):
    """Illustrative PH-style percentage conversion; institution policy may differ."""
    if percentage >= 97: return 1.00
    if percentage >= 94: return 1.25
    if percentage >= 91: return 1.50
    if percentage >= 88: return 1.75
    if percentage >= 85: return 2.00
    if percentage >= 82: return 2.25
    if percentage >= 79: return 2.50
    if percentage >= 76: return 2.75
    if percentage >= 75: return 3.00
    return 5.00


def get_student_gwa_summary(student_id):
    """Calculate an interim or completed GWA from subject term records."""
    with db_connection() as conn:
        rows = conn.execute(
            """SELECT ss.id AS enrollment_id, ss.academic_year, ss.semester,
                      sub.id AS subject_id, sub.subject_code, sub.subject_name, sub.units,
                      gr.term, gr.percentage, gr.updated_at
               FROM student_subjects ss
               JOIN subjects sub ON sub.id = ss.subject_id
               LEFT JOIN grade_records gr ON gr.student_subject_id = ss.id
               WHERE ss.student_id = %s
               ORDER BY ss.academic_year DESC, ss.semester, sub.subject_name, gr.term""",
            (student_id,)
        ).fetchall()
        policy = conn.execute(
            "SELECT dean_list_gwa_max, max_subject_gwa FROM grading_policies WHERE id = 1"
        ).fetchone()
    by_enrollment = {}
    for row in rows:
        key = row["enrollment_id"]
        if key not in by_enrollment:
            by_enrollment[key] = {
                "enrollment_id": key, "academic_year": row["academic_year"], "semester": row["semester"],
                "subject_id": row["subject_id"], "subject_code": row["subject_code"],
                "subject_name": row["subject_name"], "units": float(row["units"]),
                "midterms": None, "finals": None, "last_updated": row["updated_at"]
            }
        if row["term"] == "Midterms":
            by_enrollment[key]["midterms"] = float(row["percentage"])
        elif row["term"] == "Finals":
            by_enrollment[key]["finals"] = float(row["percentage"])
        if row["updated_at"] and (not by_enrollment[key]["last_updated"] or row["updated_at"] > by_enrollment[key]["last_updated"]):
            by_enrollment[key]["last_updated"] = row["updated_at"]
    subjects = []
    for item in by_enrollment.values():
        available = [x for x in (item["midterms"], item["finals"]) if x is not None]
        item["subject_percentage"] = round(sum(available) / len(available), 2) if available else None
        item["grade_point"] = percentage_to_grade_point(item["subject_percentage"]) if available else None
        item["term_status"] = "Complete" if item["midterms"] is not None and item["finals"] is not None else ("In progress" if available else "No grades")
        subjects.append(item)
    graded = [item for item in subjects if item["grade_point"] is not None]
    units_total = sum(item["units"] for item in graded)
    gwa = round(sum(item["grade_point"] * item["units"] for item in graded) / units_total, 2) if units_total else None
    all_complete = bool(subjects) and len(graded) == len(subjects) and all(item["term_status"] == "Complete" for item in subjects)
    max_subject_gwa = float(policy["max_subject_gwa"]) if policy else 2.50
    dean_gwa_max = float(policy["dean_list_gwa_max"]) if policy else 1.75
    no_low_subject = bool(graded) and all(item["grade_point"] <= max_subject_gwa for item in graded)
    dean_status = "Dean's List" if all_complete and gwa is not None and gwa <= dean_gwa_max and no_low_subject else (
        "Pending final grades" if not all_complete and subjects else "Not qualified"
    )
    return {"subjects": subjects, "gwa": gwa, "graded_subjects": len(graded),
            "total_subjects": len(subjects), "units_total": units_total,
            "all_complete": all_complete, "dean_status": dean_status,
            "dean_gwa_max": dean_gwa_max, "max_subject_gwa": max_subject_gwa}


def validate_grade(value):
    try:
        grade = float(value)
    except (TypeError, ValueError):
        return None
    return grade if math.isfinite(grade) and 0 <= grade <= 100 else None


def is_safe_redirect_target(target):
    """Only allow relative redirects that stay on this site."""
    if not target:
        return False
    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))
    return redirect_url.scheme in ("http", "https") and host_url.netloc == redirect_url.netloc


def login_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        admin_id = session.get("admin_id")
        if not admin_id:
            return redirect(url_for("login", next=request.path))
        # Re-check the session version so password changes revoke existing sessions.
        with db_connection() as conn:
            current = conn.execute(
                "SELECT session_version, tracker_id FROM admins WHERE id = %s", (admin_id,)
            ).fetchone()
        if not current or current["session_version"] != session.get("session_version"):
            session.clear()
            flash("Your session has expired. Please sign in again.", "error")
            return redirect(url_for("login"))
        session["tracker_id"] = str(current["tracker_id"])
        return view(*args, **kwargs)
    return wrapped


def log_audit_event(conn, action, entity_type, entity_id=None, details=None, actor_admin_id="session"):
    """Write a minimal audit record in the same transaction as the change."""
    actor_id = session.get("admin_id") if actor_admin_id == "session" else actor_admin_id
    conn.execute(
        """INSERT INTO audit_logs (actor_admin_id, action, entity_type, entity_id, details)
           VALUES (%s, %s, %s, %s, %s)""",
        (actor_id, action, entity_type, entity_id, Jsonb(details or {}))
    )


def log_sign_in(conn, account_type, account_id, account_identifier, account_name, tracker_id):
    """Store a successful sign-in without recording passwords or session secrets."""
    conn.execute(
        """INSERT INTO sign_in_logs
           (account_type, account_id, account_identifier, account_name, tracker_id)
           VALUES (%s, %s, %s, %s, %s)""",
        (account_type, account_id, account_identifier, account_name, str(tracker_id))
    )


def style_excel_table(ws, table_name):
    """Apply a real Excel table with filterable headers and alternating rows."""
    if ws.max_row < 2:
        ws.append([None] * ws.max_column)
    # Tables require a unique, non-empty header for each column.
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3B63")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    if ws.max_row >= 2 and ws.max_column >= 1:
        ref = f"A1:{ws.cell(row=ws.max_row, column=ws.max_column).coordinate}"
        table = Table(displayName=table_name, ref=ref)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2", showFirstColumn=False,
            showLastColumn=False, showRowStripes=True, showColumnStripes=False
        )
        ws.add_table(table)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.showGridLines = False
    for column_cells in ws.columns:
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 14), 42)


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


@app.cli.command("reset-admin-password")
def reset_admin_password_command():
    """Reset an existing administrator's password securely from the terminal."""
    import getpass
    username = input("Admin username to reset: ").strip()
    password = getpass.getpass("New admin password (minimum 10 characters): ")
    confirmation = getpass.getpass("Confirm new password: ")
    if not username or len(password) < 10:
        raise SystemExit("Username is required and password must be at least 10 characters.")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")
    with db_connection() as conn:
        result = conn.execute(
            "UPDATE admins SET password_hash = %s, session_version = session_version + 1 WHERE username = %s RETURNING id",
            (generate_password_hash(password), username)
        ).fetchone()
        if not result:
            raise SystemExit("No administrator with that username was found.")
    print("Administrator password reset successfully.")



def send_recovery_code(method, destination, code):
    """Send a one-time code using environment-configured SMTP or Twilio."""
    if method == "email":
        import smtplib
        from email.message import EmailMessage

        host = os.getenv("SMTP_HOST")
        username = os.getenv("SMTP_USERNAME")
        password = os.getenv("SMTP_PASSWORD")
        sender = os.getenv("SMTP_FROM") or username
        if not all([host, username, password, sender]):
            return False
        message = EmailMessage()
        message["Subject"] = "GradePilot password recovery code"
        message["From"] = sender
        message["To"] = destination
        message.set_content(
            f"Your GradePilot password recovery code is {code}. "
            "It expires in 10 minutes. If you did not request this, ignore this email."
        )
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=15) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(message)
        return True

    import base64
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen

    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    sender = os.getenv("TWILIO_FROM_NUMBER")
    if not all([sid, token, sender]):
        return False
    payload = urlencode({
        "To": destination,
        "From": sender,
        "Body": f"Your GradePilot password recovery code is {code}. It expires in 10 minutes."
    }).encode()
    credentials = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req = Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data=payload,
        headers={"Authorization": f"Basic {credentials}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        method="POST"
    )
    with urlopen(req, timeout=15) as response:
        return 200 <= response.status < 300


@app.cli.command("set-admin-recovery-contact")
def set_admin_recovery_contact_command():
    """Set the recovery email and/or phone for an administrator."""
    username = input("Admin username: ").strip()
    email = input("Recovery email (leave blank to skip): ").strip() or None
    phone = input("Recovery phone in international format (leave blank to skip): ").strip() or None
    if not username or not (email or phone):
        raise SystemExit("Enter a username and at least one recovery contact.")
    if email and ("@" not in email or "." not in email.rsplit("@", 1)[-1]):
        raise SystemExit("Enter a valid email address.")
    if phone and not phone.startswith("+"):
        raise SystemExit("Enter the phone number in international format, e.g. +639XXXXXXXXX.")
    with db_connection() as conn:
        result = conn.execute(
            "UPDATE admins SET recovery_email = %s, recovery_phone = %s WHERE username = %s RETURNING id",
            (email, phone, username)
        ).fetchone()
        if not result:
            raise SystemExit("No administrator with that username was found.")
    print("Recovery contact saved.")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        method = request.form.get("method", "")
        if method not in ("email", "sms"):
            flash("Choose a valid recovery method.", "error")
            return render_template("forgot_password.html")
        column = "recovery_email" if method == "email" else "recovery_phone"
        destination = None
        admin = None
        with db_connection() as conn:
            admin = conn.execute(
                f"SELECT id, {column} AS destination FROM admins WHERE username = %s",
                (username,)
            ).fetchone()
            if admin:
                destination = admin["destination"]
            if destination:
                code = f"{secrets.randbelow(1000000):06d}"
                conn.execute(
                    "UPDATE password_reset_codes SET used_at = CURRENT_TIMESTAMP "
                    "WHERE admin_id = %s AND used_at IS NULL",
                    (admin["id"],)
                )
                reset_row = conn.execute(
                    """INSERT INTO password_reset_codes (admin_id, code_hash, method, expires_at)
                       VALUES (%s, %s, %s, CURRENT_TIMESTAMP + INTERVAL '10 minutes')
                       RETURNING id""",
                    (admin["id"], generate_password_hash(code), method)
                ).fetchone()
                try:
                    sent = send_recovery_code(method, destination, code)
                except Exception:
                    app.logger.exception("Password recovery delivery failed")
                    sent = False
                if not sent:
                    conn.execute("UPDATE password_reset_codes SET used_at = CURRENT_TIMESTAMP WHERE id = %s",
                                 (reset_row["id"],))
        if admin and destination and sent:
            session["password_reset_id"] = reset_row["id"]
            session["password_reset_stage"] = "verify"
            flash("If the account and recovery contact are valid, a verification code has been sent.", "success")
            return redirect(url_for("verify_password_reset"))
        # Keep the response generic to avoid revealing which usernames have recovery contacts.
        flash("If the account and recovery contact are valid, recovery instructions will be sent. If no message arrives, contact the system administrator.", "success")
    return render_template("forgot_password.html")


@app.route("/verify-reset-code", methods=["GET", "POST"])
def verify_password_reset():
    reset_id = session.get("password_reset_id")
    if not reset_id or session.get("password_reset_stage") != "verify":
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        with db_connection() as conn:
            reset_row = conn.execute(
                """SELECT id, code_hash, expires_at, attempts, verified_at, used_at
                   FROM password_reset_codes WHERE id = %s""",
                (reset_id,)
            ).fetchone()
            if not reset_row or reset_row["used_at"] or reset_row["verified_at"] or reset_row["expires_at"] <= datetime.now(reset_row["expires_at"].tzinfo) or reset_row["attempts"] >= 5:
                flash("The code is invalid or expired. Start the recovery process again.", "error")
                session.pop("password_reset_id", None)
                session.pop("password_reset_stage", None)
                return redirect(url_for("forgot_password"))
            if not check_password_hash(reset_row["code_hash"], code):
                conn.execute("UPDATE password_reset_codes SET attempts = attempts + 1 WHERE id = %s", (reset_id,))
                flash("Invalid verification code.", "error")
                return render_template("verify_reset_code.html")
            conn.execute("UPDATE password_reset_codes SET verified_at = CURRENT_TIMESTAMP WHERE id = %s", (reset_id,))
        session["password_reset_stage"] = "reset"
        return redirect(url_for("reset_password"))
    return render_template("verify_reset_code.html")


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    reset_id = session.get("password_reset_id")
    if not reset_id or session.get("password_reset_stage") != "reset":
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        password = request.form.get("password", "")
        confirmation = request.form.get("confirmation", "")
        if len(password) < 10:
            flash("Password must be at least 10 characters.", "error")
            return render_template("reset_password.html")
        if password != confirmation:
            flash("Passwords do not match.", "error")
            return render_template("reset_password.html")
        with db_connection() as conn:
            reset_row = conn.execute(
                """SELECT admin_id FROM password_reset_codes
                   WHERE id = %s AND verified_at IS NOT NULL AND used_at IS NULL
                     AND expires_at > CURRENT_TIMESTAMP""",
                (reset_id,)
            ).fetchone()
            if not reset_row:
                session.pop("password_reset_id", None)
                session.pop("password_reset_stage", None)
                flash("The recovery session expired. Start again.", "error")
                return redirect(url_for("forgot_password"))
            conn.execute(
                "UPDATE admins SET password_hash = %s, session_version = session_version + 1 WHERE id = %s",
                (generate_password_hash(password), reset_row["admin_id"])
            )
            conn.execute("UPDATE password_reset_codes SET used_at = CURRENT_TIMESTAMP WHERE id = %s", (reset_id,))
            log_audit_event(conn, "password_reset", "admin", reset_row["admin_id"],
                            {"method": "verified_recovery"}, actor_admin_id=None)
        session.pop("password_reset_id", None)
        session.pop("password_reset_stage", None)
        flash("Password changed successfully. Please sign in.", "success")
        return redirect(url_for("login"))
    return render_template("reset_password.html")


def student_login_required(view):
    """Require a separate, approved student account session."""
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        student_id = session.get("student_account_id")
        if not student_id:
            return redirect(url_for("student_login", next=request.path))
        with db_connection() as conn:
            account = conn.execute(
                """SELECT sa.student_id, sa.status, st.tracker_id
                   FROM student_accounts sa
                   JOIN students st ON st.id = sa.student_id
                   WHERE sa.id = %s""", (student_id,)
            ).fetchone()
        if not account or account["status"] != "approved" or account["student_id"] != session.get("student_record_id"):
            session.clear()
            flash("Your student session is no longer active. Please sign in again.", "error")
            return redirect(url_for("student_login"))
        session["student_tracker_id"] = str(account["tracker_id"])
        return view(*args, **kwargs)
    return wrapped


@app.route("/student/login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        student_number = request.form.get("student_number", "").strip()
        password = request.form.get("password", "")
        with db_connection() as conn:
            account = conn.execute(
                """SELECT sa.id, sa.student_id, sa.password_hash, sa.status,
                          st.student_number, st.first_name, st.last_name, st.tracker_id
                   FROM student_accounts sa
                   JOIN students st ON st.id = sa.student_id
                   WHERE st.student_number = %s""", (student_number,)
            ).fetchone()
            if account and check_password_hash(account["password_hash"], password):
                if account["status"] != "approved":
                    flash("Your account is awaiting administrator approval.", "error")
                    return render_template("student_login.html")
                session.clear()
                session["student_account_id"] = account["id"]
                session["student_record_id"] = account["student_id"]
                session["student_number"] = account["student_number"]
                session["student_name"] = f'{account["first_name"]} {account["last_name"]}'
                session["student_tracker_id"] = str(account["tracker_id"])
                log_sign_in(conn, "student", account["student_id"], account["student_number"],
                            f'{account["first_name"]} {account["last_name"]}', account["tracker_id"])
                next_url = request.args.get("next", "")
                return redirect(next_url if is_safe_redirect_target(next_url) else url_for("student_portal"))
        flash("Invalid student number or password.", "error")
    return render_template("student_login.html")


@app.route("/student/register", methods=["GET", "POST"])
def student_register():
    if request.method == "POST":
        student_number = request.form.get("student_number", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if len(password) < 10:
            flash("Password must be at least 10 characters.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        else:
            with db_connection() as conn:
                student = conn.execute(
                    """SELECT id, student_number, email FROM students
                       WHERE student_number = %s AND LOWER(COALESCE(email, '')) = %s""",
                    (student_number, email)
                ).fetchone()
                if not student or not email:
                    flash("We couldn't match those details to a student record. Contact your administrator.", "error")
                else:
                    existing = conn.execute(
                        "SELECT id FROM student_accounts WHERE student_id = %s", (student["id"],)
                    ).fetchone()
                    if existing:
                        flash("A student account request already exists. Contact your administrator.", "error")
                    else:
                        conn.execute(
                            """INSERT INTO student_accounts (student_id, password_hash, status)
                               VALUES (%s, %s, 'pending')""",
                            (student["id"], generate_password_hash(password))
                        )
                        flash("Registration submitted. An administrator must approve your account before sign-in.", "success")
                        return redirect(url_for("student_login"))
    return render_template("student_register.html")


@app.get("/student/portal")
@student_login_required
def student_portal():
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM students WHERE id = %s", (session["student_record_id"],)).fetchone()
    if not row:
        session.clear()
        return redirect(url_for("student_login"))
    return render_template("student_portal.html", student=enrich_student(row), subjects=SUBJECTS)


@app.post("/student/logout")
@student_login_required
def student_logout():
    session.clear()
    return redirect(url_for("student_login"))


@app.get("/admin/student-accounts")
@login_required
def student_accounts_admin():
    with db_connection() as conn:
        accounts = conn.execute(
            """SELECT sa.id AS account_id, sa.status, sa.created_at,
                      st.student_number, st.first_name, st.last_name, st.email
               FROM student_accounts sa JOIN students st ON st.id = sa.student_id
               ORDER BY CASE WHEN sa.status = 'pending' THEN 0 ELSE 1 END, sa.created_at DESC"""
        ).fetchall()
    return render_template("student_accounts.html", accounts=accounts)


@app.post("/admin/student-accounts/<int:account_id>/approve")
@login_required
def approve_student_account(account_id):
    with db_connection() as conn:
        updated = conn.execute(
            """UPDATE student_accounts SET status = 'approved', reviewed_at = CURRENT_TIMESTAMP,
                      reviewed_by_admin_id = %s
               WHERE id = %s AND status = 'pending' RETURNING id""",
            (session["admin_id"], account_id)
        ).fetchone()
        if updated:
            log_audit_event(conn, "approve_student_account", "student_account", account_id)
    flash("Student account approved." if updated else "Account was not found or was already reviewed.",
          "success" if updated else "error")
    return redirect(url_for("student_accounts_admin"))


@app.post("/admin/student-accounts/<int:account_id>/reject")
@login_required
def reject_student_account(account_id):
    with db_connection() as conn:
        deleted = conn.execute(
            "DELETE FROM student_accounts WHERE id = %s AND status = 'pending' RETURNING id",
            (account_id,)
        ).fetchone()
        if deleted:
            log_audit_event(conn, "reject_student_account", "student_account", account_id)
    flash("Pending account request rejected." if deleted else "Account was not found or was already reviewed.",
          "success" if deleted else "error")
    return redirect(url_for("student_accounts_admin"))


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
            session["session_version"] = admin["session_version"]
            session["tracker_id"] = str(admin["tracker_id"])
            with db_connection() as conn:
                log_audit_event(conn, "login", "admin", admin["id"],
                                {"tracker_id": str(admin["tracker_id"])}, actor_admin_id=admin["id"])
                log_sign_in(conn, "admin", admin["id"], admin["username"],
                            admin["username"], admin["tracker_id"])
            next_url = request.args.get("next", "")
            return redirect(next_url if is_safe_redirect_target(next_url) else url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.post("/logout")
@login_required
def logout():
    with db_connection() as conn:
        log_audit_event(conn, "logout", "admin", session.get("admin_id"),
                        {"tracker_id": session.get("tracker_id")})
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


@app.get("/my-activity")
@login_required
def my_activity():
    admin_id = session["admin_id"]
    with db_connection() as conn:
        admin = conn.execute(
            "SELECT username, tracker_id, created_at FROM admins WHERE id = %s",
            (admin_id,)
        ).fetchone()
        events = conn.execute(
            """SELECT action, entity_type, entity_id, details, created_at
               FROM audit_logs
               WHERE actor_admin_id = %s
               ORDER BY created_at DESC
               LIMIT 100""",
            (admin_id,)
        ).fetchall()
    return render_template("my_activity.html", admin=admin, events=events)


def validate_student_form(form):
    data = {}
    errors = []
    for field, label in [("student_number", "Student number"), ("first_name", "First name"), ("last_name", "Last name")]:
        value = form.get(field, "").strip()
        if not value:
            errors.append(f"{label} is required.")
        elif len(value) > (40 if field == "student_number" else 100):
            errors.append(f"{label} is too long.")
        data[field] = value
    data["email"] = form.get("email", "").strip() or None
    if data["email"] and (
        len(data["email"]) > 255
        or "@" not in data["email"]
        or "." not in data["email"].rsplit("@", 1)[-1]
    ):
        errors.append("Enter a valid email address or leave it blank.")
    try:
        data["attendance"] = float(form.get("attendance", ""))
        if not math.isfinite(data["attendance"]) or not 0 <= data["attendance"] <= 100:
            errors.append("Attendance must be a finite number between 0 and 100.")
    except ValueError:
        data["attendance"] = 0
        errors.append("Attendance must be a number.")
    for subject in SUBJECTS:
        key = subject.lower().replace(" ", "_")
        try:
            data[key] = float(form.get(key, ""))
            if not math.isfinite(data[key]) or not 0 <= data[key] <= 100:
                errors.append(f"{subject} grade must be a finite number between 0 and 100.")
        except ValueError:
            data[key] = 0
            errors.append(f"{subject} grade must be a number.")
    return data, errors



@app.route("/subjects", methods=["GET", "POST"])
@login_required
def subjects_page():
    if request.method == "POST":
        code = request.form.get("subject_code", "").strip().upper()
        name = request.form.get("subject_name", "").strip()
        description = request.form.get("description", "").strip() or None
        try: units = float(request.form.get("units", "3"))
        except ValueError: units = 0
        if not code or len(code) > 30 or not name or len(name) > 150 or not math.isfinite(units) or not 0 < units <= 30:
            flash("Enter a valid subject code, name, and units (greater than 0 and at most 30).", "error")
        else:
            try:
                with db_connection() as conn:
                    new_subject = conn.execute(
                        """INSERT INTO subjects (subject_code, subject_name, units, description)
                           VALUES (%s, %s, %s, %s) RETURNING id""",
                        (code, name, units, description)).fetchone()
                    log_audit_event(conn, "create", "subject", new_subject["id"], {"subject_code": code})
                flash("Subject added. You can now enroll students and enter grades.", "success")
                return redirect(url_for("subject_detail", subject_id=new_subject["id"]))
            except psycopg.errors.UniqueViolation:
                flash("Subject code and subject name must both be unique.", "error")
    with db_connection() as conn:
        subjects = conn.execute(
            """SELECT sub.*, COUNT(DISTINCT ss.student_id) AS student_count
               FROM subjects sub LEFT JOIN student_subjects ss ON ss.subject_id = sub.id
               WHERE sub.is_active = TRUE GROUP BY sub.id ORDER BY sub.subject_name"""
        ).fetchall()
    return render_template("subjects.html", subjects=subjects)


@app.get("/subjects/<int:subject_id>")
@login_required
def subject_detail(subject_id):
    with db_connection() as conn:
        subject = conn.execute("SELECT * FROM subjects WHERE id = %s AND is_active = TRUE", (subject_id,)).fetchone()
        students = conn.execute(
            """SELECT ss.id AS enrollment_id, ss.academic_year, ss.semester,
                      st.id AS student_id, st.student_number, st.first_name, st.last_name,
                      MAX(CASE WHEN gr.term = 'Midterms' THEN gr.percentage END) AS midterms,
                      MAX(CASE WHEN gr.term = 'Finals' THEN gr.percentage END) AS finals
               FROM student_subjects ss JOIN students st ON st.id = ss.student_id
               LEFT JOIN grade_records gr ON gr.student_subject_id = ss.id
               WHERE ss.subject_id = %s
               GROUP BY ss.id, st.id ORDER BY st.last_name, st.first_name""", (subject_id,)).fetchall()
        available_students = conn.execute(
            "SELECT id, student_number, first_name, last_name FROM students ORDER BY last_name, first_name"
        ).fetchall()
    if not subject: abort(404)
    return render_template("subject_detail.html", subject=subject, students=students, available_students=available_students)


@app.post("/subjects/<int:subject_id>/enroll")
@login_required
def enroll_student(subject_id):
    student_id = request.form.get("student_id", type=int)
    academic_year = request.form.get("academic_year", "2026-2027").strip()
    semester = request.form.get("semester", "1st Semester").strip()
    if not student_id or not academic_year or len(academic_year) > 20 or semester not in ("1st Semester", "2nd Semester", "Summer"):
        flash("Choose a student, academic year, and valid semester.", "error")
        return redirect(url_for("subject_detail", subject_id=subject_id))
    try:
        with db_connection() as conn:
            enrollment = conn.execute(
                """INSERT INTO student_subjects (student_id, subject_id, academic_year, semester)
                   VALUES (%s, %s, %s, %s) RETURNING id""",
                (student_id, subject_id, academic_year, semester)).fetchone()
            log_audit_event(conn, "enroll", "student_subject", enrollment["id"],
                            {"student_id": student_id, "subject_id": subject_id, "academic_year": academic_year, "semester": semester})
        flash("Student enrolled in this subject.", "success")
    except psycopg.errors.UniqueViolation:
        flash("This student is already enrolled in that subject for the selected year and semester.", "error")
    except psycopg.errors.ForeignKeyViolation:
        flash("Student or subject was not found.", "error")
    return redirect(url_for("subject_detail", subject_id=subject_id))


@app.route("/enrollments/<int:enrollment_id>/grades", methods=["GET", "POST"])
@login_required
def enrollment_grades(enrollment_id):
    with db_connection() as conn:
        enrollment = conn.execute(
            """SELECT ss.*, st.student_number, st.first_name, st.last_name,
                      sub.subject_code, sub.subject_name, sub.units
               FROM student_subjects ss JOIN students st ON st.id = ss.student_id
               JOIN subjects sub ON sub.id = ss.subject_id WHERE ss.id = %s""", (enrollment_id,)).fetchone()
    if not enrollment: abort(404)
    if request.method == "POST":
        term = request.form.get("term", "")
        grade = validate_grade(request.form.get("percentage", ""))
        if term not in ("Midterms", "Finals") or grade is None:
            flash("Choose Midterms or Finals and enter a grade from 0 to 100.", "error")
        else:
            with db_connection() as conn:
                old = conn.execute("SELECT percentage FROM grade_records WHERE student_subject_id = %s AND term = %s",
                                   (enrollment_id, term)).fetchone()
                previous = float(old["percentage"]) if old else None
                conn.execute(
                    """INSERT INTO grade_records (student_subject_id, term, percentage, recorded_by_admin_id)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (student_subject_id, term) DO UPDATE
                       SET percentage = EXCLUDED.percentage, recorded_by_admin_id = EXCLUDED.recorded_by_admin_id,
                           updated_at = CURRENT_TIMESTAMP""",
                    (enrollment_id, term, grade, session["admin_id"]))
                conn.execute(
                    """INSERT INTO grade_record_history
                       (student_subject_id, term, action, previous_percentage, new_percentage, actor_admin_id)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (enrollment_id, term, "created" if previous is None else "updated", previous, grade, session["admin_id"]))
                log_audit_event(conn, "created" if previous is None else "updated", "grade_record", enrollment_id,
                                {"term": term, "previous_percentage": previous, "new_percentage": grade})
            flash(f"{term} grade saved. The GWA has been recalculated.", "success")
            return redirect(url_for("enrollment_grades", enrollment_id=enrollment_id))
    with db_connection() as conn:
        records = conn.execute(
            """SELECT id, term, percentage, created_at, updated_at FROM grade_records
               WHERE student_subject_id = %s ORDER BY CASE term WHEN 'Midterms' THEN 1 ELSE 2 END""", (enrollment_id,)).fetchall()
        history = conn.execute(
            """SELECT h.*, a.username AS admin_username FROM grade_record_history h
               LEFT JOIN admins a ON a.id = h.actor_admin_id
               WHERE h.student_subject_id = %s ORDER BY h.changed_at DESC LIMIT 100""", (enrollment_id,)).fetchall()
    summary = get_student_gwa_summary(enrollment["student_id"])
    subject_summary = next((s for s in summary["subjects"] if s["enrollment_id"] == enrollment_id), None)
    return render_template("enrollment_grades.html", enrollment=enrollment, records=records,
                           history=history, summary=summary, subject_summary=subject_summary)


@app.post("/grade-records/<int:record_id>/delete")
@login_required
def delete_grade_record(record_id):
    with db_connection() as conn:
        record = conn.execute(
            """SELECT gr.id, gr.student_subject_id, gr.term, gr.percentage
               FROM grade_records gr WHERE gr.id = %s""", (record_id,)).fetchone()
        if not record:
            flash("Grade record was not found.", "error")
            return redirect(url_for("subjects_page"))
        conn.execute(
            """INSERT INTO grade_record_history
               (student_subject_id, term, action, previous_percentage, new_percentage, actor_admin_id)
               VALUES (%s, %s, 'deleted', %s, NULL, %s)""",
            (record["student_subject_id"], record["term"], record["percentage"], session["admin_id"]))
        conn.execute("DELETE FROM grade_records WHERE id = %s", (record_id,))
        log_audit_event(conn, "delete", "grade_record", record_id,
                        {"term": record["term"], "previous_percentage": float(record["percentage"])})
        enrollment_id = record["student_subject_id"]
    flash("Grade deleted. The change remains in the history log and GWA was recalculated.", "success")
    return redirect(url_for("enrollment_grades", enrollment_id=enrollment_id))


@app.route("/admin/grade-import", methods=["GET", "POST"])
@login_required
def import_grade_report():
    if request.method == "POST":
        upload = request.files.get("report_file")
        if not upload or not upload.filename:
            flash("Choose a CSV or Excel (.xlsx) file to import.", "error")
            return render_template("grade_import.html")
        filename = upload.filename.lower()
        try:
            if filename.endswith(".csv"):
                rows = list(csv.DictReader(io.StringIO(upload.stream.read().decode("utf-8-sig"))))
            elif filename.endswith(".xlsx"):
                workbook = load_workbook(upload, read_only=True, data_only=True)
                values = list(workbook.active.iter_rows(values_only=True))
                if not values: raise ValueError("The workbook is empty.")
                headers = [str(value or "").strip() for value in values[0]]
                rows = [dict(zip(headers, row)) for row in values[1:] if any(value is not None for value in row)]
            else:
                raise ValueError("Unsupported file type. Use CSV or .xlsx.")
            required = {"Student Number", "Subject Code", "Academic Year", "Semester", "Term", "Percentage"}
            if not rows or not required.issubset(set(rows[0].keys())):
                raise ValueError("Missing required headers. Download the sample template to see the exact column names.")
            imported, skipped = 0, []
            with db_connection() as conn:
                for row_number, row in enumerate(rows, start=2):
                    student_number = str(row.get("Student Number") or "").strip()
                    code = str(row.get("Subject Code") or "").strip().upper()
                    year = str(row.get("Academic Year") or "").strip()
                    semester = str(row.get("Semester") or "").strip()
                    term = str(row.get("Term") or "").strip().title()
                    grade = validate_grade(row.get("Percentage"))
                    if not student_number or not code or not year or len(year) > 20 or semester not in ("1st Semester", "2nd Semester", "Summer") or term not in ("Midterms", "Finals") or grade is None:
                        skipped.append(f"Row {row_number}: invalid or missing values."); continue
                    student = conn.execute("SELECT id FROM students WHERE student_number = %s", (student_number,)).fetchone()
                    subject = conn.execute("SELECT id FROM subjects WHERE subject_code = %s AND is_active = TRUE", (code,)).fetchone()
                    if not student or not subject:
                        skipped.append(f"Row {row_number}: student number or subject code not found."); continue
                    enrollment = conn.execute(
                        """INSERT INTO student_subjects (student_id, subject_id, academic_year, semester)
                           VALUES (%s, %s, %s, %s)
                           ON CONFLICT (student_id, subject_id, academic_year, semester)
                           DO UPDATE SET student_id = EXCLUDED.student_id RETURNING id""",
                        (student["id"], subject["id"], year, semester)).fetchone()
                    old = conn.execute("SELECT percentage FROM grade_records WHERE student_subject_id = %s AND term = %s",
                                       (enrollment["id"], term)).fetchone()
                    previous = float(old["percentage"]) if old else None
                    conn.execute(
                        """INSERT INTO grade_records (student_subject_id, term, percentage, recorded_by_admin_id)
                           VALUES (%s, %s, %s, %s)
                           ON CONFLICT (student_subject_id, term) DO UPDATE
                           SET percentage = EXCLUDED.percentage, recorded_by_admin_id = EXCLUDED.recorded_by_admin_id,
                               updated_at = CURRENT_TIMESTAMP""",
                        (enrollment["id"], term, grade, session["admin_id"]))
                    conn.execute(
                        """INSERT INTO grade_record_history
                           (student_subject_id, term, action, previous_percentage, new_percentage, actor_admin_id)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (enrollment["id"], term, "created" if previous is None else "updated", previous, grade, session["admin_id"]))
                    imported += 1
                log_audit_event(conn, "import", "grade_report", details={"imported_rows": imported, "skipped_rows": len(skipped)})
            flash(f"Imported {imported} grade row(s). {len(skipped)} row(s) skipped.", "success" if not skipped else "error")
            for message in skipped[:10]: flash(message, "error")
        except (UnicodeDecodeError, ValueError, OSError) as exc:
            flash(str(exc), "error")
        except Exception:
            app.logger.exception("Grade report import failed")
            flash("The file could not be imported. Check the format and required headers.", "error")
    return render_template("grade_import.html")


@app.get("/admin/grade-import-template.csv")
@login_required
def export_grade_import_template():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student Number", "Subject Code", "Academic Year", "Semester", "Term", "Percentage"])
    writer.writerow(["STU-001", "PROG", "2026-2027", "1st Semester", "Midterms", "88.5"])
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=passasado_grade_import_template.csv"})


@app.get("/export/grade-report.xlsx")
@login_required
def export_grade_report():
    workbook = Workbook()
    records_sheet = workbook.active
    records_sheet.title = "Grade Records"
    records_sheet.append(["Student Number", "Student Name", "Subject Code", "Subject", "Units",
                          "Academic Year", "Semester", "Term", "Percentage", "Grade Point", "Last Updated", "Unique Student Tracker ID"])
    gwa_sheet = workbook.create_sheet("GWA Summary")
    gwa_sheet.append(["Student Number", "Student Name", "GWA", "Dean's List Status", "Subjects Graded", "Subjects Enrolled"])
    with db_connection() as conn:
        records = conn.execute(
            """SELECT st.id AS student_id, st.student_number, st.first_name, st.last_name, st.tracker_id,
                      sub.subject_code, sub.subject_name, sub.units, ss.academic_year, ss.semester,
                      gr.term, gr.percentage, gr.updated_at
               FROM grade_records gr JOIN student_subjects ss ON ss.id = gr.student_subject_id
               JOIN students st ON st.id = ss.student_id JOIN subjects sub ON sub.id = ss.subject_id
               ORDER BY st.student_number, ss.academic_year, ss.semester, sub.subject_name, gr.term""").fetchall()
        students = conn.execute("SELECT id, student_number, first_name, last_name FROM students ORDER BY student_number").fetchall()
        log_audit_event(conn, "export", "grade_report", details={"format": "xlsx"})
    for row in records:
        records_sheet.append([row["student_number"], f'{row["first_name"]} {row["last_name"]}', row["subject_code"],
                              row["subject_name"], float(row["units"]), row["academic_year"], row["semester"],
                              row["term"], float(row["percentage"]), percentage_to_grade_point(float(row["percentage"])),
                              row["updated_at"].replace(tzinfo=None) if row["updated_at"] else None, str(row["tracker_id"])])
    for student in students:
        summary = get_student_gwa_summary(student["id"])
        gwa_sheet.append([student["student_number"], f'{student["first_name"]} {student["last_name"]}',
                          summary["gwa"], summary["dean_status"], summary["graded_subjects"], summary["total_subjects"]])
    style_excel_table(records_sheet, "GradeRecordsTable")
    style_excel_table(gwa_sheet, "GWASummaryTable")
    for ws in (records_sheet, gwa_sheet):
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if cell.is_date: cell.number_format = "yyyy-mm-dd hh:mm:ss"
    output = io.BytesIO()
    workbook.save(output); output.seek(0)
    return Response(output.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=passasado_grade_report.xlsx"})


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
                inserted = conn.execute("""INSERT INTO students (student_number, first_name, last_name, email, attendance,
                    programming, database, mathematics, networking, web_development)
                    VALUES (%(student_number)s, %(first_name)s, %(last_name)s, %(email)s, %(attendance)s,
                    %(programming)s, %(database)s, %(mathematics)s, %(networking)s, %(web_development)s)
                    RETURNING id""", data).fetchone()
                log_audit_event(conn, "create", "student", inserted["id"],
                                {"changed_fields": ["student_record_created"]}) 
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
                log_audit_event(conn, "update", "student", student_id,
                                {"changed_fields": sorted(data.keys())})
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
        deleted = conn.execute(
            "DELETE FROM students WHERE id = %s RETURNING student_number", (student_id,)
        ).fetchone()
        if deleted:
            log_audit_event(conn, "delete", "student", student_id,
                            {"changed_fields": ["student_record_deleted"]})
    flash("Student deleted." if deleted else "Student record not found.", "success" if deleted else "error")
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
    with db_connection() as conn:
        log_audit_event(conn, "export_csv", "report", details={"format": "csv"})
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
    with db_connection() as conn:
        log_audit_event(conn, "export_pdf", "report", details={"format": "pdf"})
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


@app.get("/admin/sign-in-report.xlsx")
@login_required
def export_sign_in_report():
    """Export sign-in events and the current admin/student directory to Excel."""
    workbook = Workbook()
    logs_sheet = workbook.active
    logs_sheet.title = "Sign-in Logs"
    logs_sheet.append([
        "Sign-in ID", "Account Type", "Account Identifier", "Account Name",
        "Unique Tracker ID", "Sign-in Date and Time", "Status"
    ])
    directory_sheet = workbook.create_sheet("Account Directory")
    directory_sheet.append([
        "Account Type", "Account Identifier", "Account Name",
        "Unique Tracker ID", "Account Created At", "Sign-in Count"
    ])

    with db_connection() as conn:
        sign_ins = conn.execute(
            """SELECT id, account_type, account_identifier, account_name,
                      tracker_id, signed_in_at
               FROM sign_in_logs
               ORDER BY signed_in_at DESC, id DESC"""
        ).fetchall()
        admins = conn.execute(
            """SELECT a.id, a.username, a.tracker_id, a.created_at,
                      COUNT(s.id) AS sign_in_count
               FROM admins a LEFT JOIN sign_in_logs s
                 ON s.account_type = 'admin' AND s.account_id = a.id
               GROUP BY a.id ORDER BY a.username"""
        ).fetchall()
        students = conn.execute(
            """SELECT st.id, st.student_number, st.first_name, st.last_name,
                      st.tracker_id, st.created_at,
                      COUNT(s.id) AS sign_in_count
               FROM students st LEFT JOIN sign_in_logs s
                 ON s.account_type = 'student' AND s.account_id = st.id
               GROUP BY st.id ORDER BY st.last_name, st.first_name"""
        ).fetchall()

    for row in sign_ins:
        logs_sheet.append([
            row["id"], row["account_type"].title(), row["account_identifier"],
            row["account_name"], str(row["tracker_id"]),
            row["signed_in_at"].replace(tzinfo=None) if row["signed_in_at"] else None,
            "Successful"
        ])
    for row in admins:
        directory_sheet.append([
            "Admin", row["username"], row["username"], str(row["tracker_id"]),
            row["created_at"].replace(tzinfo=None) if row["created_at"] else None,
            row["sign_in_count"]
        ])
    for row in students:
        directory_sheet.append([
            "Student", row["student_number"], f'{row["first_name"]} {row["last_name"]}',
            str(row["tracker_id"]),
            row["created_at"].replace(tzinfo=None) if row["created_at"] else None,
            row["sign_in_count"]
        ])

    style_excel_table(logs_sheet, "SignInLogTable")
    style_excel_table(directory_sheet, "AccountDirectoryTable")
    for ws in (logs_sheet, directory_sheet):
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if cell.is_date:
                    cell.number_format = "yyyy-mm-dd hh:mm:ss"
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    with db_connection() as conn:
        log_audit_event(conn, "export_sign_in_report", "report", details={"format": "xlsx"})
    return Response(
        output.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=gradepilot_sign_in_report.xlsx"}
    )


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="The requested page or student record was not found."), 404


@app.errorhandler(500)
def server_error(_error):
    return render_template("error.html", code=500, message="An unexpected error occurred. Check the terminal for details."), 500


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
