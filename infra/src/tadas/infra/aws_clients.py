"""The one place botocore's client configuration is named. Every AWS impl
opens its clients with the configuration built here, so every call out to
AWS carries the timeout from settings and none goes out without one."""

from datetime import timedelta

from botocore.config import Config


def client_config(timeout: timedelta) -> Config:
    """Connect and read bounded by the same timeout; a hung endpoint costs at
    most that per call, and botocore's default retries stay."""
    seconds = timeout.total_seconds()
    return Config(connect_timeout=seconds, read_timeout=seconds)
