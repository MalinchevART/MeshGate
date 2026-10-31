"""Демо емулатор на MeshGate възли (v2).

Режим "meshtastic" (по подразбиране): публикува Meshtastic-подобен трафик —
темите са msh/emul/2/e/<канал>/!<hexid>, а payload е JSON ServiceEnvelope с
decoded.portnum (TEXT_MESSAGE/TELEMETRY/POSITION/NODEINFO), точно както го
описва docs/10-meshtastic-mqtt.md. Така целият вертикал (разпознаване →
правила → мониторинг → аларми) се тества без реално устройство.

Режим "legacy": старият опростен generic-MQTT поток върху mesh/emul/…

Употреба (в контейнер):  docker compose --profile demo up -d emulator
Самостоятелно:  python nodes.py  (env: EMQX_HOST, EMU_USER, EMU_PASS, EMULATOR_MODE, ...)
"""

import json
import os
import random
import time
import uuid

import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion

EMQX_HOST = os.environ.get("EMQX_HOST", "localhost")
EMU_USER = os.environ.get("EMU_USER", "meshgate-emulator")
EMU_PASS = os.environ.get("EMU_PASS", "")
NODES = int(os.environ.get("EMULATOR_NODES", "6"))
INTERVAL = float(os.environ.get("EMULATOR_INTERVAL", "5"))
MODE = os.environ.get("EMULATOR_MODE", "meshtastic")
MESH_REGION = os.environ.get("EMULATOR_MESH_REGION", "emul")
MESH_CHANNEL = os.environ.get("EMULATOR_MESH_CHANNEL", "LongFast")

TEXTS = [
    "на линия съм",
    "батерията пада бавно",
    "има ли някой на ретранслатора?",
    "тестов пакет от хълма",
    "температурата се вдига",
    "приемам слабо на канала",
]


class Node:
    def __init__(self, idx: int):
        self.id = f"node{idx}-{uuid.uuid4().hex[:4]}"
        # числовият NodeNum и hex id са ЕДНО И СЪЩО число при реалните
        # възли (темата е !%08x на NodeNum) — така NeighborInfo съседите
        # съвпадат с възлите на картата
        self.from_id = random.randint(0x10000000, 0x7FFFFFFF)
        self.hex_id = f"!{self.from_id:08x}"  # Meshtastic-формат node id
        # уникален packet id за всеки envelope (реалните възли също никога не
        # повтарят id; платформата дедупликира по него)
        self.pkt_seq = random.randint(0, 0xFFFF)
        self.temp = random.uniform(15, 26)
        self.hum = random.uniform(40, 70)
        self.bat = random.uniform(60, 100)
        self.rssi = random.uniform(-95, -55)
        self.snr = random.uniform(2, 12)
        self.lat = 42.69 + random.uniform(-0.05, 0.05)
        self.lng = 23.32 + random.uniform(-0.05, 0.05)
        self.tick = 0

    def step(self):
        self.tick += 1
        self.temp += random.uniform(-0.4, 0.4)
        self.hum += random.uniform(-1.5, 1.5)
        self.bat = max(5.0, self.bat - random.uniform(0, 0.05))
        self.rssi += random.uniform(-3, 3)
        self.snr += random.uniform(-0.5, 0.5)
        self.lat += random.uniform(-0.0005, 0.0005)
        self.lng += random.uniform(-0.0005, 0.0005)

    def telemetry(self) -> tuple[str, str]:
        return (
            f"mesh/emul/{self.id}/up",
            json.dumps(
                {
                    "node": self.id,
                    "temp": round(self.temp, 1),
                    "hum": round(self.hum, 0),
                    "battery": round(self.bat, 0),
                    "rssi": round(self.rssi, 0),
                    "snr": round(self.snr, 1),
                    "uptime_s": self.tick * INTERVAL,
                }
            ),
        )

    def position(self) -> tuple[str, str]:
        return (
            f"mesh/emul/{self.id}/pos",
            json.dumps(
                {"node": self.id, "lat": round(self.lat, 5), "lng": round(self.lng, 5)}
            ),
        )

    def text(self) -> tuple[str, str]:
        return (
            f"mesh/emul/{self.id}/msg",
            json.dumps({"node": self.id, "text": random.choice(TEXTS)}),
        )

    def private(self) -> tuple[str, str]:
        return (
            f"mesh/emul/{self.id}/priv",
            json.dumps({"node": self.id, "note": "лично съобщение – не се препраща"}),
        )


    # ---- Meshtastic-режим (v2): msh/<region>/2/e/<channel>/!<hex> + JSON envelope ----

    def mesh_topic(self) -> str:
        return f"msh/{MESH_REGION}/2/e/{MESH_CHANNEL}/{self.hex_id}"

    def _envelope(self, portnum: str, decoded: dict) -> str:
        self.pkt_seq = (self.pkt_seq + 1) & 0xFFFFFFFF
        return json.dumps(
            {
                "id": self.pkt_seq,
                "timestamp": int(time.time()),
                "to": -1,  # broadcast
                "from": self.from_id,
                "sender": self.hex_id,
                "channel": 0,
                "decoded": {"portnum": portnum, **decoded},
            }
        )

    def mesh_telemetry(self) -> tuple[str, str]:
        return self.mesh_topic(), self._envelope(
            "TELEMETRY_APP",
            {
                "telemetry": {
                    "device_metrics": {
                        "battery_level": round(self.bat),
                        "voltage": round(self.bat / 25, 2),
                        "channel_utilization": round(random.uniform(10, 40), 1),
                        "air_util_tx": round(random.uniform(0.5, 4), 2),
                    },
                    "environment_metrics": {
                        "temperature": round(self.temp, 1),
                        "relative_humidity": round(self.hum, 0),
                    },
                }
            },
        )

    def mesh_position(self) -> tuple[str, str]:
        return self.mesh_topic(), self._envelope(
            "POSITION_APP",
            {"position": {"latitude_i": int(self.lat * 1e7), "longitude_i": int(self.lng * 1e7), "altitude": 580}},
        )

    def mesh_text(self) -> tuple[str, str]:
        return self.mesh_topic(), self._envelope(
            "TEXT_MESSAGE_APP", {"text": random.choice(TEXTS)}
        )

    def mesh_nodeinfo(self) -> tuple[str, str]:
        return self.mesh_topic(), self._envelope(
            "NODEINFO_APP",
            {
                "user": {
                    "id": self.hex_id,
                    "long_name": f"Демо възел {self.id}",
                    "short_name": f"N{self.tick % 100:02d}",
                    "hw_model": "HELTEC_V3",
                }
            },
        )

    def mesh_neighborinfo(self, all_nodes: list["Node"]) -> tuple[str, str]:
        # всеки възел „чува" 1–3 случайни съседа с реалистичен SNR —
        # суровина за топологията (кой кого чу) върху Картата
        others = [n for n in all_nodes if n is not self]
        picked = random.sample(others, k=min(len(others), random.randint(1, 3)))
        neighbors = [
            {"node_id": n.from_id, "snr": round(random.uniform(-16, 8), 1)}
            for n in picked
        ]
        return self.mesh_topic(), self._envelope(
            "NEIGHBORINFO_APP",
            {"neighborinfo": {"node_id": self.from_id, "neighbors": neighbors}},
        )


