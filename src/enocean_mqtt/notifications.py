"""Pushover delivery and a bounded background queue for runtime notifications."""

from __future__ import annotations

import http.client
import json
import logging
import re
import threading
import time
from pathlib import Path
from queue import Empty, Full, Queue
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field

from enocean_mqtt.runtime_config import PushoverConfig

LOGGER = logging.getLogger(__name__)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]{30}")


class Notification(BaseModel):
    """Transport-independent message, also usable by future threshold rules."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    message: str = Field(min_length=1, max_length=1024)
    title: str = Field(default="enocean-mqtt", max_length=250)


class NotificationError(Exception):
    """Safe delivery error containing no credentials or remote response body."""


def validate_token(value: str) -> str:
    value = value.strip()
    if not TOKEN_PATTERN.fullmatch(value):
        raise NotificationError("Pushover tokens must contain 30 alphanumeric characters")
    return value


class PushoverClient:
    def __init__(self, config: PushoverConfig) -> None:
        self.config = config

    def send(self, notification: Notification) -> None:
        """Send once; a timeout may mean delivery succeeded, so do not retry blindly."""
        if not self.config.enabled:
            raise NotificationError("Pushover is disabled")
        try:
            user = validate_token(Path(self.config.user_token_file).read_text(encoding="utf-8"))
            token = validate_token(Path(self.config.api_token_file).read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            raise NotificationError("Pushover token files are missing or unreadable") from None

        fields = {
            "token": token,
            "user": user,
            "message": notification.message,
            "title": notification.title,
            "priority": str(self.config.priority),
        }
        if self.config.device:
            fields["device"] = self.config.device
        connection = http.client.HTTPSConnection(
            "api.pushover.net", timeout=self.config.timeout_seconds,
        )
        try:
            connection.request(
                "POST", "/1/messages.json", body=urlencode(fields),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response = connection.getresponse()
            if response.status != 200:
                raise NotificationError(f"Pushover rejected the request (HTTP {response.status})")
            payload = json.loads(response.read(65536))
            if not isinstance(payload, dict) or payload.get("status") != 1:
                raise NotificationError("Pushover did not accept the message")
        except (OSError, http.client.HTTPException, ValueError):
            raise NotificationError(
                "Pushover delivery failed (connection or invalid response)"
            ) from None
        finally:
            connection.close()


class NotificationService:
    """Keep HTTP away from telegram/MQTT processing; failures never stop the gateway."""

    def __init__(self, config: PushoverConfig, application_name: str) -> None:
        self.config = config
        self._title = application_name[:250]
        self._client = PushoverClient(config)
        self._queue: Queue[Notification] = Queue(maxsize=100)
        self._lock = threading.Lock()
        self._closing = threading.Event()
        self._last_error: float | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.config.enabled and self._thread is None:
            self._thread = threading.Thread(target=self._run, name="pushover", daemon=True)
            self._thread.start()

    def notify(self, notification: Notification) -> bool:
        """Return queue acceptance, not delivery confirmation."""
        with self._lock:
            if not self.config.enabled or self._closing.is_set():
                return False
            try:
                self._queue.put_nowait(notification)
            except Full:
                LOGGER.warning("Pushover queue full; notification dropped")
                return False
        return True

    def gateway_started(self) -> None:
        if self.config.notify_start:
            self.notify(Notification(title=self._title, message="Gateway started."))

    def gateway_stopped(self) -> None:
        if self.config.notify_stop:
            self.notify(Notification(title=self._title, message="Gateway is shutting down."))

    def gateway_error(self, component: str, message: str) -> None:
        if not self.config.enabled or not self.config.notify_errors:
            return
        with self._lock:
            now = time.monotonic()
            if (
                self._last_error is not None
                and now - self._last_error < self.config.error_cooldown_seconds
            ):
                return
            self._last_error = now
        self.notify(Notification(title=self._title, message=f"{component}: {message}"[:1024]))

    def close(self) -> None:
        with self._lock:
            self._closing.set()
        if self._thread is not None:
            self._thread.join(timeout=self.config.timeout_seconds + 1)

    def _run(self) -> None:
        while not self._closing.is_set() or not self._queue.empty():
            try:
                notification = self._queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                self._client.send(notification)
            except NotificationError as exc:
                LOGGER.warning("%s", exc)
            finally:
                self._queue.task_done()
