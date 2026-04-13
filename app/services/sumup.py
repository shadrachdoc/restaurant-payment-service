"""
SumUp Payment Integration
Uses SumUp Checkout API to create hosted payment pages for card orders
"""
import httpx
import uuid
import logging
from typing import Optional

logger = logging.getLogger(__name__)

SUMUP_API_BASE = "https://api.sumup.com"


async def create_checkout(
    api_key: str,
    merchant_code: str,
    amount: float,
    currency: str,
    order_id: str,
    description: str,
    return_url: Optional[str] = None,
) -> dict:
    """
    Create a SumUp checkout (hosted payment page).
    Returns checkout id + checkout_url for the customer to pay.
    """
    reference = f"ORDER-{order_id[:8].upper()}-{uuid.uuid4().hex[:6].upper()}"

    payload = {
        "checkout_reference": reference,
        "amount": round(amount, 2),
        "currency": currency.upper(),
        "merchant_code": merchant_code,
        "description": description,
    }
    if return_url:
        payload["return_url"] = return_url

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{SUMUP_API_BASE}/v0.1/checkouts",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    if resp.status_code not in (200, 201):
        logger.error(f"SumUp checkout creation failed: {resp.status_code} {resp.text}")
        raise Exception(f"SumUp error: {resp.text}")

    data = resp.json()
    checkout_id = data.get("id")
    checkout_url = f"https://testenv.corpv3.com/pay/{checkout_id}" if checkout_id else None

    logger.info(f"SumUp checkout created: ref={reference} id={checkout_id} amount={amount}{currency}")
    return {
        "checkout_id": checkout_id,
        "checkout_reference": reference,
        "checkout_url": checkout_url,
        "amount": amount,
        "currency": currency,
        "status": data.get("status", "PENDING"),
    }


async def get_checkout_status(api_key: str, checkout_id: str) -> dict:
    """Poll SumUp for checkout payment status."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{SUMUP_API_BASE}/v0.1/checkouts/{checkout_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )

    if resp.status_code != 200:
        raise Exception(f"SumUp status error: {resp.text}")

    data = resp.json()
    status = data.get("status", "UNKNOWN")  # PENDING | PAID | FAILED
    transactions = data.get("transactions", [])
    last_tx = transactions[-1] if transactions else {}

    return {
        "checkout_id": checkout_id,
        "status": status,
        "paid": status == "PAID",
        "transaction_id": last_tx.get("id"),
        "card_last_four": last_tx.get("card", {}).get("last_4_digits"),
        "card_brand": last_tx.get("card", {}).get("type"),
    }
