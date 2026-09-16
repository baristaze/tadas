"""The infra half of every process's settings object. Backends are selected
here and nowhere else."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

CLOUD_ENVIRONMENTS = frozenset({"staging", "production"})


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

    aws_region: str = "us-east-1"

    log_level: str = "INFO"
    log_json: bool = False
    otel_endpoint: str | None = None

    @property
    def is_cloud_environment(self) -> bool:
        return self.environment in CLOUD_ENVIRONMENTS
