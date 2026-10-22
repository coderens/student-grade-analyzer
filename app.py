            "course_section": request.form.get("course_section", ""),
            **{key: request.form.get(key, "") for key, _ in SUBJECTS},
        }

    return page("Edit student", STUDENT_FORM, heading="Edit student", student=student, subjects=SUBJECTS, error=error)


@app.route("/students/<int:student_id>/delete", methods=["POST"])
@login_required
def student_delete(student_id):
    init_db()
    with db_connection() as conn:
        conn.execute("DELETE FROM students WHERE id = %s", (student_id,))
    flash("Student deleted.", "success")
    return redirect(url_for("students"))


# ------------------------------------------------------------
# CSV and PDF exports
# ------------------------------------------------------------
def get_student_report_rows():
    with db_connection() as conn:
        rows = conn.execute("SELECT * FROM students ORDER BY full_name").fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["average"] = average_for(item)
        item["grade_label"] = grade_label(item["average"])
        output.append(item)
    return output


@app.route("/export/csv")
@login_required
def export_csv():
    init_db()
    rows = get_student_report_rows()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student Number", "Full Name", "Course / Section"] +
                    [label for _, label in SUBJECTS] + ["Average", "Interpretation"])
    for row in rows:
        writer.writerow(
            [row["student_number"], row["full_name"], row["course_section"]] +
            [row[key] for key, _ in SUBJECTS] +
            [f'{row["average"]:.2f}', row["grade_label"]]
        )
    memory = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    memory.seek(0)
    return send_file(memory, mimetype="text/csv", as_attachment=True, download_name="student_grade_report.csv")


@app.route("/export/pdf")
@login_required
def export_pdf():
    init_db()
    rows = get_student_report_rows()
    memory = io.BytesIO()
    document = SimpleDocTemplate(memory, pagesize=landscape(letter), rightMargin=24, leftMargin=24, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Student Grade Analyzer — Report", styles["Title"]),
        Spacer(1, 12),
        Paragraph(f"Total students: {len(rows)}", styles["Normal"]),
        Spacer(1, 12),
    ]
    table_data = [["Student No.", "Full Name", "Course / Section"] +
                  [label for _, label in SUBJECTS] + ["Average", "Interpretation"]]
    for row in rows:
        table_data.append(
            [str(row["student_number"]), str(row["full_name"]), str(row["course_section"])] +
            [f'{float(row[key]):.2f}' for key, _ in SUBJECTS] +
            [f'{row["average"]:.2f}', row["grade_label"]]
        )
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#152544")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd2df")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f5f9")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    document.build(story)
    memory.seek(0)
    return send_file(memory, mimetype="application/pdf", as_attachment=True, download_name="student_grade_report.pdf")


# ------------------------------------------------------------
# Friendly error pages
# ------------------------------------------------------------
@app.errorhandler(400)
def bad_request(error):
    return page("Bad request", """
      <section class="card"><h1>Request could not be processed</h1>
      <p>{{ error.description or 'Please refresh the page and try again.' }}</p>
      <a class="button" href="{{ url_for('login') }}">Return</a></section>
    """, error=error), 400


@app.errorhandler(403)
def forbidden(_error):
    return page("Forbidden", "<section class='card'><h1>Access denied</h1><p>You are not allowed to perform this action.</p></section>"), 403


@app.errorhandler(404)
def not_found(_error):
    return page("Not found", "<section class='card'><h1>Page not found</h1><p>The requested page is unavailable.</p></section>"), 404


if __name__ == "__main__":
    # For local development only. Production hosts such as Render use Gunicorn.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
