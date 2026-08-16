import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for, abort

from database import get_db, using_postgres, IntegrityError

store_bp = Blueprint("store", __name__)

ALLOWED_STATUS = {"draft", "active", "archived"}


def now_string():
    return datetime.now().strftime("%m/%d/%Y %I:%M %p")


def require_admin():
    return bool(
        session.get("admin_logged_in") is True
        and session.get("admin_auth_version") == "2026-08-16-1"
    )


def admin_required():
    if not require_admin():
        return redirect(url_for("admin_login_page"))
    return None


def slugify(value):
    value = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return value or "book"


def ensure_store_tables():
    conn = get_db()
    try:
        if using_postgres():
            statements = [
                "CREATE TABLE IF NOT EXISTS store_categories (id BIGSERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, date_created TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_products (id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, author TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', price_cents INTEGER NOT NULL DEFAULT 0, format TEXT NOT NULL DEFAULT 'Paperback', isbn TEXT NOT NULL DEFAULT '', cover_image_url TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'Books', stock_quantity INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'draft', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_orders (id BIGSERIAL PRIMARY KEY, customer_name TEXT NOT NULL DEFAULT '', customer_email TEXT NOT NULL DEFAULT '', total_cents INTEGER NOT NULL DEFAULT 0, payment_status TEXT NOT NULL DEFAULT 'unpaid', order_status TEXT NOT NULL DEFAULT 'pending', provider TEXT NOT NULL DEFAULT '', provider_order_id TEXT NOT NULL DEFAULT '', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_order_items (id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL REFERENCES store_orders(id) ON DELETE CASCADE, product_id BIGINT NOT NULL REFERENCES store_products(id), quantity INTEGER NOT NULL DEFAULT 1, unit_price_cents INTEGER NOT NULL DEFAULT 0)",
            ]
        else:
            statements = [
                "CREATE TABLE IF NOT EXISTS store_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, date_created TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_products (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, author TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', price_cents INTEGER NOT NULL DEFAULT 0, format TEXT NOT NULL DEFAULT 'Paperback', isbn TEXT NOT NULL DEFAULT '', cover_image_url TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'Books', stock_quantity INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'draft', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT NOT NULL DEFAULT '', customer_email TEXT NOT NULL DEFAULT '', total_cents INTEGER NOT NULL DEFAULT 0, payment_status TEXT NOT NULL DEFAULT 'unpaid', order_status TEXT NOT NULL DEFAULT 'pending', provider TEXT NOT NULL DEFAULT '', provider_order_id TEXT NOT NULL DEFAULT '', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_order_items (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES store_orders(id) ON DELETE CASCADE, product_id INTEGER NOT NULL REFERENCES store_products(id), quantity INTEGER NOT NULL DEFAULT 1, unit_price_cents INTEGER NOT NULL DEFAULT 0)",
            ]
        for statement in statements:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO store_categories(name, date_created) VALUES (?, ?) ON CONFLICT(name) DO NOTHING",
            ("Books", now_string()),
        )
        conn.commit()
    finally:
        conn.close()


def parse_price(value):
    try:
        amount = Decimal(str(value).strip()).quantize(Decimal("0.01"))
        if amount < 0:
            raise InvalidOperation
        return int(amount * 100)
    except (InvalidOperation, ValueError):
        raise ValueError("Price must be a non-negative dollar amount.")


def product_payload(data):
    title = str(data.get("title", "")).strip()
    if not title:
        raise ValueError("A book title is required.")
    price_cents = parse_price(data.get("price", "0"))
    try:
        stock = int(data.get("stock_quantity", 0) or 0)
    except (TypeError, ValueError):
        raise ValueError("Stock quantity must be a whole number.")
    if stock < 0:
        raise ValueError("Stock quantity cannot be negative.")
    status = str(data.get("status", "draft")).strip().lower()
    if status not in ALLOWED_STATUS:
        raise ValueError("Invalid product status.")
    return {
        "title": title,
        "slug": slugify(data.get("slug") or title),
        "author": str(data.get("author", "")).strip(),
        "description": str(data.get("description", "")).strip(),
        "price_cents": price_cents,
        "format": str(data.get("format", "Paperback")).strip() or "Paperback",
        "isbn": str(data.get("isbn", "")).strip(),
        "cover_image_url": str(data.get("cover_image_url", "")).strip(),
        "category": str(data.get("category", "Books")).strip() or "Books",
        "stock_quantity": stock,
        "status": status,
    }


