"""What the envelope says: a refusal names its reason, a failure the client
cannot act on says "internal error" and keeps its reason in the log, under
the request id."""

import logging

import httpx
import pytest
from fastapi import FastAPI

from tadas.infra.exceptions import BackendFailed
from tadas.infra.observability import RequestIdFilter
from tadas.om.exceptions import PlatformException


class Overloaded(PlatformException):
    http_status = 503
    code = "overloaded"


async def test_a_5xx_message_stays_in_the_log(
    app: FastAPI, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    @app.get("/infra-fails", include_in_schema=False)
    async def infra_fails() -> None:
        raise BackendFailed("s3", "get", "AccessDenied")

    @app.get("/overloaded", include_in_schema=False)
    async def overloaded() -> None:
        raise Overloaded("pool exhausted on db-7")

    caplog.handler.addFilter(RequestIdFilter())
    with caplog.at_level(logging.ERROR):
        infra = await client.get("/infra-fails")
        platform = await client.get("/overloaded")

    assert infra.status_code == 500
    assert infra.json()["error"] == {
        "code": "backend_failed",
        "message": "internal error",
        "request_id": infra.headers["x-request-id"],
    }
    assert platform.status_code == 503
    assert platform.json()["error"]["code"] == "overloaded"
    assert platform.json()["error"]["message"] == "internal error"

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert [r.request_id for r in errors] == [  # type: ignore[attr-defined]
        infra.headers["x-request-id"],
        platform.headers["x-request-id"],
    ]
    assert "s3 get failed with AccessDenied" in errors[0].getMessage()
    assert "pool exhausted on db-7" in errors[1].getMessage()


async def test_a_refusal_still_names_its_reason(client: httpx.AsyncClient) -> None:
    refused = await client.get("/v1/tasks")
    assert refused.status_code == 401
    assert refused.json()["error"]["message"] == "missing bearer credential"
