"""`tadas-ops token`: a token goes into the env file and nowhere else. The
operator's is minted only in a person's own terminal; the provisioner's is
copied from the secret the grant job wrote, in a cloud environment."""

import argparse
import io
from pathlib import Path

import httpx
import pytest

from tadas.ops import main as ops_main
from tadas.ops.main import token_command


def env_file(home: Path, name: str) -> Path:
    file = home / ".config" / "tadas" / "ops" / f"{name}.env"
    file.parent.mkdir(parents=True)
    file.write_text("TADAS_API_URL=http://test\nTADAS_OPERATOR_TOKEN=\n")
    file.chmod(0o600)
    return file


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def mint_route(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/auth/login":
        assert request.content and b'"totp_code":"123456"' in request.content.replace(b" ", b"")
        return httpx.Response(200, json={"token": "lgn_op", "expires_at": "x", "memberships": []})
    if request.url.path == "/v1/admin/me/tokens":
        assert request.headers["authorization"] == "Bearer lgn_op"
        assert request.headers["idempotency-key"]
        return httpx.Response(201, json={"token": "opt_minted", "expires_at": "x"})
    return httpx.Response(404, json={"error": {"code": "not_found", "message": "no"}})


async def test_the_operator_token_is_minted_in_a_terminal_and_written_unprinted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    file = env_file(tmp_path, "staging")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.stdin", Terminal())
    monkeypatch.setattr("builtins.input", lambda prompt: "ops@example.test")
    answers = iter(["secret", "123456"])
    monkeypatch.setattr(ops_main.getpass, "getpass", lambda prompt: next(answers))
    code = await token_command(
        argparse.Namespace(env="staging", identity="operator", profile=None),
        transport=httpx.MockTransport(mint_route),
    )
    assert code == 0
    assert "TADAS_OPERATOR_TOKEN=opt_minted\n" in file.read_text()
    out = capsys.readouterr().out
    assert "opt_minted" not in out and "secret" not in out


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
