"""What an inbound delivery carries into a route: its body, byte for byte,
and the provider's signature header. The gateway reads them, and the
service checks the one against the other before anything is queued."""

from typing import Annotated

from fastapi import Depends, Header, Request

from tadas.integrations.identity.deliveries import SIGNATURE_HEADER
from tadas.services.api.services.slack import SlackRequest
from tadas.services.api.services.webhooks import SignedDelivery


async def identity_delivery(
    request: Request,
    signature: Annotated[str | None, Header(alias=SIGNATURE_HEADER)] = None,
) -> SignedDelivery:
    return SignedDelivery(payload=await request.body(), signature=signature)


async def stripe_delivery(
    request: Request,
    signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
) -> SignedDelivery:
    return SignedDelivery(payload=await request.body(), signature=signature)


async def slack_request(
    request: Request,
    timestamp: Annotated[str | None, Header(alias="X-Slack-Request-Timestamp")] = None,
    signature: Annotated[str | None, Header(alias="X-Slack-Signature")] = None,
    retry_num: Annotated[str | None, Header(alias="X-Slack-Retry-Num")] = None,
) -> SlackRequest:
    return SlackRequest(
        payload=await request.body(),
        timestamp=timestamp,
        signature=signature,
        retry_num=retry_number(retry_num),
    )


def retry_number(header: str | None) -> int:
    """Which of Slack's retries a call is, from `X-Slack-Retry-Num`: 0 for the
    first call, and for a header that is no number. It is read before the
    signature is checked, so it is whatever a caller wrote. A number is ASCII
    digits alone: `isdigit` admits the digits of every script, some of which
    `int` refuses, and `int` reads a number only up to its digit limit."""
    if header is None or not (header.isascii() and header.isdigit()):
        return 0
    try:
        return int(header)
    except ValueError:
        return 0


IdentityDelivery = Annotated[SignedDelivery, Depends(identity_delivery)]
StripeDelivery = Annotated[SignedDelivery, Depends(stripe_delivery)]
SlackCall = Annotated[SlackRequest, Depends(slack_request)]
