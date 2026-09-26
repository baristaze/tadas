"""The payments integration without an account: the signature check every
delivery passes, the ids a delivery names, the twin's refusal outside a
local environment, the boot's refusal of a key that is not a restricted key
of the environment's mode, the processes
reading the runtime key alone, the boot's check of what the key may read,
and the real client's reading of a subscription."""

import json
import logging
import time
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
import stripe

from tadas.integrations.exceptions import (
    DeliveryRefused,
    PaymentsRefused,
    PaymentsUnconfigured,
    ProviderUnavailable,
    UnsafeIntegration,
)
from tadas.integrations.impl.configured import payments_for, refuse_unsafe_payments
from tadas.integrations.payments.deliveries import delivery_of, sign, verified
from tadas.integrations.payments.permissions import CHECKOUT_SESSIONS, RUNTIME_PERMISSIONS
from tadas.integrations.payments.stripe import PaymentsStripeImpl, subscription_of
from tadas.integrations.payments.twin import TWIN_WEBHOOK_SECRET, PaymentsTwinImpl
from tadas.integrations.payments.types import ORG_METADATA_KEY, delivery_key
from tadas.integrations.settings import IntegrationsSettings, key_mode

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
        with pytest.raises(UnsafeIntegration):
            PaymentsTwinImpl(environment=environment)
        with pytest.raises(UnsafeIntegration):
            payments_for(settings(billing_backend="twin"), environment)
    assert payments_for(settings(billing_backend="twin"), "test").describe() == "payments=twin"


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
        ("production", "rk_live_x", False),
        ("production", "rk_test_x", True),
        ("staging", "rk_test_x", False),
        ("staging", "rk_live_x", True),
        ("local", "rk_live_x", True),
        ("local", "rk_test_x", False),
        ("staging", "pk_test_x", True),
    ],
)
def test_a_key_whose_mode_is_not_the_environments_is_refused_at_boot(
    environment: str, key: str, refused: bool
) -> None:
    configured = settings(billing_backend="stripe", stripe_runtime_key=key)
    if refused:
        with pytest.raises(UnsafeIntegration) as refusal:
            refuse_unsafe_payments(configured, environment)
        assert key not in refusal.value.message
        assert "TADAS_STRIPE_RUNTIME_KEY" in refusal.value.message
    else:
        refuse_unsafe_payments(configured, environment)


@pytest.mark.parametrize(
    ("environment", "key", "said"),
    [
        ("staging", "rk_org_test_x", "organization key"),
        ("staging", "sk_org_test_x", "organization key"),
        ("production", "sk_org_live_x", "organization key"),
        ("staging", "sk_test_x", "secret key"),
        ("production", "sk_live_x", "secret key"),
    ],
)
def test_only_a_restricted_key_of_the_account_is_taken_at_boot(
    environment: str, key: str, said: str
) -> None:
    """An organization key reaches every account, and a secret key may do
    everything in one; the processes take a restricted key alone."""
    configured = settings(billing_backend="stripe", stripe_runtime_key=key)
    with pytest.raises(UnsafeIntegration) as refusal:
        refuse_unsafe_payments(configured, environment)
    assert said in refusal.value.message
    assert key not in refusal.value.message


def test_the_processes_read_the_runtime_key_and_never_the_bootstraps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TADAS_STRIPE_BOOTSTRAP_KEY", "rk_test_bootstrap")
    monkeypatch.delenv("TADAS_STRIPE_RUNTIME_KEY", raising=False)
    alone = IntegrationsSettings.model_validate(
        {"_env_file": None, "stripe_account_id": "acct_test"}
    )
    assert alone.stripe_runtime_key is None
    assert payments_for(alone, "staging").configured is False
    assert "rk_test_bootstrap" not in repr(alone.model_dump())
    monkeypatch.setenv("TADAS_STRIPE_RUNTIME_KEY", "rk_test_runtime")
    both = IntegrationsSettings.model_validate(
        {"_env_file": None, "stripe_account_id": "acct_test"}
    )
    assert both.stripe_runtime_key is not None
    assert both.stripe_runtime_key.get_secret_value() == "rk_test_runtime"
    assert payments_for(both, "staging").configured is True


async def test_no_key_leaves_billing_unconfigured_and_every_call_says_so() -> None:
    for off in (None, "", "off"):
        payments = payments_for(
            settings(billing_backend="stripe", stripe_runtime_key=off), "staging"
        )
        await payments.start()
        assert payments.configured is False
        with pytest.raises(PaymentsUnconfigured) as refused:
            await payments.create_customer(uuid4(), "Acme")
        assert refused.value.http_status == 503
        with pytest.raises(PaymentsUnconfigured):
            payments.verify_delivery(b"{}", "t=1,v1=00")
        await payments.close()


