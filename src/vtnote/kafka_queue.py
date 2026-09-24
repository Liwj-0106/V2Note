"""At-least-once Kafka transport for durable stage-run identifiers."""

from __future__ import annotations

import json
from typing import Any

from kafka import KafkaConsumer, KafkaProducer


class KafkaStageQueue:
    """Publish stage IDs and commit Kafka offsets only after DB transitions."""

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        topic: str,
        consumer_group: str,
    ) -> None:
        servers = [value.strip() for value in bootstrap_servers.split(",") if value.strip()]
        if not servers or not topic or not consumer_group:
            raise ValueError("Kafka bootstrap servers, topic and group are required")
        self.topic = topic
        self.producer = KafkaProducer(
            bootstrap_servers=servers,
            acks="all",
            retries=8,
            max_in_flight_requests_per_connection=1,
            key_serializer=lambda value: value.encode("utf-8"),
            value_serializer=lambda value: json.dumps(
                value, separators=(",", ":")
            ).encode("utf-8"),
        )
        self.consumer = KafkaConsumer(
            topic,
            bootstrap_servers=servers,
            group_id=consumer_group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            key_deserializer=lambda value: value.decode("utf-8") if value else None,
            value_deserializer=self._decode,
            max_poll_records=1,
        )
        self._pending_offset = False

    @staticmethod
    def _decode(value: bytes) -> dict[str, Any]:
        parsed = json.loads(value.decode("utf-8"))
        if not isinstance(parsed, dict) or set(parsed) != {"stage_run_id"}:
            raise ValueError("invalid Kafka stage message")
        stage_run_id = parsed["stage_run_id"]
        if not isinstance(stage_run_id, str) or len(stage_run_id) != 36:
            raise ValueError("invalid Kafka stage identifier")
        return parsed

    def publish(self, stage_run_id: str) -> None:
        self.producer.send(
            self.topic,
            key=stage_run_id,
            value={"stage_run_id": stage_run_id},
        ).get(timeout=15)

    def receive(self, *, timeout_ms: int = 1000) -> str | None:
        records = self.consumer.poll(timeout_ms=timeout_ms, max_records=1)
        for partition_records in records.values():
            if not partition_records:
                continue
            self._pending_offset = True
            return str(partition_records[0].value["stage_run_id"])
        return None

    def acknowledge(self) -> None:
        if self._pending_offset:
            self.consumer.commit()
            self._pending_offset = False

    def close(self) -> None:
        self.consumer.close(autocommit=False)
        self.producer.flush(timeout=5)
        self.producer.close(timeout=5)