def row_to_dict(row):
    item = dict(row)
    item["price"] = f"{item['price_cents'] / 100:.2f}"
    return item


@store_bp.before_request
def prepare_store():
    ensure_store_tables()


@store_bp.route("/store")
def store_home():
    return render_template("store.html")


@store_bp.route("/store/book/<slug>")
def store_book(slug):
    conn = get_db()
    product = conn.execute(
        "SELECT * FROM store_products WHERE slug = ? AND status = 'active'",
        (slug,),
    ).fetchone()
    conn.close()
    if not product:
        abort(404)
    return render_template("store_book.html", product=row_to_dict(product))


@store_bp.route("/api/store/products")
def public_products():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM store_products WHERE status = 'active' ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return jsonify([row_to_dict(row) for row in rows])


@store_bp.route("/api/store/products/<int:product_id>")
def public_product(product_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM store_products WHERE id = ? AND status = 'active'",
        (product_id,),
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Book not found."}), 404
    return jsonify(row_to_dict(row))


@store_bp.route("/admin/store")
def admin_store():
    blocked = admin_required()
    if blocked:
        return blocked
    return render_template("admin_store.html")


@store_bp.route("/api/store/admin/products", methods=["GET"])
def admin_products():
    blocked = admin_required()
    if blocked:
        return blocked
    conn = get_db()
    rows = conn.execute("SELECT * FROM store_products ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([row_to_dict(row) for row in rows])


@store_bp.route("/api/store/admin/products", methods=["POST"])
def admin_create_product():
    blocked = admin_required()
    if blocked:
        return blocked
    try:
        product = product_payload(request.get_json() or {})
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    conn = get_db()
    try:
        timestamp = now_string()
        conn.execute(
            "INSERT INTO store_products(title, slug, author, description, price_cents, format, isbn, cover_image_url, category, stock_quantity, status, date_created, date_updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (product["title"], product["slug"], product["author"], product["description"], product["price_cents"], product["format"], product["isbn"], product["cover_image_url"], product["category"], product["stock_quantity"], product["status"], timestamp, timestamp),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM store_products WHERE slug = ?", (product["slug"],)).fetchone()
    except IntegrityError:
        conn.rollback()
        conn.close()
        return jsonify({"error": "A bookstore product with that slug already exists."}), 409
    conn.close()
    return jsonify({"success": True, "product": row_to_dict(row)}), 201


@store_bp.route("/api/store/admin/products/<int:product_id>", methods=["GET"])
def admin_get_product(product_id):
    blocked = admin_required()
    if blocked:
        return blocked
    conn = get_db()
    row = conn.execute("SELECT * FROM store_products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Book not found."}), 404
    return jsonify(row_to_dict(row))


@store_bp.route("/api/store/admin/products/<int:product_id>", methods=["PUT"])
def admin_update_product(product_id):
    blocked = admin_required()
    if blocked:
        return blocked
    try:
        product = product_payload(request.get_json() or {})
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    conn = get_db()
    existing = conn.execute("SELECT id FROM store_products WHERE id = ?", (product_id,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({"error": "Book not found."}), 404
    try:
        conn.execute(
            "UPDATE store_products SET title = ?, slug = ?, author = ?, description = ?, price_cents = ?, format = ?, isbn = ?, cover_image_url = ?, category = ?, stock_quantity = ?, status = ?, date_updated = ? WHERE id = ?",
            (product["title"], product["slug"], product["author"], product["description"], product["price_cents"], product["format"], product["isbn"], product["cover_image_url"], product["category"], product["stock_quantity"], product["status"], now_string(), product_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM store_products WHERE id = ?", (product_id,)).fetchone()
    except IntegrityError:
        conn.rollback()
        conn.close()
        return jsonify({"error": "A bookstore product with that slug already exists."}), 409
    conn.close()
    return jsonify({"success": True, "product": row_to_dict(row)})


@store_bp.route("/api/store/admin/products/<int:product_id>", methods=["DELETE"])
def admin_delete_product(product_id):
    blocked = admin_required()
    if blocked:
        return blocked
    conn = get_db()
    row = conn.execute("SELECT id FROM store_products WHERE id = ?", (product_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Book not found."}), 404
    conn.execute("UPDATE store_products SET status = 'archived', date_updated = ? WHERE id = ?", (now_string(), product_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})
