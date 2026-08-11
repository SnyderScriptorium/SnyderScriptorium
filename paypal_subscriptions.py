"""PayPal Subscriptions integration foundation and server-side helpers.

Credentials are read only from environment variables.
"""

import os
from datetime import datetime, timezone

import requests

PRODUCT_NAME = "K. W. Snyder Writing Membership"
PRODUCT_DESCRIPTION = "Monthly membership providing access to the private K. W. Snyder Writing library."

PLAN_CONFIG = {
    "founding_3": {"price": "3.00", "currency": "USD", "label": "Founding Member — $3/month"},
    "standard_4": {"price": "4.00", "currency": "USD", "label": "Member — $4/month"},
    "standard_5": {"price": "5.00", "currency": "USD", "label": "Member — $5/month"},
}


def paypal_base_url():
    return "https://api-m.sandbox.paypal.com" if os.environ.get("PAYPAL_ENV", "sandbox").lower() != "live" else "https://api-m.paypal.com"


def paypal_credentials_present():
    return bool(os.environ.get("PAYPAL_CLIENT_ID") and os.environ.get("PAYPAL_CLIENT_SECRET"))


def get_access_token():
    if not paypal_credentials_present():
        raise RuntimeError("PayPal credentials are not configured.")
    response = requests.post(
        f"{paypal_base_url()}/v1/oauth2/token",
        auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json", "Accept-Language": "en_US"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def paypal_request(method, path, payload=None, headers=None):
    token = get_access_token()
    request_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    response = requests.request(method, f"{paypal_base_url()}{path}", json=payload, headers=request_headers, timeout=20)
    response.raise_for_status()
    return response.json() if response.content else {}


def get_subscription(subscription_id):
    return paypal_request("GET", f"/v1/billing/subscriptions/{subscription_id}")


def verify_webhook(headers, webhook_event):
    webhook_id = os.environ.get("PAYPAL_WEBHOOK_ID", "").strip()
    required = [
        "PAYPAL-TRANSMISSION-ID",
        "PAYPAL-TRANSMISSION-TIME",
        "PAYPAL-CERT-URL",
        "PAYPAL-AUTH-ALGO",
        "PAYPAL-TRANSMISSION-SIG",
    ]
    if not webhook_id or any(not headers.get(name) for name in required):
        return False
    payload = {
        "transmission_id": headers["PAYPAL-TRANSMISSION-ID"],
        "transmission_time": headers["PAYPAL-TRANSMISSION-TIME"],
        "cert_url": headers["PAYPAL-CERT-URL"],
        "auth_algo": headers["PAYPAL-AUTH-ALGO"],
        "transmission_sig": headers["PAYPAL-TRANSMISSION-SIG"],
        "webhook_id": webhook_id,
        "webhook_event": webhook_event,
    }
    try:
        result = paypal_request("POST", "/v1/notifications/verify-webhook-signature", payload)
        return result.get("verification_status") == "SUCCESS"
    except Exception:
        return False


def create_product(home_url):
    return paypal_request(
        "POST", "/v1/catalogs/products",
        {"name": PRODUCT_NAME, "description": PRODUCT_DESCRIPTION, "type": "SERVICE", "category": "SOFTWARE", "home_url": home_url},
        {"PayPal-Request-Id": f"snyder-product-{int(datetime.now(timezone.utc).timestamp())}"},
    )


def create_monthly_plan(product_id, plan_key):
    if plan_key not in PLAN_CONFIG:
        raise ValueError(f"Unknown plan key: {plan_key}")
    cfg = PLAN_CONFIG[plan_key]
    return paypal_request(
        "POST", "/v1/billing/plans",
        {
            "product_id": product_id,
            "name": cfg["label"],
            "description": cfg["label"],
            "billing_cycles": [{"frequency": {"interval_unit": "MONTH", "interval_count": 1}, "tenure_type": "REGULAR", "sequence": 1, "total_cycles": 0, "pricing_scheme": {"fixed_price": {"value": cfg["price"], "currency_code": cfg["currency"]}}}],
            "payment_preferences": {"auto_bill_outstanding": True, "payment_failure_threshold": 2},
        },
        {"PayPal-Request-Id": f"snyder-plan-{plan_key}-{int(datetime.now(timezone.utc).timestamp())}"},
    )


def plan_id(plan_key):
    env_name = {"founding_3": "PAYPAL_PLAN_FOUNDING_3", "standard_4": "PAYPAL_PLAN_STANDARD_4", "standard_5": "PAYPAL_PLAN_STANDARD_5"}.get(plan_key)
    if not env_name:
        raise ValueError(f"Unknown plan key: {plan_key}")
    return os.environ.get(env_name, "").strip()


def subscription_status_accessible(status):
    return status == "active"


def subscription_event_to_status(event_type):
    return {
        "BILLING.SUBSCRIPTION.ACTIVATED": "active",
        "PAYMENT.SALE.COMPLETED": "active",
        "BILLING.SUBSCRIPTION.UPDATED": "active",
        "BILLING.SUBSCRIPTION.PAYMENT.FAILED": "past_due",
        "BILLING.SUBSCRIPTION.SUSPENDED": "paused",
        "BILLING.SUBSCRIPTION.CANCELLED": "cancelled",
        "BILLING.SUBSCRIPTION.EXPIRED": "expired",
    }.get(event_type)
