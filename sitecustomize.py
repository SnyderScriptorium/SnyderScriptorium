"""Production startup repair for PostgreSQL serial sequences.

Python imports ``sitecustomize`` automatically during normal startup. This
hook repairs the bookstore image sequence that can fall behind after a
bulk/manual data migration, and also extends the app's existing sequence
repair so the problem stays fixed on future boots.
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


def _extend_database_sequence_repair():
    """Include store_product_images in the app's normal startup repair."""
    try:
        import database
        original = getattr(database, "_repair_sequences", None)
        if not original or getattr(original, "_includes_store_product_images", False):
            return

        def repaired(conn):
            original(conn)
            if not database.using_postgres():
                return
            try:
                conn.execute(
                    "SELECT setval(pg_get_serial_sequence('store_product_images', 'id'), "
                    "COALESCE((SELECT MAX(id) FROM store_product_images), 1))"
                )
            except Exception:
                pass

        repaired._includes_store_product_images = True
        database._repair_sequences = repaired
    except Exception as exc:
        print("[sitecustomize] database sequence hook skipped: %s" % exc, flush=True)


_repair_store_image_sequence()
_extend_database_sequence_repair()
