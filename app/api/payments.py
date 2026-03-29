from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from pydantic import BaseModel
from enum import Enum
from datetime import datetime
import uuid
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class PaymentMethod(str, Enum):
    CASH = "cash"
    CARD = "card"
    GIFT_CARD = "gift_card"
    VOUCHER = "voucher"


class PaymentGateway(str, Enum):
    STRIPE = "stripe"
    SUMUP = "sumup"
    ZETTLE = "zettle"
    SQUARE = "square"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class PaymentRequest(BaseModel):
    order_id: str
    amount: float
    currency: str = "GBP"
    method: PaymentMethod
    gateway: Optional[PaymentGateway] = None
    tip_amount: float = 0
    metadata: Optional[dict] = None


class PaymentResponse(BaseModel):
    id: str
    order_id: str
    amount: float
    currency: str
    method: PaymentMethod
    gateway: Optional[PaymentGateway]
    status: PaymentStatus
    transaction_id: Optional[str]
    card_last_four: Optional[str]
    card_brand: Optional[str]
    receipt_url: Optional[str]
    created_at: datetime


@router.post("/process", response_model=PaymentResponse)
async def process_payment(payment: PaymentRequest):
    """Process a payment through the specified gateway"""
    payment_id = str(uuid.uuid4())

    # For cash payments, complete immediately
    if payment.method == PaymentMethod.CASH:
        return PaymentResponse(
            id=payment_id,
            order_id=payment.order_id,
            amount=payment.amount + payment.tip_amount,
            currency=payment.currency,
            method=payment.method,
            gateway=None,
            status=PaymentStatus.COMPLETED,
            transaction_id=f"CASH-{payment_id[:8]}",
            card_last_four=None,
            card_brand=None,
            receipt_url=None,
            created_at=datetime.utcnow()
        )

    # For card payments, process through gateway
    if payment.method == PaymentMethod.CARD:
        if not payment.gateway:
            payment.gateway = PaymentGateway.STRIPE  # Default gateway

        # Process through appropriate gateway
        if payment.gateway == PaymentGateway.STRIPE:
            return await process_stripe_payment(payment_id, payment)
        elif payment.gateway == PaymentGateway.SUMUP:
            return await process_sumup_payment(payment_id, payment)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported gateway: {payment.gateway}")

    raise HTTPException(status_code=400, detail=f"Unsupported payment method: {payment.method}")


async def process_stripe_payment(payment_id: str, payment: PaymentRequest) -> PaymentResponse:
    """Process payment through Stripe Terminal"""
    # TODO: Implement actual Stripe Terminal integration
    # For now, return a mock successful response
    return PaymentResponse(
        id=payment_id,
        order_id=payment.order_id,
        amount=payment.amount + payment.tip_amount,
        currency=payment.currency,
        method=payment.method,
        gateway=PaymentGateway.STRIPE,
        status=PaymentStatus.COMPLETED,
        transaction_id=f"pi_{payment_id[:16]}",
        card_last_four="4242",
        card_brand="visa",
        receipt_url=f"https://pay.stripe.com/receipts/{payment_id}",
        created_at=datetime.utcnow()
    )


async def process_sumup_payment(payment_id: str, payment: PaymentRequest) -> PaymentResponse:
    """Process payment through SumUp"""
    # TODO: Implement actual SumUp integration
    return PaymentResponse(
        id=payment_id,
        order_id=payment.order_id,
        amount=payment.amount + payment.tip_amount,
        currency=payment.currency,
        method=payment.method,
        gateway=PaymentGateway.SUMUP,
        status=PaymentStatus.COMPLETED,
        transaction_id=f"SU-{payment_id[:12]}",
        card_last_four="1234",
        card_brand="mastercard",
        receipt_url=None,
        created_at=datetime.utcnow()
    )


class CardTerminalRequest(BaseModel):
    restaurant_id: str
    order_id: str
    amount: float
    lane_id: int


class CardTerminalResponse(BaseModel):
    approved: bool
    transaction_id: Optional[str]
    card_brand: Optional[str]
    card_last_four: Optional[str]
    message: str


async def _get_restaurant_payment_config(restaurant_id: str) -> dict:
    """Fetch payment config for a restaurant from restaurant-service."""
    import httpx
    from app.core.config import settings
    url = f"{settings.API_GATEWAY_URL}/api/v1/restaurants/{restaurant_id}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail="Could not fetch restaurant payment config")
        return r.json()


