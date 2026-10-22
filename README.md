# passASADO or FAILet

A local, rule-based Flask + PostgreSQL web application. It does **not** use AI, machine learning, AI APIs, or AI services. Grade and status decisions are made by the explicit Python functions in `app.py`.

## Features
- Admin sign-in with Werkzeug password hashing and server-side session authentication
- Student profiles and subject-specific enrollment lists
- Create subjects, enroll students, and record editable Midterms and Finals grades per subject
- Dashboard cards and Chart.js pass/fail and subject-average charts
- Grade history with edit/delete audit trail; GWA and estimated Dean's List status
- CSV and Excel import, plus Excel/CSV/PDF report exports
- PostgreSQL constraints for grade and attendance ranges

## Requirements
- Python 3.10 or newer
- PostgreSQL installed and running
- VS Code (Python extension recommended)
- Internet connection on first page load if you want the optional Chart.js and Google Fonts CDN assets. The app itself does not call any AI services.

## 1. Open the project in VS Code
Extract the ZIP, then use **File → Open Folder** and choose `student_grade_analyzer`.

## 2. Create a PostgreSQL database
Open pgAdmin or the PostgreSQL SQL Shell (`psql`) and run:

```sql
CREATE DATABASE student_grades;
```

Use the PostgreSQL username and password you created during installation. The default sample URL assumes username `postgres`; update it if yours differs.

## 3. Create a Python virtual environment
In VS Code, open **Terminal → New Terminal** and run:

### Windows PowerShell
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, you can run the venv's Python directly instead: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

## 4. Configure environment variables
Copy `.env.example` to a new file named `.env`. Replace `YOUR_POSTGRES_PASSWORD` with your actual PostgreSQL password. Change `SECRET_KEY` to a long, random private string. Do not share or commit `.env`.

Example URL format:
`DATABASE_URL=postgresql://postgres:your_password@localhost:5432/student_grades`

If your database password contains special characters such as `@`, `:`, `/`, or `#`, URL-encode those characters in the connection URL.

## 5. Create the tables and administrator
With the virtual environment active, run:

```powershell
flask --app app init-db
flask --app app create-admin
```

For `create-admin`, type a username and a password of at least 10 characters when prompted. The password is stored as a hash, not as plain text. You can create additional admins by running the command again with a different username.

## 6. Start the application
```powershell
flask --app app run --debug
```

Open `http://127.0.0.1:5000` in your browser and sign in with the admin account you created.

Stop the local server with `Ctrl+C` in the terminal.

## Original grading rules implemented

| Rule | Result |
|---|---|
| Average ≥ 90 / ≥ 80 / ≥ 70 / ≥ 60 / below 60 | A / B / C / D / F |
| Average ≥ 75 **and** attendance ≥ 80% | PASSED; otherwise FAILED |
| Average ≥ 95 / ≥ 90 / ≥ 85 / ≥ 80 / ≥ 75 / ≥ 60 / below 60 | Outstanding / Excellent / Very Good / Good / Satisfactory / Needs Improvement / Poor |
| Average ≥ 90 **and** attendance ≥ 90% | Scholarship Qualified |
| Average < 75 **and** attendance < 80% | Warning: Low grades and low attendance |
| Average < 75 only | Warning: Low grades |
| Attendance < 80% only | Warning: Low attendance |
| Otherwise | No warning |
| Subject grade ≥ 90 / ≥ 75 / below 75 | Excellent / Passed / Needs Improvement |

The overall average is the arithmetic mean of the five subject grades. No subject weighting was provided, so all five are equally weighted.


## Subject-based grading, GWA, and reports

