import os
from flask import Flask, render_template

# Find the exact folder where app.py lives
basedir = os.path.abspath(os.path.dirname(__file__))

# Explicitly point Flask to your templates folder using the absolute path
app = Flask(__name__, template_folder=os.path.join(basedir, "templates"))

    @app.route("/")
def the_hearth():
    return render_template("index.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/blog")
def the_blog():
    return render_template("blog_templates/theblog.html")


@app.route("/blog/bookcurations")
def book_curations():
    return render_template("blog_templates/book_curations.html")


@app.route("/blog/bookreviews")
def bookreviews():
    return render_template("blog_templates/bookreviews.html")


@app.route("/blog/curiosity_cabinet")
def curiosity_cabinet():
    return render_template("blog_templates/curiosity_cabinet.html")


@app.route("/kwsnyderwriting")
def kwsnyderwriting():
    return render_template("kwsnyderwriting.html")


@app.route("/store")
def the_scriptorium():
    return render_template("store.html")


@app.route("/merch")
def merch_shop():
    return render_template("merch.html")


@app.route("/admin")
def admin_dashboard():
    return render_template("admin.html")


if __name__ == "__main__":
    app.run(debug=True)
