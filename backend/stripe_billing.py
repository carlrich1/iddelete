"""Stripe billing integration.

Set ``STRIPE_SECRET_KEY``, ``STRIPE_PUBLIC_KEY``, and the three
``STRIPE_PRICE_*`` env vars to enable real subscriptions. Without them,
billing endpoints return a clear "billing not configured" response so the
rest of the product keeps working in development.

Webhook flow:
1. Frontend hits ``POST /api/billing/checkout`` -> we return a Stripe
   Checkout session URL the user is redirected to.
2. Stripe redirects back on success / cancel.
3. Stripe calls ``POST /api/billing/webhook`` with the
   ``checkout.session.completed`` event. We then mark the user as paid.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from flask import Blueprint, current_app, jsonify, request

from .auth import current_user, login_required
from .db import get_db, now

log = logging.getLogger(__name__)
bp = Blueprint("billing", __name__, url_prefix="/api/billing")


def _stripe():
    """Lazy import + configure stripe SDK. Returns the module, or None."""
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        return None
    try:
        import stripe
    except ImportError:
        log.warning("stripe SDK not installed (pip install stripe)")
        return None
    stripe.api_key = key
    return stripe


PRICE_BY_PLAN = {
    "personal": os.environ.get("STRIPE_PRICE_PERSONAL"),
    "family":   os.environ.get("STRIPE_PRICE_FAMILY"),
    "pro":      os.environ.get("STRIPE_PRICE_PRO"),
}


def _ensure_customer(stripe_mod, user_row) -> str:
    """Return a Stripe customer id, creating one if needed."""
    if user_row["stripe_customer_id"]:
        return user_row["stripe_customer_id"]
    c = stripe_mod.Customer.create(
        email=user_row["email"],
        name=user_row["name"] or None,
        metadata={"user_id": str(user_row["id"])},
    )
    db = get_db()
    db.execute("UPDATE users SET stripe_customer_id=?, updated_at=? WHERE id=?",
               (c.id, now(), user_row["id"]))
    db.commit()
    return c.id


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.get("/config")
def config():
    return jsonify(
        public_key=os.environ.get("STRIPE_PUBLIC_KEY", ""),
        configured=bool(os.environ.get("STRIPE_SECRET_KEY")),
        prices=PRICE_BY_PLAN,
    )


@bp.post("/checkout")
@login_required
def checkout():
    data = request.get_json(silent=True) or {}
    plan = data.get("plan", "family")
    stripe_mod = _stripe()
    if stripe_mod is None:
        return jsonify(error="billing_not_configured",
                       message="Set STRIPE_SECRET_KEY to enable real billing."), 503
    price = PRICE_BY_PLAN.get(plan)
    if not price:
        return jsonify(error="no_price_for_plan", plan=plan), 400

    from flask import g
    user = g.user
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    customer_id = _ensure_customer(stripe_mod, row)

    base = data.get("base_url") or request.host_url.rstrip("/")
    session = stripe_mod.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        payment_method_types=["card"],
        line_items=[{"price": price, "quantity": 1}],
        success_url=f"{base}/billing.html?status=success&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base}/billing.html?status=cancelled",
        client_reference_id=str(user["id"]),
        metadata={"plan": plan, "user_id": str(user["id"])},
    )
    return jsonify(url=session.url, id=session.id)


@bp.post("/portal")
@login_required
def portal():
    """Open Stripe's hosted customer portal for self-service billing."""
    stripe_mod = _stripe()
    if stripe_mod is None:
        return jsonify(error="billing_not_configured"), 503
    from flask import g
    user = g.user
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    customer_id = _ensure_customer(stripe_mod, row)
    base = request.host_url.rstrip("/")
    portal = stripe_mod.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{base}/billing.html",
    )
    return jsonify(url=portal.url)


@bp.post("/webhook")
def webhook():
    """Receive Stripe webhook events.

    Configure your endpoint to ``https://your-domain/api/billing/webhook``
    in the Stripe Dashboard and set ``STRIPE_WEBHOOK_SECRET`` so we can
    verify the signature.
    """
    stripe_mod = _stripe()
    if stripe_mod is None:
        return "billing_not_configured", 503

    payload = request.data
    sig = request.headers.get("Stripe-Signature", "")
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    try:
        if secret:
            event = stripe_mod.Webhook.construct_event(payload, sig, secret)
        else:
            event = json.loads(payload.decode())
    except Exception as e:
        log.warning("Invalid webhook: %s", e)
        return "bad_signature", 400

    etype = event.get("type") if isinstance(event, dict) else event["type"]
    data = event["data"]["object"] if isinstance(event, dict) else event.data.object

    db = get_db()
    if etype == "checkout.session.completed":
        user_id = int((data.get("client_reference_id")
                       or data.get("metadata", {}).get("user_id") or 0))
        plan = (data.get("metadata") or {}).get("plan")
        sub_id = data.get("subscription")
        if user_id:
            db.execute(
                """UPDATE users SET stripe_subscription_id=?, subscription_status='active',
                                    plan=COALESCE(?, plan), updated_at=? WHERE id=?""",
                (sub_id, plan, now(), user_id),
            )
            db.commit()
    elif etype in ("customer.subscription.deleted",
                   "customer.subscription.paused",
                   "customer.subscription.updated"):
        sub_id = data.get("id")
        status = data.get("status", "canceled")
        db.execute("UPDATE users SET subscription_status=?, updated_at=? WHERE stripe_subscription_id=?",
                   (status, now(), sub_id))
        db.commit()
    return "", 200
