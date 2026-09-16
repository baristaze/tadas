import json
from datetime import timedelta
from typing import Any

import aioboto3

from tadas.infra.queues import QueueDepth, QueueInterface, QueueMessage, Queues


class QueueSqsImpl(QueueInterface):
    def __init__(
        self,
        session: aioboto3.Session,
        *,
        endpoint_url: str | None,
        region: str,
        queue_prefix: str,
    ) -> None:
        self._session = session
        self._endpoint_url = endpoint_url
        self._region = region
        self._queue_prefix = queue_prefix
        self._urls: dict[str, str] = {}

    def _client(self) -> Any:
        return self._session.client(
            "sqs", endpoint_url=self._endpoint_url, region_name=self._region
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
        async with self._client() as sqs:
            response = await sqs.send_message(
                QueueUrl=await self._url(sqs, self._name(queue)),
                MessageBody=body.decode(),
                MessageAttributes=attributes,
            )
        return response["MessageId"]

    async def receive(
        self, queue: Queues, max_messages: int, wait: timedelta, visibility: timedelta
    ) -> list[QueueMessage]:
        async with self._client() as sqs:
            response = await sqs.receive_message(
                QueueUrl=await self._url(sqs, self._name(queue)),
                MaxNumberOfMessages=max(1, min(max_messages, 10)),
                WaitTimeSeconds=int(min(wait.total_seconds(), 20)),
                VisibilityTimeout=int(visibility.total_seconds()),
                AttributeNames=["ApproximateReceiveCount"],
            )
        return [
            QueueMessage(
                id=m["MessageId"],
                body=m["Body"].encode(),
                receipt=m["ReceiptHandle"],
                attempts=int(m.get("Attributes", {}).get("ApproximateReceiveCount", "1")),
            )
            for m in response.get("Messages", [])
        ]

    async def delete(self, queue: Queues, receipt: str) -> None:
        async with self._client() as sqs:
            await sqs.delete_message(
                QueueUrl=await self._url(sqs, self._name(queue)), ReceiptHandle=receipt
            )

    async def change_visibility(self, queue: Queues, receipt: str, visibility: timedelta) -> None:
        async with self._client() as sqs:
            await sqs.change_message_visibility(
                QueueUrl=await self._url(sqs, self._name(queue)),
                ReceiptHandle=receipt,
                VisibilityTimeout=int(visibility.total_seconds()),
            )

    async def depth(self, queue: Queues) -> QueueDepth:
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
