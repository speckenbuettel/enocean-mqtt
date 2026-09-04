"""DolphinView XML replay reader."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from enocean_mqtt.replay.models import ReplayTelegram


class DolphinViewXmlReader:
    """Read DolphinView XML capture files.

    The reader converts DolphinView telegram entries into normalized
    ReplayTelegram objects.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def iter_telegrams(
        self,
        limit: int | None = None,
    ):
        """Iterate over normalized replay telegrams."""

        tree = ElementTree.parse(self.path)
        root = tree.getroot()

        count = 0

        for telegram_id, telegram in enumerate(root.iter("Telegram"), start=1):
            if limit is not None and count >= limit:
                break

            rorg = telegram.attrib.get("RORG")
            data = telegram.attrib.get("Data")
            sender_id = telegram.attrib.get("ID")

            packet = telegram.find("Packet")

            raw_frame = None
            optional_data = None

            if packet is not None:
                raw_frame = packet.attrib.get("Data")
                optional_data = packet.attrib.get("OptionalData")

            replay_telegram = ReplayTelegram(
                telegram_id=telegram_id,
                timestamp=telegram.attrib.get("Timestamp"),
                protocol="EnOcean",
                telegram_type="Radio",
                direction=telegram.attrib.get("Direction"),
                eno_id=sender_id,
                eno_rorg=rorg,
                eno_data=data,
                eno_rssi=telegram.attrib.get("dBm"),
                raw_frame_data=raw_frame,
                raw_apdu_data=data,
                properties={},
                source="dolphin_view",
                destination_id=telegram.attrib.get("DestinationID"),
                status=telegram.attrib.get("Status"),
                port=telegram.attrib.get("Port"),
                optional_data=optional_data,
                subtelegram_count=_safe_int(
                    telegram.attrib.get("SubtelegramCount")
                ),
                security_level=_safe_int(
                    telegram.attrib.get("SecurityLevel")
                ),
                tick_count=_safe_int(
                    telegram.attrib.get("Tickcount")
                ),
            )

            yield replay_telegram

            count += 1



def _safe_int(value: str | None) -> int | None:
    """Safely convert optional integer values."""

    if value is None or value == "":
        return None

    try:
        return int(value)
    except ValueError:
        return None
