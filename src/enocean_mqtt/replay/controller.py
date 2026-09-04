"""Replay runtime controller."""

from __future__ import annotations

from enocean_mqtt.replay.dolphinview_xml import DolphinViewXmlReader
from enocean_mqtt.replay.session import ReplaySession
from enocean_mqtt.replay.weinzierl_enolog import WeinzierlEnologReader

SUPPORTED_SQLITE_SUFFIXES = {
    ".enolog",
    ".sqlite",
    ".db",
}


class ReplayController:
    """Central replay lifecycle controller."""

    def __init__(self) -> None:
        self._session: ReplaySession | None = None

    @property
    def session(self) -> ReplaySession | None:
        """Return current replay session."""

        return self._session

    def start(self, session: ReplaySession) -> None:
        """Start replay session."""

        self._session = session
        session.mark_running()

    def finish(self) -> None:
        """Finish current replay session."""

        if self._session is not None:
            self._session.mark_finished()

        self._session = None

    def stop(self) -> None:
        """Stop current replay session."""

        if self._session is not None:
            self._session.mark_stopped()

        self._session = None

    def fail(self) -> None:
        """Fail current replay session."""

        if self._session is not None:
            self._session.mark_failed()

        self._session = None

    @staticmethod
    def create_reader(session: ReplaySession):
        """Create replay reader for current session."""

        capture_file = session.capture_file

        if capture_file.lower().endswith(".xml"):
            return DolphinViewXmlReader(capture_file)

        if any(
            capture_file.lower().endswith(suffix)
            for suffix in SUPPORTED_SQLITE_SUFFIXES
        ):
            return WeinzierlEnologReader(capture_file)

        raise ValueError(
            f"Unsupported replay file type: {capture_file}"
        )
