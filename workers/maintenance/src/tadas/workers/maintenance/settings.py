"""The one settings object of the maintenance worker."""

import os
import socket

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from tadas.infra.impl.settings import InfraSettings
from tadas.om.storage.settings import StorageSettings


def default_worker_id() -> str:
    return f"maintenance-{socket.gethostname()}-{os.getpid()}"


class MaintenanceSettings(StorageSettings, InfraSettings):
    model_config = SettingsConfigDict(env_prefix="TADAS_", env_file=".env", extra="ignore")

    service_name: str = "maintenance"
    version: str = "0.1.0"
    # The worker serves no HTTP but its metrics; containers bind 0.0.0.0.
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 9464
    worker_id: str = Field(default_factory=default_worker_id)
    worker_lane: str = "default"
    worker_capacity: int = 4
    worker_lease_seconds: int = 60
    worker_heartbeat_seconds: int = 10
    worker_heartbeat_failure_limit: int = 3
    worker_sweep_seconds: int = 30
    worker_poll_seconds: int = 5
