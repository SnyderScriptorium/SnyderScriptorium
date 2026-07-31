import os
from flask import Flask, render_template

# Get the absolute path of the directory where app.py is located
basedir = os.path.abspath(os.path.dirname(__file__))

# Point Flask explicitly to the templates folder in that directory
app = Flask(
    __name__,
    template_folder=os.path.join(basedir, "templates"),
    static_folder=os.path.join(basedir, "static"),
)


@app.route("/")
def home():
  return render_template("index.html")


@app.route("/about")
def about():
  return render_template("about.html")


@app.route("/admin")
def admin():
  return render_template("admin.html")


@app.route("/book-curations")
def book_curations():
  return render_template("book-curations.html")


@app.route("/book-reviews")
def book_reviews():
  return render_template("book-reviews.html")


@app.route("/curiosity-cabinet")
def curiosity_cabinet():
  return render_template("curiosity-cabinet.html")


if __name__ == "__main__":
  app.run(debug=True)
