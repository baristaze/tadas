from pathlib import Path

import pytest

from tadas.infra.cache import CacheScope
from tadas.infra.impl.configured import InfraConfiguredImpl, UnsafeConfiguration
from tadas.infra.impl.settings import InfraSettings

CLOUD_BACKENDS = {
    "secrets_backend": "aws",
    "cache_backend": "valkey",
    "topics_backend": "valkey",
    "buckets_backend": "s3",
    "queues_backend": "sqs",
}


def local_settings(tmp_path: Path, **overrides: object) -> InfraSettings:
    base = {
        "environment": "local",
        "buckets_root": tmp_path / "buckets",
        "secrets_file": tmp_path / "secrets.env",
    }
    return InfraSettings.model_validate({**base, **overrides})


@pytest.mark.parametrize("environment", ["dev", "staging", "production"])
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
def test_deployed_environments_refuse_local_backends(
    tmp_path: Path, environment: str, field: str, value: str
) -> None:
    with pytest.raises(UnsafeConfiguration) as raised:
        InfraConfiguredImpl(
            local_settings(tmp_path, environment=environment, **{**CLOUD_BACKENDS, field: value})
        )
    assert field.upper() in raised.value.message


@pytest.mark.parametrize("environment", ["prod", "Production", "stage", ""])
def test_an_unknown_environment_name_is_refused(tmp_path: Path, environment: str) -> None:
    """Terraform passes `production`; a process named `prod` must not boot on
    the file secrets backend by slipping past the cloud checks."""
    with pytest.raises(UnsafeConfiguration) as raised:
        InfraConfiguredImpl(local_settings(tmp_path, environment=environment))
    assert "TADAS_ENVIRONMENT" in raised.value.message


async def test_local_environment_builds_local_impls(tmp_path: Path) -> None:
    infra = InfraConfiguredImpl(local_settings(tmp_path))
    assert infra.get_cache(CacheScope.RATE_LIMIT) is infra.get_cache(CacheScope.RATE_LIMIT)
    assert infra.describe() == [
        *(f"cache[{scope.value}]=memory" for scope in CacheScope),
        "topics=memory",
        f"buckets=local({tmp_path / 'buckets'})",
        "queues=memory",
        f"secrets=local({tmp_path / 'secrets.env'})",
    ]
    await infra.start()
    await infra.close()


def test_cloud_backends_are_constructed_without_connecting(tmp_path: Path) -> None:
    infra = InfraConfiguredImpl(local_settings(tmp_path, **CLOUD_BACKENDS))
    assert infra.describe() == [
        *(f"cache[{scope.value}]=valkey" for scope in CacheScope),
        "topics=valkey",
        "buckets=s3(us-east-1)",
        "queues=sqs(us-east-1)",
        "secrets=aws(us-east-1)",
    ]
    assert (
        infra.get_cache(CacheScope.NETWORK_RESPONSE).describe() == "cache[network_response]=valkey"
    )


def test_every_cache_scope_is_built_at_construction(tmp_path: Path) -> None:
    """No lazy member: every scope's cache exists before the first request
    and the boot line names it (ADR 0007)."""
    infra = InfraConfiguredImpl(local_settings(tmp_path))
    built = {scope: infra.get_cache(scope) for scope in CacheScope}
    assert all(infra.get_cache(scope) is cache for scope, cache in built.items())
    assert [line for line in infra.describe() if line.startswith("cache[")] == [
        cache.describe() for cache in built.values()
    ]


async def test_secret_overrides_reach_the_local_secrets_impl(tmp_path: Path) -> None:
    infra = InfraConfiguredImpl(
        local_settings(tmp_path, secret_overrides={"API_TOKEN": "from-boot"})
    )
    assert await infra.get_secrets().get("api_token") == "from-boot"


@pytest.mark.parametrize("value", ["", "off", " OFF "])
def test_an_empty_or_off_sentry_dsn_turns_reporting_off(tmp_path: Path, value: str) -> None:
    assert local_settings(tmp_path, sentry_dsn=value).sentry_dsn is None


def test_a_sentry_dsn_is_kept(tmp_path: Path) -> None:
    dsn = "http://key@glitchtip:8000/1"
    assert local_settings(tmp_path, sentry_dsn=dsn).sentry_dsn == dsn
