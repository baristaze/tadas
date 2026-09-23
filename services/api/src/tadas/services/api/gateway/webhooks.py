"""What an inbound delivery carries into a route: its body, byte for byte,
and the processor's signature header. The gateway reads both, and the
service checks the one against the other before anything is queued."""

from typing import Annotated

from fastapi import Depends, Header, Request

from tadas.services.api.services.billing import SignedDelivery


async def signed_delivery(
    request: Request,
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
) -> SignedDelivery:
    return SignedDelivery(payload=await request.body(), signature=stripe_signature)


StripeDelivery = Annotated[SignedDelivery, Depends(signed_delivery)]
