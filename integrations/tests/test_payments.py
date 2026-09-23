"""The payments integration without an account: the signature check every
delivery passes, the ids a delivery names, the twin's refusal outside a
local environment, the boot's refusal of a key whose mode is not the
environment's, and the real client's reading of a subscription."""

import json
import time
from datetime import timedelta
from uuid import uuid4

import pytest
import stripe

from tadas.integrations.exceptions import (
    DeliveryRefused,
    PaymentsUnconfigured,
    UnsafeProviderConfiguration,
)
from tadas.integrations.payments.deliveries import delivery_of, sign, verified
from tadas.integrations.payments.stripe import PaymentsStripeImpl, subscription_of
from tadas.integrations.payments.twin import TWIN_WEBHOOK_SECRET, PaymentsTwinImpl
from tadas.integrations.payments.types import ORG_METADATA_KEY, delivery_key
from tadas.integrations.settings import (
    IntegrationsSettings,
    build_payments,
    key_mode,
    refuse_unsafe_payments,
)

SECRET = "whsec_test_only"


def event(event_type: str, obj: dict[str, object], event_id: str = "evt_1") -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "object": "event",
            "type": event_type,
            "created": int(time.time()),
            "livemode": False,
            "data": {"object": obj},
        }
    ).encode()


def settings(**fields: object) -> IntegrationsSettings:
    return IntegrationsSettings.model_validate({"_env_file": None, **fields})


# The signature.


def test_a_delivery_signed_with_the_secret_checks_out() -> None:
    org = uuid4()
    payload = event(
        "customer.subscription.updated",
        {"id": "sub_1", "customer": "cus_1", "metadata": {ORG_METADATA_KEY: str(org)}},
    )
    delivery = verified(payload, sign(payload, SECRET), SECRET)
    assert (delivery.event_id, delivery.event_type) == ("evt_1", "customer.subscription.updated")
    assert (delivery.customer_id, delivery.subscription_id, delivery.org_hint) == (
        "cus_1",
        "sub_1",
        org,
    )
    assert delivery.idempotency_key == delivery_key("evt_1")


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "t=1,v1=00",
        sign(b"another body", SECRET),
        sign(event("invoice.paid", {}), "whsec_someone_else"),
    ],
)
def test_a_delivery_that_does_not_check_out_is_refused(header: str | None) -> None:
    payload = event("invoice.paid", {})
    with pytest.raises(DeliveryRefused) as refused:
        verified(payload, header, SECRET)
    assert refused.value.http_status == 400
    assert refused.value.code == "webhook_signature_invalid"
    assert SECRET not in refused.value.message


def test_a_delivery_outside_the_replay_window_is_refused() -> None:
    payload = event("invoice.paid", {})
    stale = sign(payload, SECRET, int(time.time()) - 3600)
    with pytest.raises(DeliveryRefused):
        verified(payload, stale, SECRET)


def test_a_signed_body_that_is_not_an_event_is_refused() -> None:
    for payload in (b"[]", b"not json", json.dumps({"id": "evt"}).encode()):
        with pytest.raises(DeliveryRefused):
            verified(payload, sign(payload, SECRET), SECRET)


# The ids a delivery names.


def test_a_checkout_names_the_org_by_its_client_reference() -> None:
    org = uuid4()
    raw = json.loads(
        event(
            "checkout.session.completed",
            {"customer": "cus_1", "subscription": "sub_1", "client_reference_id": str(org)},
        )
    )
    delivery = delivery_of(raw)
    assert (delivery.customer_id, delivery.subscription_id, delivery.org_hint) == (
        "cus_1",
        "sub_1",
        org,
    )


def test_an_invoice_names_its_subscription_where_the_pinned_version_puts_it() -> None:
    org = uuid4()
    raw = json.loads(
        event(
            "invoice.payment_failed",
            {
                "customer": {"id": "cus_1"},
                "parent": {
                    "subscription_details": {
                        "subscription": "sub_1",
                        "metadata": {ORG_METADATA_KEY: str(org)},
                    }
                },
            },
        )
    )
    delivery = delivery_of(raw)
    assert (delivery.customer_id, delivery.subscription_id, delivery.org_hint) == (
        "cus_1",
        "sub_1",
        org,
    )
    older = delivery_of(json.loads(event("invoice.paid", {"subscription": "sub_2"})))
    assert older.subscription_id == "sub_2" and older.org_hint is None


def test_an_event_of_another_type_names_nothing_but_itself() -> None:
    delivery = delivery_of(json.loads(event("product.created", {"id": "prod_1"})))
    assert (delivery.customer_id, delivery.subscription_id, delivery.org_hint) == (
        None,
        None,
        None,
    )


