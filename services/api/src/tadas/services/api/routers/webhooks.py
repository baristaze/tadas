"""Inbound deliveries from the payment processor, outside /v1: the version
of their shape is the processor's, pinned on the endpoint. The route takes
no credential; it is authenticated by the processor's signature over the
body and its timestamp, checked before anything is queued, and a worker
applies what the delivery means."""

from fastapi import APIRouter

from tadas.services.api.gateway.resolve import WebhooksService
from tadas.services.api.gateway.webhooks import StripeDelivery
from tadas.services.api.types.billing import DeliveryReceivedView

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe", response_model=DeliveryReceivedView)
async def stripe_delivery(
    webhooks: WebhooksService, delivery: StripeDelivery
) -> DeliveryReceivedView:
    return await webhooks.receive_stripe(delivery)
