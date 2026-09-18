from datetime import timedelta
from pathlib import Path

from tadas.infra.base import new_id
from tadas.infra.buckets import Buckets
from tadas.infra.cache import CacheScope
from tadas.infra.impl.local import InfraLocalImpl
from tadas.infra.queues import Queues


async def test_every_capability_works_over_the_local_root(tmp_path: Path) -> None:
    infra = InfraLocalImpl(tmp_path)
    await infra.start()
    org = new_id()
    await infra.get_cache(CacheScope.NETWORK_RESPONSE).put(org, "k", b"v", timedelta(seconds=5))
    assert await infra.get_cache(CacheScope.NETWORK_RESPONSE).get(org, "k") == b"v"
    await infra.get_buckets().put(org, Buckets.EXPORTS, "f.txt", b"hi", "text/plain")
    assert await infra.get_buckets().get(org, Buckets.EXPORTS, "f.txt") == b"hi"
    await infra.get_queues().send(Queues.WEBHOOKS, b"m")
    assert (await infra.get_queues().depth(Queues.WEBHOOKS)).visible == 1
    await infra.get_secrets().put("s", "v")
    assert await infra.get_secrets().get("s") == "v"
    assert infra.get_topics().describe() == "topics=memory"
    assert len(infra.describe()) == 5
    await infra.close()
