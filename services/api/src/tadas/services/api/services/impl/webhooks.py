import json

from tadas.infra.queues import Queues, QueuesInterface
from tadas.integrations.identity import IdentityProviderInterface
from tadas.integrations.payments import PaymentsInterface
from tadas.om.context import RequestContext
from tadas.services.api.services.webhooks import SignedDelivery, WebhooksServiceInterface
from tadas.services.api.types.webhooks import DeliveryReceivedView


class WebhooksServiceImpl(WebhooksServiceInterface):
    """The edge of an outside producer: the check, then the queue. What the
    delivery means is the worker's to apply, under the org it names."""

    def __init__(
        self,
        identity: IdentityProviderInterface,
        payments: PaymentsInterface,
        queues: QueuesInterface,
    ) -> None:
        self._identity = identity
        self._payments = payments
        self._queues = queues

    async def receive_identity(
        self, rctx: RequestContext, delivery: SignedDelivery
    ) -> DeliveryReceivedView:
        verified = self._identity.verify_delivery(delivery.payload, delivery.signature)
        body = {
            "idempotency_key": str(verified.key),
            "provider": "identity",
            "delivery": verified.model_dump(mode="json"),
        }
        await self._queues.send(
            Queues.WEBHOOKS, json.dumps(body).encode("utf-8"), deadline=rctx.deadline
        )
        return DeliveryReceivedView(received=True)

    async def receive_stripe(
        self, rctx: RequestContext, delivery: SignedDelivery
    ) -> DeliveryReceivedView:
        verified = self._payments.verify_delivery(delivery.payload, delivery.signature)
        body = {
            "idempotency_key": str(verified.idempotency_key),
            "provider": "stripe",
            "delivery": verified.model_dump(mode="json"),
        }
        await self._queues.send(
            Queues.WEBHOOKS, json.dumps(body).encode("utf-8"), deadline=rctx.deadline
        )
        return DeliveryReceivedView(received=True)
