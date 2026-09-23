"""The integrations family of exceptions. It hangs under infra's root, since
a provider is an external service like any hosted backend: the gateway
presents both alike, and a provider's own error type never crosses the
boundary."""

from tadas.infra.exceptions import InfraException, InfraUnavailable


class PaymentsUnconfigured(InfraUnavailable):
    """This environment holds no credential for the payment processor. The
    plans still apply; nobody can buy one here."""

    code = "billing_unavailable"


class PaymentsRefused(InfraException):
    """The processor answered, and refused: a credential without the
    permission the call needs, a price it does not know, a request it calls
    invalid. The message names the operation and the processor's error code,
    never a payload or a key."""

    http_status = 502
    code = "payments_refused"

    def __init__(self, operation: str, reason: str) -> None:
        super().__init__(f"the payment processor refused {operation}: {reason}")


class DeliveryRefused(InfraException):
    """An inbound delivery whose signature, timestamp, or body did not check
    out. Nothing is queued for it."""

    http_status = 400
    code = "webhook_signature_invalid"


class UnsafeProviderConfiguration(InfraException):
    """A provider setting a process refuses at boot: a twin outside a local
    environment, or a credential whose mode is not the environment's."""

    code = "unsafe_configuration"
