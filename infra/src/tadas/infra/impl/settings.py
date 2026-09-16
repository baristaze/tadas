"""The infra half of every process's settings object. Backends are selected
here and nowhere else, and this is the only module below the container
that reads the environment."""

import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENVIRONMENTS = frozenset({"local", "test", "dev", "staging", "production"})
"""The one set of environment names, shared with deployment/terraform."""

CLOUD_ENVIRONMENTS = frozenset({"dev", "staging", "production"})
"""The deployed environments: each refuses every local-only backend at boot."""

SECRET_ENV_PREFIX = "TADAS_SECRET_"


def secret_overrides_from_environment() -> dict[str, str]:
    """TADAS_SECRET_<NAME>=value, collected once at boot and handed to the local
    secrets impl, keyed by NAME."""
    return {
        key[len(SECRET_ENV_PREFIX) :]: value
        for key, value in os.environ.items()
        if key.startswith(SECRET_ENV_PREFIX) and len(key) > len(SECRET_ENV_PREFIX)
    }


class InfraSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TADAS_", env_file=".env", extra="ignore")

    environment: str = "local"

    cache_backend: Literal["memory", "redis"] = "memory"
    topics_backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://127.0.0.1:56379/0"

    buckets_backend: Literal["local", "s3"] = "local"
    buckets_root: Path = Path(".local/buckets")
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket_prefix: str = "tadas"

    queues_backend: Literal["memory", "sqs"] = "memory"
    sqs_endpoint_url: str | None = None
    sqs_queue_prefix: str = "tadas-"

    secrets_backend: Literal["local", "aws"] = "local"
    secrets_file: Path | None = Path(".local/secrets.env")
    secrets_name_prefix: str = "tadas/"
    secret_overrides: dict[str, str] = Field(
        default_factory=secret_overrides_from_environment, exclude=True, repr=False
    )

    aws_region: str = "us-east-1"

    log_level: str = "INFO"
    log_json: bool = False
    otel_endpoint: str | None = None

    @property
    def is_known_environment(self) -> bool:
        return self.environment in ENVIRONMENTS

    @property
    def is_cloud_environment(self) -> bool:
        return self.environment in CLOUD_ENVIRONMENTS