def main() -> None:
    nodes = [Node(i + 1) for i in range(NODES)]
    cli = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=f"meshgate-emu-{uuid.uuid4().hex[:6]}")
    if EMU_PASS:
        cli.username_pw_set(EMU_USER, EMU_PASS)

    # пауза/продължи на тестовите възли през контролна тема (UI бутон):
    # payload "pause" спира публикуването, "resume" го връща
    state = {"paused": False}

    def on_message(_c, _u, msg):
        cmd = (msg.payload or b"").decode("utf-8", "replace").strip().lower()
        if cmd == "pause":
            state["paused"] = True
            print("емулатор: ПАУЗА (тестовите възли мълчат)", flush=True)
        elif cmd == "resume":
            state["paused"] = False
            print("емулатор: продължава", flush=True)

    cli.on_message = on_message
    cli.connect(EMQX_HOST, 1883, keepalive=30)
    cli.loop_start()
    cli.subscribe("mesh/emul/ctrl")
    print(f"емулатор: {NODES} възли -> {EMQX_HOST}, интервал {INTERVAL}s", flush=True)
    print(f"емулатор: режим {MODE} (контролна тема mesh/emul/ctrl: pause/resume)", flush=True)
    try:
        while True:
            if state["paused"]:
                time.sleep(INTERVAL)
                continue
            for node in nodes:
                node.step()
                if MODE == "meshtastic":
                    for topic, payload in (
                        node.mesh_telemetry(),
                        *( [node.mesh_position()] if node.tick % 6 == 0 else [] ),
                        *( [node.mesh_text()] if node.tick % 7 == 0 else [] ),
                        *( [node.mesh_nodeinfo()] if node.tick % 30 == 0 else [] ),
                        *( [node.mesh_neighborinfo(nodes)] if node.tick % 12 == 0 else [] ),
                    ):
                        cli.publish(topic, payload, qos=0)
                else:
                    topic, payload = node.telemetry()
                    cli.publish(topic, payload, qos=0)
                    if node.tick % 6 == 0:
                        t2, p2 = node.position()
                        cli.publish(t2, p2, qos=0)
                    if node.tick % 7 == 0:
                        t3, p3 = node.text()
                        cli.publish(t3, p3, qos=0)
                    if node.tick % 30 == 0:
                        t4, p4 = node.private()
                        cli.publish(t4, p4, qos=0)
            time.sleep(INTERVAL)
    finally:
        cli.loop_stop()
        cli.disconnect()


if __name__ == "__main__":
    main()
