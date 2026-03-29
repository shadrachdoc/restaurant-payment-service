"""
triPOS Cloud client — sends sale transactions to a physical card terminal.

Worldpay triPOS Cloud API:
  Host: triposcert.vantiv.com (cert) / tripos.worldpay.com (prod)
  Endpoint: POST /api/v1/sale

Authentication: HMAC-SHA256 signature in tp-authorization header.
  HashKey = base64(HMAC-SHA256(requestBodyString, accountToken))
"""
import hashlib
import hmac
import base64
import json
import uuid
import time
import httpx

from app.core.config import settings


TRIPOS_HOSTS = {
    "cert": "https://triposcert.vantiv.com",
    "prod": "https://tripos.worldpay.com",
}


def _build_auth_header(body: str, acceptor_id: str, application_id: str, account_token: str) -> str:
    """Build tp-authorization header value with HMAC-SHA256 signature."""
    key = account_token.encode("utf-8")
    msg = body.encode("utf-8")
    hash_bytes = hmac.new(key, msg, hashlib.sha256).digest()
    hash_key = base64.b64encode(hash_bytes).decode("utf-8")
    return (
        f"Version=1.0,"
        f"AcceptorID={acceptor_id},"
        f"ApplicationID={application_id},"
        f"ApplicationVersion=1.0.0,"
        f"ApplicationName=RestaurantPOS,"
        f"HashKey={hash_key}"
    )


async def charge_card_terminal(
    amount: float,
    order_ref: str,
    lane_id: int,
    config: dict | None = None,
) -> dict:
    """
    Send a sale to the physical card terminal via triPOS Cloud.
    Uses per-restaurant config if provided, falls back to global settings.

    Blocks until customer taps/inserts card (up to 90 seconds).
    Returns the raw triPOS response dict.
    """
    if config:
        acceptor_id = config["acceptor_id"]
        account_id = config["account_id"]
        account_token = config["account_token"]
        application_id = config["application_id"]
        base_url = TRIPOS_HOSTS.get(config.get("environment", "cert"), TRIPOS_HOSTS["cert"])
    else:
        acceptor_id = settings.TRIPOS_ACCEPTOR_ID
        account_id = settings.TRIPOS_ACCOUNT_ID
        account_token = settings.TRIPOS_ACCOUNT_TOKEN
        application_id = settings.TRIPOS_APPLICATION_ID
        base_url = settings.TRIPOS_BASE_URL

    payload = {
        "laneId": lane_id,
        "transactionAmount": round(amount, 2),
        "marketCode": "Retail",
        "referenceNumber": (order_ref[:8] + str(int(time.time()))[-4:])[:12],
        "clerkNumber": "1",
        "ticketNumber": order_ref[:20],
    }
    body = json.dumps(payload, separators=(",", ":"))
    request_id = str(uuid.uuid4())

    headers = {
        "Content-Type": "application/json",
        "tp-application-id": application_id,
        "tp-application-name": "RestaurantPOS",
        "tp-application-version": "1.0.0",
        "tp-authorization": _build_auth_header(body, acceptor_id, application_id, account_token),
        "tp-express-acceptor-id": acceptor_id,
        "tp-express-account-id": account_id,
        "tp-express-account-token": account_token,
        "tp-request-id": request_id,
    }

    url = f"{base_url}/api/v1/sale"
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(url, headers=headers, content=body)
        response.raise_for_status()
        return response.json()


async def return_card_terminal(
    amount: float,
    order_ref: str,
    lane_id: int,
    config: dict | None = None,
) -> dict:
    """
    Send a return/refund to the physical card terminal via triPOS Cloud.
    Customer taps/inserts card to receive refund. Blocks up to 90 seconds.
    """
    if config:
        acceptor_id = config["acceptor_id"]
        account_id = config["account_id"]
        account_token = config["account_token"]
        application_id = config["application_id"]
        base_url = TRIPOS_HOSTS.get(config.get("environment", "cert"), TRIPOS_HOSTS["cert"])
    else:
        acceptor_id = settings.TRIPOS_ACCEPTOR_ID
        account_id = settings.TRIPOS_ACCOUNT_ID
        account_token = settings.TRIPOS_ACCOUNT_TOKEN
        application_id = settings.TRIPOS_APPLICATION_ID
        base_url = settings.TRIPOS_BASE_URL

    payload = {
        "laneId": lane_id,
        "transactionAmount": round(amount, 2),
        "referenceNumber": (order_ref[:8] + str(int(time.time()))[-4:])[:12],
        "clerkNumber": "1",
        "ticketNumber": order_ref[:20],
    }
    body = json.dumps(payload, separators=(",", ":"))
    request_id = str(uuid.uuid4())

    headers = {
        "Content-Type": "application/json",
        "tp-application-id": application_id,
        "tp-application-name": "RestaurantPOS",
        "tp-application-version": "1.0.0",
        "tp-authorization": _build_auth_header(body, acceptor_id, application_id, account_token),
        "tp-express-acceptor-id": acceptor_id,
        "tp-express-account-id": account_id,
        "tp-express-account-token": account_token,
        "tp-request-id": request_id,
    }

    url = f"{base_url}/api/v1/return"
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(url, headers=headers, content=body)
        response.raise_for_status()
        return response.json()
