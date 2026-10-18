"""Repair bookstore PostgreSQL ID sequences after schema startup.

This runs during production startup so manual imports or older migrations
cannot leave an auto-increment sequence behind the table's actual MAX(id).
"""

from database import get_db, using_postgres


def repair_store_sequences():
    if not using_postgres():
        return

    conn = get_db()
    try:
        # Serialize repairs so two workers cannot repair sequences concurrently
        # while a bookstore insert is happening.
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('snyderscriptorium_store_sequences'))"
        )
        for table in (
            "store_categories",
            "store_products",
            "store_orders",
            "store_order_items",
            "store_product_images",
            "store_images",
        ):
            conn.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
            )
        conn.commit()
    finally:
        conn.close()


repair_store_sequences()
