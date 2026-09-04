from concurrent.futures import ThreadPoolExecutor

from enocean_mqtt.runtime.event import RuntimeTelegramEvent
from enocean_mqtt.storage.sqlite_store import SQLiteRuntimeStore


def _event(index: int, direction: str) -> RuntimeTelegramEvent:
    return RuntimeTelegramEvent(
        timestamp_local=None,
        timestamp_unix=float(index),
        direction=direction,
        raw_telegram="F670052523B100",
        rorg="F6",
        sender_id="052523B1",
        data="70",
        erp1_status="00",
        interface_id="usb300",
    )


def test_concurrent_rx_and_tx_persistence_uses_atomic_transactions(tmp_path) -> None:
    store = SQLiteRuntimeStore(str(tmp_path / "runtime.sqlite"))
    event_count = 400

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(
                    store.persist_event,
                    _event(index, "rx" if index % 2 == 0 else "tx"),
                )
                for index in range(event_count)
            ]
            for future in futures:
                future.result()

        row = store.connection.execute(
            "SELECT COUNT(*) AS telegram_count FROM telegrams"
        ).fetchone()
        assert row is not None
        assert row["telegram_count"] == event_count
    finally:
        store.close()
