# Student Grade Management and Performance Analyzer

A local, rule-based Flask + PostgreSQL web application. It does **not** use AI, machine learning, AI APIs, or AI services. Grade and status decisions are made by the explicit Python functions in `app.py`.

## Features
- Admin sign-in with Werkzeug password hashing and server-side session authentication
- Student CRUD: create, view, edit, delete, and search
- Five equally weighted subjects: Programming, Database, Mathematics, Networking, Web Development
- Dashboard cards and Chart.js pass/fail and subject-average charts
- CSV and PDF exports
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

## Database
`schema.sql` creates the `admins` and `students` tables and enforces 0–100 constraints for attendance and grades. The database must be created separately first. `flask --app app init-db` can be run again safely to ensure tables exist.

## Troubleshooting
- **Could not connect to server:** confirm PostgreSQL is running and the `.env` `DATABASE_URL` has the correct password, port, and database name.
- **`flask` is not recognized:** activate `.venv` and run `python -m flask --app app run --debug` instead.
- **Template not found:** make sure VS Code opened the project folder containing `app.py`, `templates/`, and `static/`.
- **Chart blank:** check internet access for the Chart.js CDN; grade calculations and exports are handled locally.
- **500 error:** check the VS Code terminal for the underlying error. Do not use Flask debug mode on a public server.

## Security notes
This package is intended for local development. Before exposing it to a network, set a strong secret key, disable debug mode, configure HTTPS and secure cookies, add CSRF protection, and review deployment security. Keep `.env` private. The built-in development server is not intended for production deployment.
