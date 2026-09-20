"""Every outbound client is built with a timeout from settings, and no call
goes out without one. The scan reads every source root the way a reviewer
does: each construction of an HTTP, socket, AWS, Valkey, or exporter client
names a timeout (or the AWS configuration that carries one) at the call
site. The cases below then build each client and read the timeout back."""

import ast
import subprocess
from datetime import timedelta
from pathlib import Path

import aioboto3

from tadas.infra.buckets.s3 import BucketsS3Impl
from tadas.infra.observability import span_exporter
from tadas.infra.queues.sqs import QueueSqsImpl
from tadas.infra.secrets.aws import SecretsAwsImpl

SOURCE_ROOTS = (
    "clients/python/src",
    "apps/cli/src",
    "services/api/src",
    "infra/src",
    "workers/maintenance/src",
)

CLIENT_CONSTRUCTORS = {
    "AsyncClient",  # httpx
    "Client",  # httpx
    "connect",  # websockets
    "OTLPSpanExporter",
    "GlideClientConfiguration",
}
"""A call by one of these names is a client being built; `session.client(...)`
(an AWS client) is matched by its receiver below."""


def repository_root() -> Path:
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).parent,
    ).stdout.strip()
    return Path(top)


def _is_client_construction(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id in CLIENT_CONSTRUCTORS
    if isinstance(func, ast.Attribute):
        if func.attr in CLIENT_CONSTRUCTORS:
            return True
        receiver = func.value
        if func.attr == "client":
            if isinstance(receiver, ast.Attribute):
                return receiver.attr.endswith("session")
            return isinstance(receiver, ast.Name) and receiver.id.endswith("session")
    return False


def _carries_a_timeout(call: ast.Call) -> bool:
    keywords = {keyword.arg for keyword in call.keywords if keyword.arg}
    return "config" in keywords or any("timeout" in name for name in keywords)


def client_constructions() -> list[tuple[str, bool]]:
    """Every client construction under the source roots as (site, bounded)."""
    root = repository_root()
    found: list[tuple[str, bool]] = []
    for source_root in SOURCE_ROOTS:
        for path in sorted((root / source_root).rglob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _is_client_construction(node):
                    site = f"{path.relative_to(root)}:{node.lineno}"
                    found.append((site, _carries_a_timeout(node)))
    return found


def test_every_client_construction_names_a_timeout() -> None:
    found = client_constructions()
    sites = {site.split(":")[0] for site, _ in found}
    assert sites >= {
        "clients/python/src/tadas/client/client.py",
        "clients/python/src/tadas/client/realtime.py",
        "infra/src/tadas/infra/buckets/s3.py",
        "infra/src/tadas/infra/queues/sqs.py",
        "infra/src/tadas/infra/secrets/aws.py",
        "infra/src/tadas/infra/impl/valkey.py",
        "infra/src/tadas/infra/observability.py",
    }, "the scan no longer sees a client it used to; widen it before trusting it"
    unbounded = [site for site, bounded in found if not bounded]
    assert not unbounded, f"clients built without a timeout: {unbounded}"


async def test_every_aws_client_is_opened_with_the_timeout() -> None:
    session = aioboto3.Session(
        aws_access_key_id="key", aws_secret_access_key="secret", region_name="us-east-1"
    )
    timeout = timedelta(seconds=7)
    impls = (
        BucketsS3Impl(
            session, endpoint_url=None, region="us-east-1", bucket_prefix="t", timeout=timeout
        ),
        QueueSqsImpl(
            session, endpoint_url=None, region="us-east-1", queue_prefix="t-", timeout=timeout
        ),
        SecretsAwsImpl(session, region="us-east-1", name_prefix="t/", timeout=timeout),
    )
    for impl in impls:
        async with impl._client() as client:  # opened, not called: no request leaves
            config = client.meta.config
            assert (config.connect_timeout, config.read_timeout) == (7.0, 7.0), impl.describe()


def test_the_trace_exporter_is_bounded_by_the_timeout() -> None:
    exporter = span_exporter("http://127.0.0.1:1/", timedelta(seconds=3))
    assert exporter._timeout == 3.0  # pyright: ignore[reportPrivateUsage] (read back, not set)
    assert exporter._endpoint == "http://127.0.0.1:1/v1/traces"  # pyright: ignore[reportPrivateUsage]