# The twin.


def test_the_twin_refuses_to_run_outside_a_local_environment() -> None:
    for environment in ("dev", "staging", "production"):
        with pytest.raises(UnsafeProviderConfiguration):
            PaymentsTwinImpl(environment=environment)
        with pytest.raises(UnsafeProviderConfiguration):
            build_payments(settings(environment=environment, billing_backend="twin"))
    assert build_payments(settings(environment="test")).describe() == "payments=twin"


async def test_the_twins_deliveries_pass_the_check_the_real_ones_do() -> None:
    twin = PaymentsTwinImpl(environment="test")
    org = uuid4()
    customer = await twin.create_customer(org, "Acme")
    assert await twin.create_customer(org, "Acme") == customer
    url = await twin.create_checkout(
        customer_id=customer,
        org_id=org,
        lookup_key="tadas.pro.monthly",
        quantity=1,
        success_url="http://portal.test/done",
        cancel_url="http://portal.test/cancelled",
    )
    payload, header = twin.complete_checkout(url)
    delivery = verified(payload, header, TWIN_WEBHOOK_SECRET)
    assert delivery.org_hint == org and delivery.customer_id == customer
    assert delivery.subscription_id is not None
    subscription = await twin.read_subscription(delivery.subscription_id)
    assert subscription is not None and subscription.status == "active"
    assert await twin.read_customer_org(customer) == org


# The boot's refusals.


@pytest.mark.parametrize(
    ("key", "mode"),
    [
        ("sk_live_x", "live"),
        ("rk_live_x", "live"),
        ("sk_org_live_x", "live"),
        ("sk_test_x", "test"),
        ("rk_test_x", "test"),
        ("sk_org_test_x", "test"),
        ("pk_test_x", None),
    ],
)
def test_a_keys_prefix_says_its_mode(key: str, mode: str | None) -> None:
    assert key_mode(key) == mode


@pytest.mark.parametrize(
    ("environment", "key", "refused"),
    [
        ("production", "sk_live_x", False),
        ("production", "rk_test_x", True),
        ("staging", "rk_test_x", False),
        ("staging", "sk_live_x", True),
        ("local", "sk_live_x", True),
        ("local", "sk_org_test_x", False),
        ("staging", "pk_test_x", True),
    ],
)
def test_a_key_whose_mode_is_not_the_environments_is_refused_at_boot(
    environment: str, key: str, refused: bool
) -> None:
    configured = settings(environment=environment, billing_backend="stripe", stripe_org_key=key)
    if refused:
        with pytest.raises(UnsafeProviderConfiguration) as refusal:
            refuse_unsafe_payments(configured)
        assert key not in refusal.value.message
    else:
        refuse_unsafe_payments(configured)


async def test_no_key_leaves_billing_unconfigured_and_every_call_says_so() -> None:
    for off in (None, "", "off"):
        payments = build_payments(
            settings(environment="staging", billing_backend="stripe", stripe_org_key=off)
        )
        await payments.start()
        assert payments.configured is False
        with pytest.raises(PaymentsUnconfigured) as refused:
            await payments.create_customer(uuid4(), "Acme")
        assert refused.value.http_status == 503
        with pytest.raises(PaymentsUnconfigured):
            payments.verify_delivery(b"{}", "t=1,v1=00")
        await payments.close()


async def test_the_real_client_names_the_account_and_the_pinned_version() -> None:
    payments = PaymentsStripeImpl(
        api_key="rk_test_x",
        account_id="acct_test",
        webhook_secret=SECRET,
        timeout=timedelta(seconds=3),
    )
    await payments.start()
    try:
        assert payments.describe().startswith("payments=stripe (acct_test, ")
        client = payments._client  # the SDK's own, read to see what every call names
        assert client is not None
        options = client._requestor._options
        assert options.stripe_context == "acct_test"
        assert options.stripe_version == stripe.api_version
    finally:
        await payments.close()


def test_a_subscription_is_read_from_the_item_where_the_period_now_sits() -> None:
    org = uuid4()
    read = subscription_of(
        {
            "id": "sub_1",
            "customer": "cus_1",
            "status": "active",
            "cancel_at_period_end": True,
            "metadata": {ORG_METADATA_KEY: str(org)},
            "items": {
                "data": [
                    {
                        "id": "si_1",
                        "quantity": 11,
                        "current_period_end": 1_900_000_000,
                        "price": {"lookup_key": "tadas.max.monthly"},
                    }
                ]
            },
        }
    )
    assert (read.price_lookup_key, read.quantity, read.cancel_at_period_end) == (
        "tadas.max.monthly",
        11,
        True,
    )
    assert read.current_period_end is not None and read.org_id == org
