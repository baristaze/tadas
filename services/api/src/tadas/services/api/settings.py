"""The one settings object of the API process: storage, infra, and the
knobs that belong to this service, all under the TADAS_ prefix."""

import ipaddress

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from tadas.infra.impl.settings import InfraSettings
from tadas.om.storage.settings import StorageSettings


class ApiSettings(StorageSettings, InfraSettings):
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

    login_rate_limit: int = 10
    login_rate_window_seconds: int = 60
    # Sign-up is open by default: a deployed environment has no other door,
    # since the seeding is local. False closes it, and the route then answers
    # 404 as a route that does not exist would. Its budget is its own, per
    # client address, the way the login's is.
    signup_enabled: bool = True
    signup_rate_limit: int = 10
    signup_rate_window_seconds: int = 60
    # The socket's two send lanes, each bounded on its own. The stream lane
    # holds the event hints, and a full one drops its oldest: the client that
    # sees the gap replays from storage. The control lane holds the frames
    # that say where the socket stands (hello, pong, subscribed,
    # unsubscribed, error), and it is small because a socket offers few of
    # them; a lane that fills is a fault of the process, not a burst.
    realtime_send_buffer_size: int = Field(default=256, gt=0)
    realtime_control_buffer_size: int = Field(default=16, gt=0)
    # The readiness probe's own deadline, shorter than the interval it is
    # polled on (the container probe asks every 10 seconds and gives up at 3,
    # the load balancer every 15 and gives up at 5), so a hung database or an
    # exhausted pool makes the probe answer "not ready" instead of making it
    # stop answering. Seconds.
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
