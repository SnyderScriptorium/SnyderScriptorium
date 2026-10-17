"""Repair bookstore PostgreSQL ID sequences after schema startup.

This is imported by the production WSGI entry point after the store tables
exist. It intentionally runs on every boot because an old sequence can remain
behind after manual imports or prior migrations.
"""

from database import get_db, using_postgres


def repair_store_sequences():
    if not using_postgres():
        return

    conn = get_db()
    try:
        # Serialize this repair so two workers cannot both repair the sequence
        # while a bookstore image insert is happening.
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('snyderscriptorium_store_image_sequences'))"
        )
        for table in ("store_product_images", "store_images"):
            conn.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
            )
        conn.commit()
    finally:
        conn.close()


repair_store_sequences()
