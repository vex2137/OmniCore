"""Single-process settings event fan-out. Full snapshots coalesce for slow consumers."""

import asyncio
from contextlib import contextmanager

from omnicore.schemas import ServerEvent


class EventHub:
    def __init__(self):
        self.subscribers: set[asyncio.Queue[ServerEvent]] = set()

    @contextmanager
    def subscribe(self):
        queue: asyncio.Queue[ServerEvent] = asyncio.Queue(maxsize=32)
        self.subscribers.add(queue)
        try:
            yield queue
        finally:
            self.subscribers.discard(queue)

    @staticmethod
    def enqueue(queue: asyncio.Queue[ServerEvent], event: ServerEvent) -> None:
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(event)

    def publish(self, event: ServerEvent) -> None:
        for queue in self.subscribers:
            self.enqueue(queue, event)
