"""Production startup repair for PostgreSQL serial sequences.

Python imports ``sitecustomize`` automatically during normal startup. This
small hook repairs the bookstore image sequence that can fall behind after a
bulk/manual data migration. The repair is intentionally best-effort and has
no effect on local SQLite development.
"""

import os


def _repair_store_image_sequence():
    database_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not database_url:
        return
    try:
        import psycopg

        conn = psycopg.connect(database_url, connect_timeout=10)
        try:
            # The table already exists on the live database. If this hook runs
            # before schema creation on a fresh environment, simply skip it.
            conn.execute(
                "SELECT setval(pg_get_serial_sequence('store_product_images', 'id'), "
                "COALESCE((SELECT MAX(id) FROM store_product_images), 1))"
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        # Never prevent the application from starting because of this repair.
        print("[sitecustomize] store image sequence repair skipped: %s" % exc, flush=True)


_repair_store_image_sequence()
