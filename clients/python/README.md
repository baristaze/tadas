# Tadas Python client

The one Python client of the API: every Python consumer (the CLI, the demo
recorders, a service that calls this one) goes through it, and nothing
else in Python calls `/v1/*`.

- `schema.py` is generated from the committed OpenAPI document
  (`apps/portal/openapi.json`, one document for both type sets) by
  `make openapi`; never hand-edited, excluded from lint, checked current
  in CI.
- `types.py` is the facade consumers import: the views and enums by name.
- `client.py` is the one transport client: bearer, app header, the error
  envelope parsed into `ApiError` with the request id, an idempotency key
  on every creating call, a 401 that clears the token, and the operating
  system's trust store. Request bodies are built by the operation methods
  from keyword arguments; the API validates them.
- `envelopes.py` mirrors the socket's frames by hand, as the portal's
  `envelopes.ts` does; they are not in the OpenAPI document.
- `stream.py` is the pure placement rule (next, seen, gap), the same cases
  the portal's `stream.ts` pins.
- `realtime.py` is the channel: a ticket, one subscription, pings at the
  interval the hello names from a timer of their own, gaps replayed from `/v1/events`, reconnects
  with backoff. `async for change in Channel(client)` yields every change
  once, in stream order.

```python
from tadas.client.client import ApiClient
from tadas.client.realtime import Channel

api = ApiClient("http://127.0.0.1:8000", app="cli", app_version="cli@0.1.0", token=token)
async with api:
    task = await api.create_task("Migrate DB")
    async for change in Channel(api):
        print(change.kind, change.target_id, change.actor_id)
```

```bash
uv run pytest -q clients/python/tests
```
