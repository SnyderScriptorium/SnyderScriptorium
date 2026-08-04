import os
from flask import Flask, render_template

# Find the exact folder where app.py lives
basedir = os.path.abspath(os.path.dirname(__file__))

# Explicitly point Flask to your templates folder using the absolute path
app = Flask(__name__, template_folder=os.path.join(basedir, "templates"))


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/K. W. Snyder-writing")
def K-W-Snyder-Writing():
    return render_template("K-W-Snyder-writing.html")


@app.route("/blog")
def theblog():
    return render_template("blog_templates/main_blog.html")


@app.route("/blog/curations")
def book-curations():
    return render_template("blog_templates/curations.html")


@app.route("/blog templates")
def bookreviews():
    return render_template("blog_templates/bookreviews.html")


@app.route("/blog/curiosity-cabinet")
def blog_cabinet():
    return render_template("blog_templates/curiosity_cabinet.html")


@app.route("/store")
def store():
    return render_template("store.html")


@app.route("/merch")
def merch():
    return render_template("merch.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/admin")
def admin_dashboard():
    return render_template("admin.html")


if __name__ == "__main__":
    app.run(debug=True)
