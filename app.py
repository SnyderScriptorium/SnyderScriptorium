
@app.route("/admin")
def admin_dashboard():
    if not require_admin():
        return redirect(url_for("admin_login"))
    return render_template("admin.html", logged_in=True)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "GET":
        if require_admin():
            return redirect(url_for("admin_dashboard"))
        return render_template("admin.html", logged_in=False)

    password = request.form.get("password", "")
    configured_password = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not configured_password:
        return render_template("admin.html", logged_in=False, login_error="Admin password is not configured on the server.")
    if password == configured_password:
        session.clear()
        session.permanent = False
        session["admin_logged_in"] = True
        session["admin_auth_version"] = ADMIN_AUTH_VERSION
        return redirect(url_for("admin_dashboard"))
    return render_template("admin.html", logged_in=False, login_error="The admin password was not recognized.")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))
