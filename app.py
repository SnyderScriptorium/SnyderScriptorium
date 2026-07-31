import os
from flask import Flask, render_template

# Explicitly tell Flask where the templates and static folders are
app = Flask(
    __name__,
    template_folder=os.path.abspath("templates"),
    static_folder=os.path.abspath("static"),
)


@app.route("/")
def home():
  return render_template("index.html")


if __name__ == "__main__":
  app.run(debug=True)
