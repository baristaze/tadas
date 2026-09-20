"""`tadas-ops size`: the operator signs in and reads `/v1/admin/size`."""

import argparse
import json
from pathlib import Path

import httpx
import pytest

from tadas.ops.main import size_command


def operator_api(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/auth/login":
        body = json.loads(request.content)
        assert body == {"email": "ops@example.test", "password": "secret"}
        return httpx.Response(
            200, json={"token": "lgn_op", "expires_at": "2026-09-20T12:00:00Z", "memberships": []}
        )
    if request.url.path == "/v1/admin/size":
        assert request.headers["authorization"] == "Bearer lgn_op"
        assert request.headers["x-app"] == "admin"
        return httpx.Response(200, json={"orgs": 3, "users": 12, "tasks_last_24h": 40})
    return httpx.Response(404)


async def test_size_reads_the_operator_plane_as_the_operator(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / ".config" / "tadas" / "ops" / "staging.env"
    file.parent.mkdir(parents=True)
    file.write_text(
        "TADAS_API_URL=http://test\nTADAS_OPERATOR_EMAIL=ops@example.test\nTADAS_OPERATOR_PASSWORD=secret\n"
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TADAS_API_URL", raising=False)
    code = await size_command(
        argparse.Namespace(env="staging"), transport=httpx.MockTransport(operator_api)
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "orgs                     3" in out and "tasks_last_24h           40" in out
