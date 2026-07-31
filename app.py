from flask import Flask, render_template_string

app = Flask(__name__)


@app.route("/")
def home():
  # This reads the index.html file straight from the main directory
  try:
    with open("index.html", "r", encoding="utf-8") as f:
      return render_template_string(f.read())
  except FileNotFoundError:
    return (
        "Error: index.html not found in root directory. Please check file"
        " placement."
    )


if __name__ == "__main__":
  app.run(debug=True)
