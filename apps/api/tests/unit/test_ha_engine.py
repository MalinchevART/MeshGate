"""Модулни тестове на Home Assistant адаптера (docs/13 §1)."""
import json

import pytest

from app.integrations.ha_engine import HomeAssistantEngine, discovery_config


def test_discovery_config_shapes():
    bat = discovery_config("!a1b2c3d4", "battery")
    assert bat["unique_id"] == "meshgate_a1b2c3d4_battery"
    assert bat["state_topic"] == "meshgate/!a1b2c3d4/battery"
    assert bat["device_class"] == "battery"
    assert bat["device"]["identifiers"] == ["meshgate_a1b2c3d4"]
    assert bat["device"]["name"] == "MeshGate !a1b2c3d4"

    snr = discovery_config("!a1b2c3d4", "snr")
    assert snr["unit_of_measurement"] == "dB"
    msg = discovery_config("!a1b2c3d4", "message")
    assert msg["name"] == "Последно съобщение"

    with pytest.raises(ValueError):
        discovery_config("!a1b2c3d4", "nope")


class _Engine(HomeAssistantEngine):
    """Без база: публикациите отиват в списък вместо в брокера."""

    def __init__(self):
        super().__init__(pool=None)
        self.published: list[tuple[str, str, bool]] = []

    async def _publish(self, topic, payload, retain):
        self.published.append((topic, payload, retain))

    @staticmethod
    def _now():
        return 1000.0


@pytest.mark.asyncio
async def test_update_publishes_config_once_and_throttles_state(monkeypatch):
    e = _Engine()
    e.enabled = True
    # детерминистично време за тротъла
    clock = {"t": 1000.0}
    monkeypatch.setattr("app.integrations.ha_engine.time.monotonic", lambda: clock["t"])

    decoded = {"node": "!ab12cd34", "battery": 55, "snr": -7.5, "text": "здравей"}
    await e._update("!ab12cd34", decoded)
    topics = [t for t, _, _ in e.published]
    # конфиг веднъж на сензор (retain) + състояние
    assert topics.count("homeassistant/sensor/meshgate_ab12cd34/battery/config") == 1
    assert topics.count("homeassistant/sensor/meshgate_ab12cd34/message/config") == 1
    assert "meshgate/!ab12cd34/battery" in topics
    assert "meshgate/!ab12cd34/message" in topics
    state = dict((t, p) for t, p, _ in e.published)["meshgate/!ab12cd34/battery"]
    assert state == "55"
    msg = dict((t, p) for t, p, _ in e.published)["meshgate/!ab12cd34/message"]
    assert msg == "здравей"

    # втори пакет в рамките на 20s → само конфигите не се повтарят, състоянията се тротълват
    n_before = len(e.published)
    clock["t"] += 5.0
    await e._update("!ab12cd34", {**decoded, "battery": 44})
    assert len(e.published) == n_before  # нищо ново

    # след паузата състоянието се обновява, конфигът — не
    clock["t"] += 25.0
    await e._update("!ab12cd34", {**decoded, "battery": 33})
    topics2 = [t for t, _, _ in e.published]
    assert topics2.count("homeassistant/sensor/meshgate_ab12cd34/battery/config") == 1
    new_state = [p for t, p, _ in e.published if t == "meshgate/!ab12cd34/battery"]
    assert new_state == ["55", "33"]
    assert e.entities["!ab12cd34"] == ["battery", "snr", "message"]


@pytest.mark.asyncio
async def test_handle_local_gates():
    e = _Engine()
    e.enabled = False
    e.handle_local("msh/x", {"node": "!ab12cd34", "battery": 5}, "local")
    assert e._queue.qsize() == 0

    e.enabled = True
    e.handle_local("mesh/x", None, "local")  # без decoded → пропуск
    assert e._queue.qsize() == 0
    e.handle_local("msh/x", {"node": "not-a-node"}, "local")  # node без ! → пропуск
    assert e._queue.qsize() == 0
    e.handle_local("msh/x", {"node": "!ab12cd34", "battery": 5}, "local")
    assert e._queue.qsize() == 1
