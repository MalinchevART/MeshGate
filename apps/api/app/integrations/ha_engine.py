"""Home Assistant адаптер (docs/13 §1): Meshtastic възлите стават сензори в
Home Assistant чрез MQTT discovery.

За всеки възел (!hex) се публикуват (retain) discovery конфигурации на
homeassistant/sensor/meshgate_<hex>/<сенз>/config и състояния на
meshgate/<възел>/<сенз> — батерия %, SNR dB и последно текстово съобщение.
Всички сензори на един възел се групират в едно HA устройство.

Публикациите минават през ingest.publish_local с origin marker „ha:meshgate“
(игнорира се от routing engine-а → няма цикъл). Състоянията се тротълват
минимум на MIN_STATE_INTERVAL_S, конфигурацията се праща веднъж на старт
(remain retained на брокера за рестарти на HA)."""

import asyncio
import json
import logging
import time

import asyncpg

log = logging.getLogger("meshgate.ha")

QUEUE_MAX = 500
MIN_STATE_INTERVAL_S = 20.0
NODE_PREFIXES = ("!",)  # Meshtastic възли


def _hex_id(node: str) -> str:
    return node.lstrip("!")


def discovery_config(node: str, entity: str) -> dict:
    """HA MQTT discovery конфиг за един сензор на възела."""
    hex_id = _hex_id(node)
    common = {
        "unique_id": f"meshgate_{hex_id}_{entity}",
        "state_topic": f"meshgate/{node}/{entity}",
        "device": {
            "identifiers": [f"meshgate_{hex_id}"],
            "name": f"MeshGate {node}",
            "manufacturer": "MeshGate",
            "model": "Meshtastic възел",
        },
    }
    if entity == "battery":
        return {
            **common,
            "name": "Батерия",
            "device_class": "battery",
            "unit_of_measurement": "%",
            "state_class": "measurement",
        }
    if entity == "snr":
        return {
            **common,
            "name": "SNR",
            "unit_of_measurement": "dB",
            "state_class": "measurement",
        }
    if entity == "message":
        return {**common, "name": "Последно съобщение", "icon": "mdi:message-text"}
    if entity == "channel":
        # реалното групиране: в HA може да филтрираш/групираш възли по канал
        return {**common, "name": "Канал", "icon": "mdi:tag"}
    raise ValueError(f"непознат сензор {entity!r}")


class HomeAssistantEngine:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.enabled = False
        self.ingest = None  # свързва се в main.py (публикация през ingest)
        self.entities: dict[str, list[str]] = {}  # възел → сензори (за статус)
        self._published_configs: set[tuple[str, str]] = set()
        self._last_state: dict[tuple[str, str], float] = {}
        self._queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue(QUEUE_MAX)
        self._stop = asyncio.Event()
        self._worker: asyncio.Task | None = None
        self.published = 0

    async def load(self) -> None:
        row = await self.pool.fetchrow(
            "SELECT value FROM settings WHERE key = 'homeassistant'"
        )
        self.enabled = bool(row and json.loads(row["value"]).get("enabled"))
        log.info("home assistant: %s", "включен" if self.enabled else "изключен")

    def start(self) -> None:
        self._worker = asyncio.create_task(self._run(), name="ha-adapter")

    async def stop(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except (asyncio.CancelledError, Exception):
                pass

    # --- входна точка от ingest (неблокиращо) ------------------------------

    def handle_local(self, topic: str, decoded: dict | None, origin: str) -> None:
        if not self.enabled or not decoded:
            return
        node = decoded.get("node")
        if not isinstance(node, str) or not node.startswith(NODE_PREFIXES):
            return
        try:
            self._queue.put_nowait((node, decoded))
        except asyncio.QueueFull:
            log.warning("home assistant: опашката е пълна — пропускам %s", node)

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                node, decoded = await self._queue.get()
                await self._update(node, decoded)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("home assistant: грешка в работника")

    async def _publish(self, topic: str, payload: str, retain: bool) -> None:
        if self.ingest is None:
            return
        await self.ingest.publish_local(
            topic, payload.encode("utf-8"), "ha:meshgate", qos=1, retain=retain
        )
        self.published += 1

    async def _update(self, node: str, decoded: dict) -> None:
        now = time.monotonic()
        ents = self.entities.setdefault(node, [])
        for entity, value in (
            ("battery", decoded.get("battery")),
            ("snr", decoded.get("snr")),
            ("message", decoded.get("text")),
            ("channel", decoded.get("channel")),
        ):
            if value is None:
                continue
            if entity not in ents:
                ents.append(entity)
            # discovery конфигът се праща веднъж на процес (retain на брокера)
            if (node, entity) not in self._published_configs:
                cfg = discovery_config(node, entity)
                await self._publish(
                    f"homeassistant/sensor/meshgate_{_hex_id(node)}/{entity}/config",
                    json.dumps(cfg, ensure_ascii=False),
                    retain=True,
                )
                self._published_configs.add((node, entity))
            # тротъл на състоянието
            key = (node, entity)
            if now - self._last_state.get(key, 0.0) < MIN_STATE_INTERVAL_S:
                continue
            self._last_state[key] = now
            # цели числа без десетични (55, не 55.0); дробните с 1 знак
            state = (format(float(value), "g")
                     if isinstance(value, (int, float)) else str(value))
            await self._publish(f"meshgate/{node}/{entity}", str(state), retain=True)

    async def publish_test(self) -> str:
        """Бутон „Тест“: изкуствен възел !test1234, за да се види в HA веднага."""
        node = "!test1234"
        for entity, value in (("battery", 99), ("message", "тестово от MeshGate")):
            cfg = discovery_config(node, entity)
            await self._publish(
                f"homeassistant/sensor/meshgate_{_hex_id(node)}/{entity}/config",
                json.dumps(cfg, ensure_ascii=False), retain=True,
            )
            await self._publish(f"meshgate/{node}/{entity}", str(value), retain=True)
        self.entities.setdefault(node, ["battery", "message"])
        return node

    def counters(self) -> dict:
        nodes = len(self.entities)
        return {
            "enabled": self.enabled,
            "nodes": nodes,
            "entities": sum(len(v) for v in self.entities.values()),
            "published": self.published,
        }
