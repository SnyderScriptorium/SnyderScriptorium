import os
from flask import Flask, render_template_string

app = Flask(__name__)


def load_html(filename):
  # Looks for the file in a 'templates' folder first, or right next to app.py
  paths_to_try = [
      os.path.join("templates", filename),
      filename,
  ]
  for path in paths_to_try:
    if os.path.exists(path):
      with open(path, "r", encoding="utf-8") as f:
        return f.read()
  return f"Error: {filename} could not be found."


@app.route("/")
def home():
  return render_template_string(load_html("index.html"))


@app.route("/about")
def about():
  return render_template_string(load_html("about.html"))


@app.route("/admin")
def admin():
  return render_template_string(load_html("admin.html"))


@app.route("/book-curations")
def book_curations():
  return render_template_string(load_html("book-curations.html"))


@app.route("/book-reviews")
def book_reviews():
  return render_template_string(load_html("book-reviews.html"))


@app.route("/curiosity-cabinet")
def curiosity_cabinet():
  return render_template_string(load_html("curiosity-cabinet.html"))


if __name__ == "__main__":
  app.run(debug=True)
