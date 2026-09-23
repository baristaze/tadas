"""The one settings object of the API process: storage, infra, and the
knobs that belong to this service, all under the TADAS_ prefix."""

import ipaddress

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import SettingsConfigDict

from tadas.infra.impl.settings import InfraSettings
from tadas.integrations.settings import IntegrationsSettings
from tadas.om.storage.settings import StorageSettings


class ApiSettings(StorageSettings, InfraSettings, IntegrationsSettings):
    model_config = SettingsConfigDict(env_prefix="TADAS_", env_file=".env", extra="ignore")

    service_name: str = "api"
    version: str = "0.1.0"
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # The proxies whose X-Forwarded-For names the client, as addresses or
    # CIDR blocks; never "*", which trusts every peer and so lets any caller
    # choose its own address for the login rate limit. Empty, the peer is the
    # client and the header is ignored; the cloud passes the VPC block the
    # load balancer lives in.
    trusted_proxies: list[str] = []

    # Every number in this file is illustrative, and deliberately generous:
    # this system is here to show the shape, and a limit that trips during a
    # demo teaches the wrong lesson. A team adopting it sets its own from
    # what its traffic does. What is not illustrative is where each bound
    # sits and what it protects.
    #
    # This budget is per address, and one address is a crowd: a company
    # behind one gateway, a school, a shared runner. So it is sized for a
    # crowd signing in, not for one person, and the defence against guessing
    # a password is the per-email delay below, which no crowd dilutes.
    login_rate_limit: int = 200
    login_rate_window_seconds: int = 60
    # Past the per-address limit, which rides the cache and fails open: a run
    # of failed sign-ins for one email, held by an identity or not, makes the
    # next one wait, counted in the database. The first
    # `sign_in_free_failures` cost nothing; then the wait starts at the base
    # and doubles, up to the cap.
    sign_in_free_failures: int = Field(default=3, ge=1)
    sign_in_delay_base_seconds: float = Field(default=1.0, gt=0)
    sign_in_delay_cap_seconds: float = Field(default=300.0, gt=0)
    # How long a sign-in lasts before it must be exchanged for a session, and
    # how long a session lasts: from its exchange, whatever it is used for
    # (the absolute lifetime), and from its last use (the idle one). A
    # session ends at whichever passes first.
    login_lifetime_seconds: int = Field(default=600, gt=0)
    session_lifetime_seconds: int = Field(default=43200, gt=0)
    session_idle_lifetime_seconds: int = Field(default=14400, gt=0)
    # The longest an operator token lives, and what a mint that names no
    # lifetime gets. An hour at most, whoever mints it.
    operator_token_max_lifetime_seconds: int = Field(default=3600, gt=0, le=3600)
    # The key the operators' TOTP secrets are sealed under: a Fernet-shaped
    # key (URL-safe base64 of 32 bytes), a process credential injected at
    # start from the secret store like the database URL, and only into the
    # API. No default: a process without it refuses every enrolment and every
    # sign-in that presents a code, and says so; one of the wrong shape
    # refuses to start.
    totp_encryption_key: SecretStr | None = None
    # Sign-up is open by default: a deployed environment has no other door,
    # since the seeding is local. False closes it, and the route then answers
    # 404 as a route that does not exist would. Its budget is its own, per
    # client address, the way the login's is.
    signup_enabled: bool = True
    # The interactive API docs and the OpenAPI document, served locally for
    # a developer. A deployed environment turns them off: the document is in
    # the repository, and a production edge has no use for a console.
    interactive_docs: bool = True
    # Per address, like the login budget and for the same reason.
    signup_rate_limit: int = 200
    signup_rate_window_seconds: int = 60
    # The socket's two send lanes, each bounded on its own. The stream lane
    # holds the event hints, and a full one drops its oldest: the client that
    # sees the gap replays from storage. The control lane holds the frames
    # that say where the socket stands (hello, pong, subscribed,
    # unsubscribed, error), and it is small because a socket offers few of
    # them; a lane that fills is a fault of the process, not a burst.
    realtime_send_buffer_size: int = Field(default=256, gt=0)
    realtime_control_buffer_size: int = Field(default=16, gt=0)
    # The readiness probe's own deadline, shorter than its prober's timeout
    # (the deploy's check after a rollout gives up at 10 seconds), so a hung
    # database or an exhausted pool makes the probe answer "not ready"
    # instead of making it stop answering. Seconds.
    readiness_timeout_seconds: float = 2.0
    # Admission: the requests this process keeps in flight at once, counted
    # in two budgets, and what a refusal past either tells the client to
    # wait. Reads (GET, HEAD) and writes are budgeted apart so that a read
    # storm, which is what a client that was offline replaying its backlog
    # is, cannot take every slot from the commands. Together they are the one
    # bound the process had, which is a multiple of what it can actually work
    # on: the declared size of the pool it opens per role and no more, since
    # the pools carry no overflow. Reads are the many and writes the few, so
    # that is how the bound is split. A burst still waits briefly on a
    # checkout, which has a bound of its own, and only a flood is refused; it
    # is not the login rate limit, which is fairness between subjects and
    # fails open.
    admission_limit_reads: int = Field(default=48, gt=0)
    admission_limit_writes: int = Field(default=16, gt=0)
    admission_retry_after_seconds: int = 1

    @field_validator("trusted_proxies")
    @classmethod
    def proxies_are_addresses_or_blocks(cls, proxies: list[str]) -> list[str]:
        """Each proxy is an address or a CIDR block. uvicorn takes a wildcard as
        trust in every peer, and a name it cannot parse as a literal host, so
        both are refused here, where the mistake is one line to find."""
        for proxy in proxies:
            try:
                ipaddress.ip_network(proxy)
            except ValueError:
                raise ValueError(
                    f"trusted_proxies names {proxy!r}; each proxy is an address or a CIDR block"
                ) from None
        return proxies
