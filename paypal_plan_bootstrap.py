import logging
import os

from database import get_db
from paypal_subscriptions import create_monthly_plan, create_product, paypal_request

logger = logging.getLogger(__name__)
PLAN_KEY = "founding_3"
PLAN_ENV = "PAYPAL_PLAN_FOUNDING_3"
PLAN_DB_KEY = "paypal_founding_plan_id"
PRODUCT_DB_KEY = "paypal_membership_product_id"


def _site_value(conn, key):
    row = conn.execute("SELECT value FROM site_content WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""


def _save_site_value(conn, key, value):
    conn.execute(
        "INSERT INTO site_content(key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
        (key, value, "paypal-bootstrap"),
    )


def _verify_plan(plan_id):
    if not plan_id:
        return None
    return paypal_request("GET", f"/v1/billing/plans/{plan_id}")


def ensure_paypal_plan(app):
    """Ensure the Sandbox membership plan exists and is usable.

    Render's old PAYPAL_PLAN_FOUNDING_3 value was a stale plan ID. This
    bootstrap keeps a valid plan ID in the database so the checkout does not
    depend on manually replacing an environment variable every time a Sandbox
    plan is recreated.
    """
    if not os.environ.get("PAYPAL_CLIENT_ID", "").strip() or not os.environ.get("PAYPAL_CLIENT_SECRET", "").strip():
        logger.warning("PayPal plan bootstrap skipped: credentials are incomplete.")
        return ""

    conn = get_db()
    try:
        stored_plan = _site_value(conn, PLAN_DB_KEY).strip()
        configured_plan = os.environ.get(PLAN_ENV, "").strip()
        candidates = [stored_plan, configured_plan]

        for candidate in candidates:
            if not candidate:
                continue
            try:
                plan = _verify_plan(candidate)
                if str(plan.get("status", "")).upper() in {"ACTIVE", "CREATED"}:
                    if str(plan.get("status", "")).upper() == "CREATED":
                        try:
                            paypal_request("POST", f"/v1/billing/plans/{candidate}/activate", {})
                            plan = _verify_plan(candidate)
                        except Exception:
                            logger.exception("Could not activate PayPal membership plan %s", candidate)
                    os.environ[PLAN_ENV] = candidate
                    app.config["PAYPAL_PLAN_ID"] = candidate
                    _save_site_value(conn, PLAN_DB_KEY, candidate)
                    conn.commit()
                    logger.info("PayPal membership plan verified: plan_id=%s", candidate)
                    return candidate
            except Exception:
                logger.warning("Configured PayPal plan %s is unavailable; provisioning a replacement Sandbox plan.", candidate)

        product_id = _site_value(conn, PRODUCT_DB_KEY).strip()
        if product_id:
            try:
                paypal_request("GET", f"/v1/catalogs/products/{product_id}")
            except Exception:
                product_id = ""

        if not product_id:
            home_url = os.environ.get("PUBLIC_BASE_URL", "https://snyderscriptorium.onrender.com").strip().rstrip("/")
            product = create_product(f"{home_url}/kwsnyderwriting/membership")
            product_id = str(product.get("id") or "").strip()
            if not product_id:
                raise RuntimeError("PayPal did not return a product ID while creating the membership product.")
            _save_site_value(conn, PRODUCT_DB_KEY, product_id)

        plan = create_monthly_plan(product_id, PLAN_KEY)
        plan_id = str(plan.get("id") or "").strip()
        if not plan_id:
            raise RuntimeError("PayPal did not return a plan ID while creating the membership plan.")
        if str(plan.get("status", "")).upper() != "ACTIVE":
            try:
                paypal_request("POST", f"/v1/billing/plans/{plan_id}/activate", {})
            except Exception:
                logger.exception("New PayPal membership plan %s could not be activated.", plan_id)
        _save_site_value(conn, PLAN_DB_KEY, plan_id)
        conn.commit()
        os.environ[PLAN_ENV] = plan_id
        app.config["PAYPAL_PLAN_ID"] = plan_id
        logger.info("Created PayPal Sandbox membership plan: plan_id=%s product_id=%s", plan_id, product_id)
        return plan_id
    except Exception:
        conn.rollback()
        logger.exception("PayPal membership plan bootstrap failed.")
        return ""
    finally:
        conn.close()
