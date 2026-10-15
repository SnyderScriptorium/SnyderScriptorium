"""Temporary web-triggered migration: Neon -> new Render Postgres.

Visit /admin/migrate-neon (admin auth required) to start.
Poll /admin/migrate-status for progress.

DELETE THIS FILE after migration completes.
"""
import os
import threading
import time
import traceback

from flask import Blueprint, jsonify, request

migrate_bp = Blueprint("migrate_neon", __name__)

_state = {"status": "idle", "log": [], "started_at": None, "finished_at": None}


def _log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    _state["log"].append(line)
    print(line, flush=True)


def _run_migration():
    _state["status"] = "running"
    _state["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        import psycopg
        from psycopg.rows import dict_row

        source_url = os.environ.get("DATABASE_URL", "")
        target_url = os.environ.get("TARGET_DATABASE_URL", "")
        if not source_url or not target_url:
            raise RuntimeError("DATABASE_URL or TARGET_DATABASE_URL missing")

        # Import schema builders (read DATABASE_URL at import; override first)
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        os.environ["DATABASE_URL"] = target_url
        import importlib
        import database
        importlib.reload(database)
        _log("Creating schema on target...")
        database.init_db()
        from store import ensure_store_tables
        ensure_store_tables()
        _log("Schema ready.")

        TABLE_ORDER = [
            "drafts", "published_posts", "manuscript_books", "manuscript_chapters",
            "members", "subscriptions", "inbox_messages", "site_content",
            "page_views", "find_us_events", "blocked_senders", "push_subscriptions",
            "email_subscribers", "store_categories", "store_products",
            "store_orders", "store_order_items", "store_product_images",
            "store_images",
        ]

        _log("Connecting to source (Neon)...")
        src = psycopg.connect(source_url, row_factory=dict_row, connect_timeout=30)
        _log("Connecting to target (Render)...")
        dst = psycopg.connect(target_url, row_factory=dict_row, connect_timeout=30)

        with src.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
            src_tables = {r["table_name"] for r in cur.fetchall()}

        total = 0
        with dst:
            for table in TABLE_ORDER:
                if table not in src_tables:
                    _log(f"{table}: not in source, skipped")
                    continue
                with src.cursor() as scur:
                    scur.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name=%s ORDER BY ordinal_position",
                        (table,),
                    )
                    cols = [r["column_name"] for r in scur.fetchall()]
                qcols = ", ".join(f'"{c}"' for c in cols)
                with src.cursor() as scur:
                    scur.execute(f'SELECT {qcols} FROM "{table}"')
                    rows = scur.fetchall()
                with dst.cursor() as dcur:
                    dcur.execute(f'DELETE FROM "{table}"')
                    if rows:
                        ph = ", ".join(["%s"] * len(cols))
                        data = [tuple(r[c] for c in cols) for r in rows]
                        dcur.executemany(
                            f'INSERT INTO "{table}" ({qcols}) VALUES ({ph})', data
                        )
                total += len(rows)
                _log(f"{table}: {len(rows)} rows copied")

            _log("Resetting sequences...")
            with dst.cursor() as cur:
                cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                for (table,) in cur.fetchall():
                    cur.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name=%s AND column_default LIKE 'nextval%%'",
                        (table,),
                    )
                    for (col,) in cur.fetchall():
                        cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (table, col))
                        seq = cur.fetchone()[0]
                        if seq:
                            cur.execute(
                                f"SELECT setval('{seq}', COALESCE(MAX(\"{col}\"), 1)) FROM \"{table}\""
                            )
            dst.commit()

        _log("Verifying counts...")
        mismatches = []
        for table in TABLE_ORDER:
            if table not in src_tables:
                continue
            with src.cursor() as scur, dst.cursor() as dcur:
                scur.execute(f'SELECT COUNT(*) AS c FROM "{table}"')
                dcur.execute(f'SELECT COUNT(*) AS c FROM "{table}"')
                s, d = scur.fetchone()["c"], dcur.fetchone()["c"]
                ok = "OK" if s == d else "MISMATCH!"
                if s != d:
                    mismatches.append(table)
                _log(f"{table}: source={s} target={d} {ok}")

        src.close()
        dst.close()
        _log(f"Done. {total} rows copied.")
        if mismatches:
            _state["status"] = "mismatch"
            _log(f"MISMATCHES: {mismatches}")
        else:
            _state["status"] = "complete"
    except Exception as e:
        _state["status"] = "error"
        _log(f"ERROR: {e}")
        _log(traceback.format_exc())
    finally:
        _state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")


def _check_admin():
    # Reuse the app's admin password check
    admin_pw = os.environ.get("ADMIN_PASSWORD", "")
    return admin_pw and request.args.get("pw") == admin_pw


@migrate_bp.route("/admin/migrate-neon")
def start_migration():
    if not _check_admin():
        return "Unauthorized", 401
    if _state["status"] == "running":
        return jsonify({"status": "already running", "log": _state["log"]})
    if _state["status"] == "complete":
        return jsonify({"status": "already complete", "log": _state["log"]})
    _state["log"] = []
    t = threading.Thread(target=_run_migration, daemon=True)
    t.start()
    return jsonify({"status": "started", "message": "Migration running in background. Poll /admin/migrate-status?pw=..."})


@migrate_bp.route("/admin/migrate-status")
def migration_status():
    if not _check_admin():
        return "Unauthorized", 401
    return jsonify(_state)


@migrate_bp.route("/admin/verify-migration")
def verify_migration():
    """Standalone count verification with fresh connections. Safe to re-run."""
    if not _check_admin():
        return "Unauthorized", 401
    import psycopg
    from psycopg.rows import dict_row

    source_url = os.environ.get("DATABASE_URL", "")
    target_url = os.environ.get("TARGET_DATABASE_URL", "")
    if not source_url or not target_url:
        return jsonify({"error": "missing URLs"}), 500

    tables = [
        "drafts", "published_posts", "manuscript_books", "manuscript_chapters",
        "members", "subscriptions", "inbox_messages", "site_content",
        "page_views", "find_us_events", "blocked_senders", "push_subscriptions",
        "email_subscribers", "store_categories", "store_products",
        "store_orders", "store_order_items", "store_product_images",
        "store_images",
    ]
    results = []
    mismatches = []
    try:
        src = psycopg.connect(source_url, row_factory=dict_row, connect_timeout=30)
        dst = psycopg.connect(target_url, row_factory=dict_row, connect_timeout=30)
        for table in tables:
            try:
                with src.cursor() as scur, dst.cursor() as dcur:
                    scur.execute(f'SELECT COUNT(*) AS c FROM "{table}"')
                    dcur.execute(f'SELECT COUNT(*) AS c FROM "{table}"')
                    s, d = scur.fetchone()["c"], dcur.fetchone()["c"]
                    ok = (s == d)
                    if not ok:
                        mismatches.append(table)
                    results.append({"table": table, "source": s, "target": d, "match": ok})
            except Exception as e:
                results.append({"table": table, "error": str(e), "match": False})
                mismatches.append(table)
        src.close()
        dst.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "all_match": len(mismatches) == 0,
        "mismatches": mismatches,
        "tables": results,
    })
