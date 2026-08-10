from app import app, DATABASE, init_db
from analytics import init_analytics

app.config["DATABASE"] = DATABASE
init_db()
init_analytics(app)

if __name__ == "__main__":
    app.run()