1. Create a student profile from **Students** (profile details only).
2. Open **Subjects**, create the subject code/name/units, then open it and enroll students for an academic year and semester.
3. From the subject roster, open **Manage grades** and enter a percentage for **Midterms** or **Finals**. Saving a term again edits its current grade and records the previous/new value in grade history. Deleting a grade also leaves a history entry.
4. GWA uses the unit-weighted average of grade points for the latest academic year/semester with records. If only midterms are entered, the displayed GWA is interim; Dean's List eligibility stays pending until both midterms and finals exist for every enrolled subject.
5. The current sample percentage conversion is: 97–100 = 1.00; 94–96 = 1.25; 91–93 = 1.50; 88–90 = 1.75; 85–87 = 2.00; 82–84 = 2.25; 79–81 = 2.50; 76–78 = 2.75; 75 = 3.00; below 75 = 5.00. Midterms and finals are equally weighted in the current subject percentage.
6. The sample Dean's List defaults are GWA ≤ 1.75 and no subject grade point worse than 2.50. Administrators can edit these thresholds from **Subjects**. Confirm your institution's official conversion, weights, and eligibility requirements before using the status as an official decision.
7. **Import grade file** accepts CSV or XLSX with the headers Student Number, Subject Code, Academic Year, Semester, Term, and Percentage. Use the downloadable CSV template. The importer validates rows, reports skipped entries, creates missing enrollments for valid student/subject pairs, and records changes in history.
8. **Export grade report** creates an Excel workbook with current grade records and a GWA summary. Existing CSV/PDF student exports and the separate sign-in Excel report remain available.

## Database
`schema.sql` creates the `admins` and `students` tables and enforces 0–100 constraints for attendance and grades. The database must be created separately first. `flask --app app init-db` can be run again safely to ensure tables exist.

## Troubleshooting
- **Could not connect to server:** confirm PostgreSQL is running and the `.env` `DATABASE_URL` has the correct password, port, and database name.
- **`flask` is not recognized:** activate `.venv` and run `python -m flask --app app run --debug` instead.
- **Template not found:** make sure VS Code opened the project folder containing `app.py`, `templates/`, and `static/`.
- **Chart blank:** check internet access for the Chart.js CDN; grade calculations and exports are handled locally.
- **500 error:** check the VS Code terminal for the underlying error. Do not use Flask debug mode on a public server.

## Security and deployment notes

- Set a long, random `SECRET_KEY` in Render's environment variables. Production startup intentionally fails if it is missing. Never commit or share this value.
- Keep `FLASK_DEBUG=false` in production. Use Gunicorn or the platform's production server, not Flask's development server.
- Use HTTPS and keep `.env` private. Rotate any database password or API token that has been exposed.
- Forms use CSRF tokens. Admin sessions use HTTP-only cookies and are revoked when an administrator password is changed.
- Student create, edit, and delete operations are recorded in the `audit_logs` table. Audit records contain action metadata rather than student grade values.
- Grade and attendance inputs are validated on the server and constrained in PostgreSQL.
- Password recovery requires an already registered email or phone and a configured SMTP or Twilio sender. Verification codes expire after 10 minutes and allow up to five attempts.
- Automated regression tests run through GitHub Actions. Passing tests do not replace a deployment review, database backup plan, or manual security testing.

### Recovery administration

Use these Flask CLI commands from a trusted terminal with `DATABASE_URL` pointing to the intended database:

```powershell
py -m flask --app app set-admin-recovery-contact
py -m flask --app app reset-admin-password
```

These commands prompt for account details and passwords. Do not paste database credentials or recovery codes into chat or commit them to the repository.

The database schema is applied by `flask --app app init-db` and the configured Render startup command. The `session_version` migration and audit table are additive and do not delete student records.


## Per-administrator student trackers
- Every student record created by an administrator is assigned to that administrator. Student lists, search, subject rosters, grade entry/edit/delete, dashboard calculations, account approvals, imports, and exports are scoped to the signed-in administrator.
- New administrator accounts start with an empty student tracker. Existing student records are preserved with no administrator owner and remain separate from every new account's tracker; they are not automatically assigned or deleted.
- Student numbers are unique within each administrator's tracker, so separate trackers can contain independent records without exposing them to other administrators.
- Existing subjects remain in the shared subject catalog, but student rosters and counts show only records owned by the current administrator.
 
## Account tracking and Excel sign-in report
- Every administrator and student record receives a unique tracker ID.
- Successful administrator sign-ins and approved student sign-ins are recorded without storing passwords or session secrets.
- Students use the separate **Student sign in** and **Request access** pages. Registration must match an existing student number and school-record email, and stays pending until an administrator approves it from **Student Account Approvals**.
- Administrators should independently verify a student's identity before approving; matching the stored email is not email verification.
- Students can view only their own grade record after approval. Admin and student sessions use separate session keys.
- Administrators can download **Sign-in Excel Report** from the sidebar. The workbook includes filterable Excel tables with header rows on the **Sign-in Logs** and **Account Directory** sheets.
- The directory lists admin accounts and student records, including tracker IDs and sign-in counts. The report is restricted to authenticated administrators.
