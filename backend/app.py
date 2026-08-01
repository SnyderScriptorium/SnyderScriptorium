from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = "your-secret-key-here"

@app.route("/")
def home():
    return "Backend is running!"

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # Replace with your real credentials
        if username == "Snyder" and password == "scriptorium123":
            session["logged_in"] = True
            return redirect("/admin")
        else:
            return "Invalid credentials"

    return render_template("login.html")

@app.route("/admin")
def admin():
    if not session.get("logged_in"):
        return redirect("/login")
    return render_template("admin.html")
