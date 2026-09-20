import json
from datetime import timedelta
from typing import Any

import aioboto3

from tadas.infra.aws_clients import client_config
from tadas.infra.aws_errors import translated
from tadas.infra.observability import OUTCOMES
from tadas.infra.queues import QueueDepth, QueueInterface, QueueMessage, Queues


class QueueSqsImpl(QueueInterface):
    """The hosted queue moves a message to its dead-letter queue itself, after
    the redrive policy's receive count, so that transition is not observable
    here; `depth()` reports the dead-lettered count."""

    def __init__(
        self,
        session: aioboto3.Session,
        *,
        endpoint_url: str | None,
        region: str,
        queue_prefix: str,
        timeout: timedelta,
    ) -> None:
        self._session = session
        self._endpoint_url = endpoint_url
        self._region = region
        self._queue_prefix = queue_prefix
        self._config = client_config(timeout)
        self._urls: dict[str, str] = {}

    def _client(self) -> Any:
        return self._session.client(
            "sqs", endpoint_url=self._endpoint_url, region_name=self._region, config=self._config
        )

    async def _url(self, sqs: Any, name: str) -> str:
        if name not in self._urls:
            response = await sqs.get_queue_url(QueueName=name)
            self._urls[name] = response["QueueUrl"]
        return self._urls[name]

    def _name(self, queue: Queues) -> str:
        return f"{self._queue_prefix}{queue.value}"

    async def send(self, queue: Queues, body: bytes, *, dedup_id: str | None = None) -> str:
        attributes: dict[str, Any] = {}
        if dedup_id is not None:
            attributes["dedup_id"] = {"DataType": "String", "StringValue": dedup_id}
        with translated("sqs", "send"):
            async with self._client() as sqs:
                response = await sqs.send_message(
                    QueueUrl=await self._url(sqs, self._name(queue)),
                    MessageBody=body.decode(),
                    MessageAttributes=attributes,
                )
        OUTCOMES.labels(subsystem="queue", outcome="sent").inc()
        return response["MessageId"]

    async def receive(
        self, queue: Queues, max_messages: int, wait: timedelta, visibility: timedelta
    ) -> list[QueueMessage]:
        with translated("sqs", "receive"):
            async with self._client() as sqs:
                response = await sqs.receive_message(
                    QueueUrl=await self._url(sqs, self._name(queue)),
                    MaxNumberOfMessages=max(1, min(max_messages, 10)),
                    WaitTimeSeconds=int(min(wait.total_seconds(), 20)),
                    VisibilityTimeout=int(visibility.total_seconds()),
                    AttributeNames=["ApproximateReceiveCount"],
                )
        received = [
            QueueMessage(
                id=m["MessageId"],
                body=m["Body"].encode(),
                receipt=m["ReceiptHandle"],
                attempts=int(m.get("Attributes", {}).get("ApproximateReceiveCount", "1")),
            )
            for m in response.get("Messages", [])
        ]
        OUTCOMES.labels(subsystem="queue", outcome="received").inc(len(received))
        return received

    async def delete(self, queue: Queues, receipt: str) -> None:
        with translated("sqs", "delete"):
            async with self._client() as sqs:
                await sqs.delete_message(
                    QueueUrl=await self._url(sqs, self._name(queue)), ReceiptHandle=receipt
                )
        OUTCOMES.labels(subsystem="queue", outcome="deleted").inc()

    async def change_visibility(self, queue: Queues, receipt: str, visibility: timedelta) -> None:
        with translated("sqs", "change_visibility"):
            async with self._client() as sqs:
                await sqs.change_message_visibility(
                    QueueUrl=await self._url(sqs, self._name(queue)),
                    ReceiptHandle=receipt,
                    VisibilityTimeout=int(visibility.total_seconds()),
                )

    async def depth(self, queue: Queues) -> QueueDepth:
        with translated("sqs", "depth"):
            async with self._client() as sqs:
                url = await self._url(sqs, self._name(queue))
                response = await sqs.get_queue_attributes(
                    QueueUrl=url,
                    AttributeNames=[
                        "ApproximateNumberOfMessages",
                        "ApproximateNumberOfMessagesNotVisible",
                        "RedrivePolicy",
                    ],
                )
                attributes = response.get("Attributes", {})
                dead = 0
                redrive = attributes.get("RedrivePolicy")
                if redrive:
                    dead_name = json.loads(redrive)["deadLetterTargetArn"].rsplit(":", 1)[-1]
                    dead_response = await sqs.get_queue_attributes(
                        QueueUrl=await self._url(sqs, dead_name),
                        AttributeNames=["ApproximateNumberOfMessages"],
                    )
                    dead = int(dead_response["Attributes"]["ApproximateNumberOfMessages"])
        return QueueDepth(
            visible=int(attributes.get("ApproximateNumberOfMessages", "0")),
            in_flight=int(attributes.get("ApproximateNumberOfMessagesNotVisible", "0")),
            dead_lettered=dead,
        )

    def describe(self) -> str:
        return f"queues=sqs({self._endpoint_url or self._region})"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None