@router.post("/card-terminal", response_model=CardTerminalResponse)
async def charge_card_terminal(request: CardTerminalRequest):
    """Charge a physical card terminal via triPOS Cloud using the restaurant's own credentials."""
    from app.services.tripos import charge_card_terminal as tripos_charge

    restaurant = await _get_restaurant_payment_config(request.restaurant_id)

    if not restaurant.get("tripos_enabled"):
        raise HTTPException(status_code=400, detail="Worldpay triPOS is not enabled for this restaurant")

    tripos_config = {
        "acceptor_id": restaurant.get("tripos_acceptor_id"),
        "account_id": restaurant.get("tripos_account_id"),
        "account_token": restaurant.get("tripos_account_token"),
        "application_id": restaurant.get("tripos_application_id"),
        "environment": restaurant.get("tripos_environment", "cert"),
    }
    if not all([tripos_config["acceptor_id"], tripos_config["account_id"],
                tripos_config["account_token"], tripos_config["application_id"]]):
        raise HTTPException(status_code=400, detail="Worldpay triPOS credentials are incomplete")

    try:
        result = await tripos_charge(
            amount=request.amount,
            order_ref=request.order_id,
            lane_id=request.lane_id,
            config=tripos_config,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Terminal error: {str(e)}")

    logger.info("triPOS response: %s", result)
    status_val = result.get("_statusCode") or result.get("statusCode", "")
    approved = str(status_val).lower() == "approved"

    card = result.get("card") or {}
    return CardTerminalResponse(
        approved=approved,
        transaction_id=result.get("transactionId"),
        card_brand=card.get("type") or result.get("cardType"),
        card_last_four=card.get("last4") or result.get("maskedPan", "")[-4:] or None,
        message=result.get("statusMessage") or status_val or "Unknown",
    )


class CardRefundRequest(BaseModel):
    restaurant_id: str
    order_id: str
    amount: float
    lane_id: int


@router.post("/card-refund", response_model=CardTerminalResponse)
async def refund_card_terminal(request: CardRefundRequest):
    """Send a return/refund to the physical card terminal via triPOS Cloud. Customer taps card."""
    from app.services.tripos import return_card_terminal as tripos_return

    restaurant = await _get_restaurant_payment_config(request.restaurant_id)

    if not restaurant.get("tripos_enabled"):
        raise HTTPException(status_code=400, detail="Worldpay triPOS is not enabled for this restaurant")

    tripos_config = {
        "acceptor_id": restaurant.get("tripos_acceptor_id"),
        "account_id": restaurant.get("tripos_account_id"),
        "account_token": restaurant.get("tripos_account_token"),
        "application_id": restaurant.get("tripos_application_id"),
        "environment": restaurant.get("tripos_environment", "cert"),
    }
    if not all([tripos_config["acceptor_id"], tripos_config["account_id"],
                tripos_config["account_token"], tripos_config["application_id"]]):
        raise HTTPException(status_code=400, detail="Worldpay triPOS credentials are incomplete")

    try:
        result = await tripos_return(
            amount=request.amount,
            order_ref=request.order_id,
            lane_id=request.lane_id,
            config=tripos_config,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Terminal error: {str(e)}")

    logger.info("triPOS refund response: %s", result)
    status_val = result.get("_statusCode") or result.get("statusCode", "")
    approved = str(status_val).lower() == "approved"

    card = result.get("card") or {}
    return CardTerminalResponse(
        approved=approved,
        transaction_id=result.get("transactionId"),
        card_brand=card.get("type") or result.get("cardType"),
        card_last_four=card.get("last4") or result.get("maskedPan", "")[-4:] or None,
        message=result.get("statusMessage") or status_val or "Unknown",
    )


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(payment_id: str):
    """Get payment details by ID"""
    # TODO: Fetch from database
    raise HTTPException(status_code=404, detail="Payment not found")


@router.get("/order/{order_id}")
async def get_payments_by_order(order_id: str):
    """Get all payments for an order"""
    # TODO: Fetch from database
    return []


@router.post("/{payment_id}/capture")
async def capture_payment(payment_id: str):
    """Capture a pre-authorized payment"""
    # TODO: Implement capture logic
    return {"status": "captured", "payment_id": payment_id}
