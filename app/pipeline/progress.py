"""Pipeline progress tracking via in-memory event bus for SSE streaming."""

import asyncio
import time
from typing import Any, Dict, Optional
from collections import defaultdict

from app.utils.logger import get_logger

logger = get_logger("pipeline.progress")


class PipelineProgress:
    """Per-pipeline progress tracker. Nodes call `emit()`, SSE endpoint reads `listen()`."""

    def __init__(self, topic_id: str):
        self.topic_id = topic_id
        self.started_at = time.time()
        self._queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._done = False

    def emit(self, stage: str, status: str, detail: str = "", **extra: Any):
        event = {
            "stage": stage,
            "status": status,
            "detail": detail,
            "elapsed": round(time.time() - self.started_at, 1),
            **extra,
        }
        self._queue.put_nowait(event)

    def finish(self):
        self._done = True
        self._queue.put_nowait({"stage": "__done__", "status": "complete", "elapsed": round(time.time() - self.started_at, 1)})

    async def listen(self):
        while True:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=2.0)
                yield event
                if event.get("stage") == "__done__":
                    return
            except asyncio.TimeoutError:
                yield {"stage": "__heartbeat__", "status": "alive", "elapsed": round(time.time() - self.started_at, 1)}


_active: Dict[str, PipelineProgress] = {}


def create_tracker(topic_id: str) -> PipelineProgress:
    tracker = PipelineProgress(topic_id)
    _active[topic_id] = tracker
    return tracker


def get_tracker(topic_id: str) -> Optional[PipelineProgress]:
    return _active.get(topic_id)


def remove_tracker(topic_id: str):
    _active.pop(topic_id, None)