# The boot's check of what the key may read.


class _Lister:
    def __init__(self, name: str, refused: set[str], error: type[Exception]) -> None:
        self._name = name
        self._refused = refused
        self._error = error
        self.params: list[dict[str, Any]] = []

    async def list_async(self, params: dict[str, Any]) -> object:
        self.params.append(params)
        if self._name in self._refused:
            raise self._error("refused")
        return {"data": []}


class _ProcessorOf:
    """The SDK client's `v1` as far as the key check reads it: five lists,
    each refused when the key lacks its resource."""

    def __init__(self, refused: set[str], error: type[Exception] = stripe.PermissionError) -> None:
        def lister(name: str) -> _Lister:
            return _Lister(name, refused, error)

        self.customers = lister("customers")
        self.subscriptions = lister("subscriptions")
        self.prices = lister("prices")
        self.checkout = type("Checkout", (), {"sessions": lister("checkout.sessions")})()
        self.billing_portal = type(
            "Portal", (), {"configurations": lister("billing_portal.configurations")}
        )()
        self.v1 = self


async def _checked(refused: set[str], error: type[Exception] = stripe.PermissionError) -> Any:
    payments = PaymentsStripeImpl(
        api_key="rk_test_x",
        account_id="acct_test",
        webhook_secret=SECRET,
        timeout=timedelta(seconds=3),
        check_at_start=False,
    )
    await payments.start()
    await payments.close()
    payments._client = _ProcessorOf(refused, error)  # type: ignore[assignment]
    return payments


async def test_a_key_that_reads_every_resource_passes_the_check() -> None:
    payments = await _checked(set())
    assert await payments.check_access() == ()
    assert "lacks" not in payments.describe()
    client = payments._client
    assert all(
        lister.params == [{"limit": 1}]
        for lister in (
            client.customers,
            client.subscriptions,
            client.prices,
            client.checkout.sessions,
            client.billing_portal.configurations,
        )
    )


async def test_a_key_without_checkout_sessions_is_named_at_start(
    caplog: pytest.LogCaptureFixture,
) -> None:
    payments = await _checked({"checkout.sessions"})
    with caplog.at_level(logging.ERROR):
        assert await payments.check_access() == (CHECKOUT_SESSIONS,)
    assert payments.describe().endswith("; the key lacks Checkout Sessions)")
    assert "lacks Checkout Sessions (group Checkout Sessions)" in caplog.text
    assert "rk_test_x" not in caplog.text


async def test_a_key_every_read_refuses_is_named_as_the_wrong_account(
    caplog: pytest.LogCaptureFixture,
) -> None:
    payments = await _checked(
        {
            "customers",
            "subscriptions",
            "prices",
            "checkout.sessions",
            "billing_portal.configurations",
        },
        stripe.AuthenticationError,
    )
    with caplog.at_level(logging.ERROR):
        assert await payments.check_access() == RUNTIME_PERMISSIONS
    assert "not a key of acct_test" in caplog.text


async def test_a_processor_that_does_not_answer_leaves_the_check_open() -> None:
    payments = await _checked({"customers"}, stripe.APIConnectionError)
    assert await payments.check_access() == ()
    assert "lacks" not in payments.describe()


