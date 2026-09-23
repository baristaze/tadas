"""`tadas-ops token`: a token goes into the env file and nowhere else. The
operator's is minted only in a person's own terminal, after a sign-in through
the identity provider and the second factor; the provisioner's is copied from
the secret the grant job wrote, in a cloud environment."""

import argparse
import io
import json
from pathlib import Path

import httpx
import pytest

from tadas.client.client import ApiClient
from tadas.ops import main as ops_main
from tadas.ops.main import device_sign_in, token_command


def env_file(home: Path, name: str) -> Path:
    file = home / ".config" / "tadas" / "ops" / f"{name}.env"
    file.parent.mkdir(parents=True)
    file.write_text("TADAS_API_URL=http://test\nTADAS_OPERATOR_TOKEN=\n")
    file.chmod(0o600)
    return file


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


LOGIN = {"expires_at": "2026-09-20T12:00:00Z", "memberships": []}
DEVICE = {
    "device_code": "dev_secret",
    "user_code": "ABCD-EFGH",
    "verification_uri": "https://auth.example.test/device",
    "verification_uri_complete": "https://auth.example.test/device?user_code=ABCD-EFGH",
    "expires_in": 300,
    "interval": 5,
}


class SignInRoutes:
    """The device sign-in, answered pending `pending` times (the first of them
    a slow-down), then the second factor and the mint."""

    def __init__(self, pending: int = 2) -> None:
        self.pending = pending
        self.paths: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.paths.append(path)
        body = json.loads(request.content) if request.content else {}
        if path == "/v1/auth/device":
            return httpx.Response(200, json=DEVICE)
        if path == "/v1/auth/device/token":
            assert body == {"device_code": "dev_secret"}
            if self.pending > 0:
                code = "sign_in_slow_down" if self.pending == 2 else "sign_in_pending"
                self.pending -= 1
                return httpx.Response(400, json={"error": {"code": code, "message": "wait"}})
            return httpx.Response(200, json={"token": "lgn_first", **LOGIN})
        if path == "/v1/auth/dev-sign-in":
            assert body["email"] == "ops@example.test"
            return httpx.Response(200, json={"token": "lgn_first", **LOGIN})
        if path == "/v1/auth/second-factor":
            assert request.headers["authorization"] == "Bearer lgn_first"
            assert body == {"totp_code": "123456"}
            return httpx.Response(200, json={"token": "lgn_verified", **LOGIN})
        if path == "/v1/admin/me/tokens":
            assert request.headers["authorization"] == "Bearer lgn_verified"
            assert request.headers["idempotency-key"]
            return httpx.Response(201, json={"token": "opt_minted", "expires_at": "x"})
        return httpx.Response(404, json={"error": {"code": "not_found", "message": "no"}})


async def test_a_device_sign_in_waits_the_interval_and_longer_after_a_slow_down(
    capsys: pytest.CaptureFixture[str],
) -> None:
    routes = SignInRoutes(pending=2)
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    async with ApiClient(
        "http://test", app="admin", app_version="ops@test", transport=httpx.MockTransport(routes)
    ) as client:
        token = await device_sign_in(client, sleep=sleep, clock=lambda: 0.0)
    assert token == "lgn_first"
    assert waits == [5.0, 10.0, 10.0]
    err = capsys.readouterr().err
    assert "ABCD-EFGH" in err and "dev_secret" not in err


async def test_a_device_sign_in_stops_when_its_code_expires() -> None:
    routes = SignInRoutes(pending=1000)
    ticks = iter(range(0, 10_000, 100))

    async def sleep(seconds: float) -> None:
        return None

    async with ApiClient(
        "http://test", app="admin", app_version="ops@test", transport=httpx.MockTransport(routes)
    ) as client:
        with pytest.raises(ValueError, match="expired"):
            await device_sign_in(client, sleep=sleep, clock=lambda: float(next(ticks)))


async def test_the_operator_token_is_minted_in_a_terminal_and_written_unprinted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    file = env_file(tmp_path, "staging")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.stdin", Terminal())
    monkeypatch.setattr(ops_main.getpass, "getpass", lambda prompt: "123456")

    async def no_wait(seconds: float) -> None:
        return None

    monkeypatch.setattr(ops_main.asyncio, "sleep", no_wait)
    routes = SignInRoutes(pending=1)
    code = await token_command(
        argparse.Namespace(env="staging", identity="operator", profile=None, dev_email=None),
        transport=httpx.MockTransport(routes),
    )
    assert code == 0
    assert routes.paths[0] == "/v1/auth/device"
    assert "TADAS_OPERATOR_TOKEN=opt_minted\n" in file.read_text()
    captured = capsys.readouterr()
    assert "opt_minted" not in captured.out + captured.err
    assert "lgn_" not in captured.out + captured.err


async def test_the_local_stack_signs_the_operator_in_by_address(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = env_file(tmp_path, "local")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.stdin", Terminal())
    monkeypatch.setattr(ops_main.getpass, "getpass", lambda prompt: "123456")
    routes = SignInRoutes()
    code = await token_command(
        argparse.Namespace(
            env="local", identity="operator", profile=None, dev_email="ops@example.test"
        ),
        transport=httpx.MockTransport(routes),
    )
    assert code == 0
    assert routes.paths[0] == "/v1/auth/dev-sign-in"
    assert "TADAS_OPERATOR_TOKEN=opt_minted\n" in file.read_text()


async def test_the_local_sign_in_is_refused_for_a_deployed_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file(tmp_path, "staging")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.stdin", Terminal())
    code = await token_command(
        argparse.Namespace(
            env="staging", identity="operator", profile=None, dev_email="ops@example.test"
        )
    )
    assert code == 2


async def test_the_operator_token_is_never_minted_without_a_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file(tmp_path, "staging")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO())
    code = await token_command(argparse.Namespace(env="staging", identity="operator", profile=None))
    assert code == 2


async def test_the_provisioner_token_is_copied_only_in_a_cloud_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file(tmp_path, "local")
    monkeypatch.setenv("HOME", str(tmp_path))
    code = await token_command(
        argparse.Namespace(env="local", identity="provisioner", profile=None)
    )
    assert code == 2


async def test_the_provisioner_token_is_never_read_under_an_investigate_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file(tmp_path, "staging")
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ValueError, match="reads no secret"):
        await token_command(
            argparse.Namespace(
                env="staging", identity="provisioner", profile="tadas-staging-investigate"
            )
        )
