from functools import wraps
from flask import jsonify, request

from database import get_db, using_postgres, IntegrityError


REQUEST_HEADER = "X-Draft-Request-ID"


def ensure_table():
    conn = get_db()
    try:
        if using_postgres():
            conn.execute(
                "CREATE TABLE IF NOT EXISTS draft_save_requests (request_id TEXT PRIMARY KEY, draft_id BIGINT NOT NULL, response_json TEXT NOT NULL, date_created TEXT NOT NULL)"
            )
        else:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS draft_save_requests (request_id TEXT PRIMARY KEY, draft_id INTEGER NOT NULL, response_json TEXT NOT NULL, date_created TEXT NOT NULL)"
            )
        conn.commit()
    finally:
        conn.close()


def register(app):
    ensure_table()
    endpoint = app.view_functions.get("create_draft")
    if endpoint is None or getattr(endpoint, "_snyder_draft_guard", False):
        return

    @wraps(endpoint)
    def guarded_create_draft(*args, **kwargs):
        request_id = str(request.headers.get(REQUEST_HEADER, "")).strip()
        if not request_id:
            return endpoint(*args, **kwargs)

        ensure_table()
        conn = get_db()
        try:
            existing = conn.execute(
                "SELECT response_json FROM draft_save_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if existing:
                import json
                payload = json.loads(existing["response_json"])
                return jsonify(payload), 200
        finally:
            conn.close()

        response = endpoint(*args, **kwargs)
        status = response[1] if isinstance(response, tuple) and len(response) > 1 else 200
        body = response[0] if isinstance(response, tuple) else response
        if int(status) < 200 or int(status) >= 300 or not hasattr(body, "get_json"):
            return response

        payload = body.get_json(silent=True) or {}
        draft_id = payload.get("id")
        if not payload.get("success") or not draft_id:
            return response

        import json
        from datetime import datetime
        conn = get_db()
        try:
            try:
                conn.execute(
                    "INSERT INTO draft_save_requests(request_id, draft_id, response_json, date_created) VALUES (?, ?, ?, ?)",
                    (request_id, int(draft_id), json.dumps(payload), datetime.now().strftime("%m/%d/%Y %I:%M %p")),
                )
                conn.commit()
            except IntegrityError:
                conn.rollback()
        finally:
            conn.close()
        return response

    guarded_create_draft._snyder_draft_guard = True
    app.view_functions["create_draft"] = guarded_create_draft
