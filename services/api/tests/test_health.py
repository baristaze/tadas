import httpx


async def test_healthz_answers_with_the_version(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}
    assert "x-request-id" in response.headers


async def test_readyz_awaits_the_storage_healthcheck(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"ready": True}


async def test_metrics_are_exposed_outside_the_versioned_api(client: httpx.AsyncClient) -> None:
    await client.get("/healthz")
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "tadas_http_requests_total" in response.text
