
@app.cli.command("create-admin")
def create_admin_command():
    """Interactively create an administrator account."""
    import getpass

    username = input("Admin username: ").strip()
    password = getpass.getpass(
        "Admin password (minimum 10 characters): "
    )

    if not username or len(username) > 80 or len(password) < 10:
        raise SystemExit(
            "Username must be 1–80 characters and password "
            "must be at least 10 characters."
        )

    init_db()

    with db_connection() as conn:
        exists = conn.execute(
            "SELECT id FROM admins WHERE username = %s",
            (username,)
        ).fetchone()

        if exists:
            raise SystemExit("That username already exists.")

        conn.execute(
            """
            INSERT INTO admins (username, password_hash)
            VALUES (%s, %s)
            """,
            (username, generate_password_hash(password))
        )

    print("Administrator created successfully.")


@app.route("/setup-admin", methods=["GET", "POST"])
def setup_admin():
    """Temporarily create the first administrator."""
    setup_token = os.getenv("ADMIN_SETUP_TOKEN")

    if not setup_token:
        abort(404)

    if request.method == "POST":
        submitted_token = request.form.get("setup_token", "")
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not hmac.compare_digest(submitted_token, setup_token):
            abort(403)

        if not username or len(username) > 80:
            return "Username must be 1–80 characters.", 400

        if len(password) < 10:
            return "Password must be at least 10 characters.", 400

        # Lock the table while checking and creating the first admin.
        with db_connection() as conn:
            conn.execute(
                "LOCK TABLE admins IN EXCLUSIVE MODE"
            )

            admin_count = conn.execute(
                "SELECT COUNT(*) AS total FROM admins"
            ).fetchone()["total"]

            if admin_count > 0:
                abort(404)

            conn.execute(
                """
                INSERT INTO admins (username, password_hash)
                VALUES (%s, %s)
                """,
                (username, generate_password_hash(password))
            )

        return (
            "Administrator created successfully. "
            "Remove this temporary setup route and the "
            "ADMIN_SETUP_TOKEN environment variable."
        )

    return render_template_string("""
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport"
                  content="width=device-width, initial-scale=1">
            <title>Initial Administrator Setup</title>
        </head>
        <body>
            <h1>Create First Administrator</h1>

            <form method="post">
                <input type="hidden" name="csrf_token"
                       value="{{ csrf_token }}">

                <p>
                    <label>Setup token<br>
                        <input type="password" name="setup_token"
                               required autocomplete="off">
                    </label>
                </p>

                <p>
                    <label>Username<br>
                        <input type="text" name="username"
                               maxlength="80" required>
                    </label>
                </p>

                <p>
                    <label>Password (minimum 10 characters)<br>
                        <input type="password" name="password"
                               minlength="10" required
                               autocomplete="new-password">
                    </label>
                </p>

                <button type="submit">Create Administrator</button>
            </form>
        </body>
        </html>
    """)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with db_connection() as conn:
            admin = conn.execute(
                """
                SELECT id, username, password_hash
                FROM admins
                WHERE username = %s
                """,
                (username,)
            ).fetchone()

        if admin and check_password_hash(
            admin["password_hash"], password
        ):
            session.clear()
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]

            # Only redirect to a local application path.
            next_url = request.args.get("next", "")
            if not next_url.startswith("/") or next_url.startswith("//"):
                next_url = url_for("dashboard")

            return redirect(next_url)

        flash("Invalid username or password.", "error")

    return render_template("login.html")
