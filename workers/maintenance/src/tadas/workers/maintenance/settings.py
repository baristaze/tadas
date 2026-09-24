"""The one settings object of the maintenance worker."""

import os
import socket

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from tadas.infra.impl.settings import InfraSettings
from tadas.integrations.settings import IntegrationsSettings
from tadas.om.storage.settings import StorageSettings


def default_worker_id() -> str:
    return f"maintenance-{socket.gethostname()}-{os.getpid()}"


class MaintenanceSettings(StorageSettings, InfraSettings, IntegrationsSettings):
    model_config = SettingsConfigDict(env_prefix="TADAS_", env_file=".env", extra="ignore")

    service_name: str = "maintenance"
    version: str = "0.1.0"
    # The worker serves no HTTP but its metrics; containers bind 0.0.0.0.
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 9464
    worker_id: str = Field(default_factory=default_worker_id)
    worker_lane: str = "default"
    # Every one of these is a count or a duration the loop divides or waits
    # on, so zero is not a smaller setting but a broken one: a lease of zero
    # cancels each item as `lease_lost` the moment it is claimed, a heartbeat
    # of zero never lets the claim loop run, and a capacity of zero claims
    # nothing at all. The process refuses to start instead.
    worker_capacity: int = Field(default=4, gt=0)
    worker_lease_seconds: int = Field(default=60, gt=0)
    worker_heartbeat_seconds: int = Field(default=10, gt=0)
    worker_sweep_seconds: int = Field(default=30, gt=0)
    worker_poll_seconds: int = Field(default=5, gt=0)

    # Where people open Tadas in this environment: a list answered in Slack
    # links to the task list there. The local stack's portal by default; a deployed
    # environment names its own.
    portal_url: str = "http://localhost:55173"
    # How long a received Slack delivery stays hidden from other consumers
    # while one handles it; one that is not deleted by then comes back.
    slack_inbound_visibility_seconds: int = Field(default=60, gt=0)
