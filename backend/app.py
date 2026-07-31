from flask import Flask
from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def home():
    return "Backend is running!"

@app.route("/admin")
def admin():
    return render_template("admin.html")
