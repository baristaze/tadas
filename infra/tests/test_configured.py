from pathlib import Path

import pytest

from tadas.infra.cache import CacheScope
from tadas.infra.impl.configured import InfraConfiguredImpl, UnsafeConfiguration
from tadas.infra.impl.settings import InfraSettings


def local_settings(tmp_path: Path, **overrides: object) -> InfraSettings:
    base = {
        "environment": "local",
        "buckets_root": tmp_path / "buckets",
        "secrets_file": tmp_path / "secrets.env",
    }
    return InfraSettings.model_validate({**base, **overrides})


@pytest.mark.parametrize(
    "field,value",
    [
        ("secrets_backend", "local"),
        ("cache_backend", "memory"),
        ("topics_backend", "memory"),
        ("buckets_backend", "local"),
        ("queues_backend", "memory"),
    ],
)
def test_production_refuses_local_backends(tmp_path: Path, field: str, value: str) -> None:
    cloud = {
        "secrets_backend": "aws",
        "cache_backend": "redis",
        "topics_backend": "redis",
        "buckets_backend": "s3",
        "queues_backend": "sqs",
        field: value,
    }
    with pytest.raises(UnsafeConfiguration) as raised:
        InfraConfiguredImpl(local_settings(tmp_path, environment="production", **cloud))
    assert field.upper() in raised.value.message


async def test_local_environment_builds_local_impls(tmp_path: Path) -> None:
    infra = InfraConfiguredImpl(local_settings(tmp_path))
    assert infra.get_cache(CacheScope.RATE_LIMIT) is infra.get_cache(CacheScope.RATE_LIMIT)
    assert infra.describe() == [
        "cache=memory",
        "topics=memory",
        f"buckets=local({tmp_path / 'buckets'})",
        "queues=memory",
        f"secrets=local({tmp_path / 'secrets.env'})",
    ]
    await infra.start()
    await infra.close()


def test_cloud_backends_are_constructed_without_connecting(tmp_path: Path) -> None:
    infra = InfraConfiguredImpl(
        local_settings(
            tmp_path,
            cache_backend="redis",
            topics_backend="redis",
            buckets_backend="s3",
            queues_backend="sqs",
            secrets_backend="aws",
        )
    )
    assert infra.describe() == [
        "cache=redis",
        "topics=redis",
        "buckets=s3(us-east-1)",
        "queues=sqs(us-east-1)",
        "secrets=aws(us-east-1)",
    ]
    assert (
        infra.get_cache(CacheScope.NETWORK_RESPONSE).describe() == "cache[network_response]=redis"
    )