async def test_the_real_client_names_the_account_and_the_pinned_version() -> None:
    payments = PaymentsStripeImpl(
        api_key="rk_test_x",
        account_id="acct_test",
        webhook_secret=SECRET,
        timeout=timedelta(seconds=3),
        check_at_start=False,
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


class _Sessions:
    def __init__(self) -> None:
        self.params: list[dict[str, Any]] = []

    async def create_async(self, params: dict[str, Any]) -> object:
        self.params.append(params)
        return type("Session", (), {"url": "https://billing.stripe.com/p/session"})()


class _Configurations:
    async def list_async(self, params: dict[str, Any]) -> object:
        return type("Page", (), {"data": []})()


class _PortalOf:
    """The SDK client's `v1` as far as a portal session reads it."""

    def __init__(self) -> None:
        self.sessions = _Sessions()
        self.billing_portal = type(
            "Portal", (), {"sessions": self.sessions, "configurations": _Configurations()}
        )()
        self.v1 = self


async def test_a_portal_session_for_a_failed_payment_opens_the_payment_method_flow() -> None:
    """The processor's documented deep link: `flow_data` of type
    `payment_method_update`, redirecting back to the page that asked."""
    payments = await _checked(set())
    portal = _PortalOf()
    payments._client = portal  # type: ignore[assignment]
    await payments.create_portal_session("cus_1", "http://portal.test/settings/billing")
    await payments.create_portal_session(
        "cus_1", "http://portal.test/settings/billing", update_payment_method=True
    )
    home, fix = portal.sessions.params
    assert "flow_data" not in home
    assert fix["flow_data"] == {
        "type": "payment_method_update",
        "after_completion": {
            "type": "redirect",
            "redirect": {"return_url": "http://portal.test/settings/billing"},
        },
    }
    assert fix["customer"] == "cus_1"


class _Ends:
    """The SDK client's `v1` as far as ending an account reads it: one
    subscription in a status, and the calls made."""

    def __init__(self, status: str | None, missing: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self._status = status
        self._missing = missing
        ends = self

        class Subscriptions:
            async def retrieve_async(self, subscription_id: str) -> object:
                if ends._status is None:
                    raise stripe.InvalidRequestError("gone", None, code="resource_missing")
                raw = {"id": subscription_id, "customer": "cus_1", "status": ends._status}
                return type("S", (), {"to_dict": lambda self: raw})()

            async def cancel_async(self, subscription_id: str) -> object:
                ends.calls.append(("cancel", subscription_id))
                return object()

        class Customers:
            async def delete_async(self, customer_id: str) -> object:
                ends.calls.append(("delete", customer_id))
                if ends._missing:
                    raise stripe.InvalidRequestError("gone", None, code="resource_missing")
                return object()

        self.subscriptions = Subscriptions()
        self.customers = Customers()
        self.v1 = self


@pytest.mark.parametrize(
    ("status", "calls"),
    [
        ("active", [("cancel", "sub_1"), ("delete", "cus_1")]),
        ("past_due", [("cancel", "sub_1"), ("delete", "cus_1")]),
        ("canceled", [("delete", "cus_1")]),
        (None, [("delete", "cus_1")]),
    ],
)
async def test_an_accounts_subscription_ends_now_and_its_customer_goes(
    status: str | None, calls: list[tuple[str, str]]
) -> None:
    """A live subscription is canceled at once, one that ended or that the
    processor no longer knows is left alone, and the customer is deleted."""
    payments = await _checked(set())
    ends = _Ends(status)
    payments._client = ends  # type: ignore[assignment]
    await payments.cancel_subscription("sub_1")
    await payments.delete_customer("cus_1")
    assert ends.calls == calls


async def test_a_customer_the_processor_no_longer_knows_is_deleted_already() -> None:
    payments = await _checked(set())
    payments._client = _Ends("canceled", missing=True)  # type: ignore[assignment]
    await payments.delete_customer("cus_1")


async def test_a_runtime_key_refused_the_end_of_an_account_is_unavailable_not_refused() -> None:
    """A key without the permission is the process's to fix: the work waits."""
    payments = await _checked(set())

    class Refusing(_Ends):
        def __init__(self) -> None:
            super().__init__("active")

            class Customers:
                async def delete_async(self, customer_id: str) -> object:
                    raise stripe.PermissionError("no", None, code=None)

            self.customers = Customers()

    payments._client = Refusing()  # type: ignore[assignment]
    with pytest.raises(ProviderUnavailable) as raised:
        await payments.delete_customer("cus_1")
    assert "delete customer" in str(raised.value)


async def test_a_runtime_key_refused_the_read_before_a_cancel_is_unavailable() -> None:
    """The read on the way to the cancel is the end's too: a key without the
    permission to read subscriptions parks the work, never fails it."""
    payments = await _checked(set())

    class Unreadable(_Ends):
        def __init__(self) -> None:
            super().__init__("active")
            ends = self

            class Subscriptions:
                async def retrieve_async(self, subscription_id: str) -> object:
                    raise stripe.PermissionError("no", None, code=None)

                async def cancel_async(self, subscription_id: str) -> object:
                    ends.calls.append(("cancel", subscription_id))
                    return object()

            self.subscriptions = Subscriptions()

    unreadable = Unreadable()
    payments._client = unreadable  # type: ignore[assignment]
    with pytest.raises(ProviderUnavailable) as raised:
        await payments.cancel_subscription("sub_1")
    assert "read subscription" in str(raised.value)
    assert unreadable.calls == []


async def test_a_cancel_the_processor_refuses_as_a_request_is_refused() -> None:
    """A refusal of the request itself stays a refusal: the caller decides."""
    payments = await _checked(set())

    class Invalid(_Ends):
        def __init__(self) -> None:
            super().__init__("active")

            class Subscriptions:
                async def retrieve_async(self, subscription_id: str) -> object:
                    raise stripe.InvalidRequestError("bad", None, code="parameter_invalid")

            self.subscriptions = Subscriptions()

    payments._client = Invalid()  # type: ignore[assignment]
    with pytest.raises(PaymentsRefused) as raised:
        await payments.cancel_subscription("sub_1")
    assert "parameter_invalid" in str(raised.value)
