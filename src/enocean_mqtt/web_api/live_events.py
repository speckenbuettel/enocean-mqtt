"""Live SSE event distribution for Web UI."""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from typing import Any

logger = logging.getLogger(__name__)

SHUTDOWN_EVENT_TYPE = "shutdown"


class LiveEventQueue:
    """Thread-safe live event queue with async consumer API."""

    def __init__(self, max_queue_size: int | None = None) -> None:
        maxsize = max(max_queue_size or 0, 0)
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(
            maxsize=maxsize,
        )
        self._shutdown_requested = False
        self._clients = 0
        self._lock = threading.Lock()

    def connect(self) -> None:
        """Register a live consumer before accepting new events."""
        with self._lock:
            self._clients += 1

    def disconnect(self) -> None:
        """Discard pending live events when the last consumer leaves."""
        with self._lock:
            self._clients = max(0, self._clients - 1)
            if not self._clients:
                while True:
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        break

    def configure(self, max_queue_size: int | None = None) -> None:
        """Reconfigure queue size and clear buffered events."""

        maxsize = max(max_queue_size or 0, 0)
        self._queue = queue.Queue(maxsize=maxsize)
        self._shutdown_requested = False
        logger.debug("SSE live queue configured maxsize=%s", maxsize)

    def request_shutdown(self) -> None:
        """Request shutdown and wake one waiting SSE consumer."""

        self._shutdown_requested = True
        self.put_nowait({"event": SHUTDOWN_EVENT_TYPE})

    def put_nowait(self, payload: dict[str, Any]) -> None:
        """Publish one live event without blocking runtime processing."""

        with self._lock:
            if not self._clients:
                return
            self._put_nowait(payload)

    def _put_nowait(self, payload: dict[str, Any]) -> None:

        try:
            self._queue.put_nowait(payload)
            logger.debug(
                "SSE publish sender_id=%s rorg=%s event=%s",
                payload.get("sender_id"),
                payload.get("rorg"),
                payload.get("event"),
            )
        except queue.Full:
            logger.warning("SSE queue full; dropping oldest event")
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass

            self._queue.put_nowait(payload)

    async def get(self, *, poll: bool = False) -> dict[str, Any] | None:
        """Return one event without blocking the ASGI event loop."""

        while True:
            if self._shutdown_requested:
                return None

            try:
                payload = await asyncio.to_thread(
                    self._queue.get,
                    True,
                    0.5,
                )
            except queue.Empty:
                if poll:
                    raise TimeoutError("No live event available") from None
                continue

            if payload.get("event") == SHUTDOWN_EVENT_TYPE:
                return None

            logger.debug(
                "SSE consume sender_id=%s rorg=%s",
                payload.get("sender_id"),
                payload.get("rorg"),
            )
            return payload


LIVE_EVENT_QUEUE = LiveEventQueue()


def configure_live_event_queue(max_queue_size: int | None = None) -> None:
    """Configure the process-local live event queue."""

    LIVE_EVENT_QUEUE.configure(max_queue_size=max_queue_size)


def publish_live_event(payload: dict[str, Any]) -> None:
    """Publish one normalized live event into the SSE queue."""

    LIVE_EVENT_QUEUE.put_nowait(payload)


def request_live_event_shutdown() -> None:
    """Request live SSE stream shutdown."""

    LIVE_EVENT_QUEUE.request_shutdown()


async def get_live_event(*, poll: bool = False) -> dict[str, Any] | None:
    """Return the next live event without blocking the ASGI loop."""

    return await LIVE_EVENT_QUEUE.get(poll=poll)
