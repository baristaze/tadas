"""The one settings object of the API process: storage, infra, and the
knobs that belong to this service, all under the TADAS_ prefix."""

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
    # The proxies whose X-Forwarded-For names the client, as addresses, CIDR
    # blocks, or "*". Empty, the peer is the client and the header is ignored;
    # the cloud passes the VPC block the load balancer lives in.
    trusted_proxies: list[str] = []

    login_rate_limit: int = 10
    login_rate_window_seconds: int = 60
    realtime_send_buffer_size: int = 256
