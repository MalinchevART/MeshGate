"""Bridge engine: управлява outbound връзките, прилага правилата, пише
журнал на решенията. Провал на външната връзка НЕ смущава локалния поток."""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

import aiomqtt
import asyncpg
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties as PahoProps

from ..config import settings
from .rules import BridgePolicy, Decision, Rule, map_topic

log = logging.getLogger("meshgate.bridge")


@dataclass
class BridgeState:
    id: str
    name: str
    remote_host: str
    remote_port: int
    remote_username: str | None = None
    remote_password: str | None = None
    topic_map: list[dict] = field(default_factory=list)
    policy: BridgePolicy = field(default_factory=BridgePolicy)
    direction: str = "outbound"  # outbound | bidirectional | inbound
    health: str = "unknown"  # up | down | unknown
    last_error: str | None = None
    counters: dict = field(
        default_factory=lambda: {"forwarded": 0, "rejected": 0, "rate_limited": 0, "loop_blocked": 0}
    )
    connected_at: float | None = None

    def new_counters(self) -> None:
        if self.direction == "inbound":
            self.counters = {"received": 0, "published": 0, "deduped": 0, "echo_blocked": 0}


class BridgeEngine:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.bridges: dict[str, BridgeState] = {}
        self._clients: dict[str, aiomqtt.Client] = {}
        self._local_pub = None  # inbound: локален издател към нашия брокер
        # кръстосан дедуп: един пакет, донесен от който и да е входящ мост,
        # влиза веднъж — копията от другите мостове се режат (и така не се
        # препращат наново към другия публичен брокер)
        self._inbound_seen = None  # DedupeCache, създава се в load()
        self._tasks: dict[str, asyncio.Task] = {}
        self._queues: dict[str, asyncio.Queue] = {}
        self._stop = asyncio.Event()

    # --- управление ---

    async def load(self) -> None:
        from .rules import DedupeCache

        if self._inbound_seen is None:
            self._inbound_seen = DedupeCache(ttl_s=120.0, max_size=16384)
        rows = await self.pool.fetch(
            "SELECT id, name, remote_host, remote_port, direction, remote_username,"
            " remote_password, topic_map, rate_limit_per_min"
            " FROM bridge_configs WHERE enabled"
        )
        wanted = {str(r["id"]) for r in rows}
        for bid in set(self.bridges) - wanted:
            await self._stop_bridge(bid)
        for r in rows:
            bid = str(r["id"])
            rules_rows = await self.pool.fetch(
                "SELECT kind, topic_pattern, payload_type, priority, reason"
                " FROM bridge_rules WHERE bridge_id = $1",
                r["id"],
            )
            policy = BridgePolicy(
                rules=[
                    Rule(
                        kind=x["kind"],
                        topic_pattern=x["topic_pattern"],
                        payload_type=x["payload_type"],
                        priority=x["priority"],
                        reason=x["reason"] or "",
                    )
                    for x in rules_rows
                ],
                rate_limit_per_min=r["rate_limit_per_min"],
            )
            if bid in self.bridges:
                self.bridges[bid].policy = policy
                self.bridges[bid].topic_map = json.loads(r["topic_map"])
                self.bridges[bid].remote_username = r["remote_username"]
                self.bridges[bid].remote_password = r["remote_password"]
            else:
                self.bridges[bid] = BridgeState(
                    id=bid,
                    name=r["name"],
                    remote_host=r["remote_host"],
                    remote_port=r["remote_port"],
                    remote_username=r["remote_username"],
                    remote_password=r["remote_password"],
                    topic_map=json.loads(r["topic_map"]),
                    policy=policy,
                    direction=r["direction"],
                )
                self.bridges[bid].new_counters()
                self._queues[bid] = asyncio.Queue(maxsize=1000)
                if r["direction"] == "inbound":
                    self._tasks[bid] = asyncio.create_task(self._inbound_loop(bid))
                else:
                    self._tasks[bid] = asyncio.create_task(self._bridge_loop(bid))
        log.info("bridge: заредени %d активни моста", len(self.bridges))

    async def reload(self) -> None:
        await self.load()

    def healthy(self) -> bool:
        return all(b.health != "down" for b in self.bridges.values()) if self.bridges else True

    def summary(self) -> list[dict]:
        return [
            {
                "id": b.id,
                "name": b.name,
                "health": b.health,
                "last_error": b.last_error,
                "counters": dict(b.counters),
            }
            for b in self.bridges.values()
        ]

    # --- входна точка от ingestion ---

    async def handle_local(self, topic: str, payload: bytes, payload_type: str, origin: str) -> None:
        for bid, state in self.bridges.items():
            decision = state.policy.decide(topic, payload, payload_type, origin)
            state.counters[decision.action] = state.counters.get(decision.action, 0) + 1
            await self._record(bid, decision, topic)
            if decision.action == "forward":
                ok, _ = self.enqueue(bid, map_topic(topic, state.topic_map), payload)
                if not ok:
                    await self._record(
                        bid,
                        Decision("reject", "изходна опашка пълна (бавен remote)"),
                        topic,
                    )

    def enqueue(
        self, bid: str, topic: str, payload: bytes, qos: int = 0, retain: bool = False
    ) -> tuple[bool, str | None]:
        """Публичен вход за routing engine-а: поставя съобщение в изходната
        опашка на активен мост. Връща (ok, причина при отказ)."""
        if bid not in self.bridges:
            return False, f"bridge {bid} не е активен"
        try:
            self._queues[bid].put_nowait((topic, payload, qos, retain))
            return True, None
        except asyncio.QueueFull:
            return False, "изходна опашка пълна (бавен remote)"

    async def _record(self, bridge_id: str, decision: Decision, topic: str) -> None:
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO bridge_events (bridge_id, decision, topic, reason, detail)"
                    " VALUES ($1,$2,$3,$4,$5::jsonb)",
                    bridge_id,
                    decision.action,
                    topic,
                    decision.reason,
                    json.dumps({"rule_id": decision.rule_id}),
                )
        except Exception:
            log.exception("bridge_events: записът пропадна")

    # --- връзка към remote ---

    async def _bridge_loop(self, bid: str) -> None:
        state = self.bridges[bid]
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with aiomqtt.Client(
                    hostname=state.remote_host,
                    port=state.remote_port,
                    identifier=f"meshgate-bridge-{bid[:8]}",
                    timeout=5.0,
                    # MQTT 5: публикуваме origin marker за защита срещу цикли
                    protocol=aiomqtt.ProtocolVersion.V5,
                    **self._auth_kwargs(state),
                ) as client:
                    state.health = "up"
                    state.connected_at = time.monotonic()
                    state.last_error = None
                    backoff = 1.0
                    log.info("bridge %s: свързан с %s:%s", state.name, state.remote_host, state.remote_port)
                    while not self._stop.is_set():
                        item = await self._queues[bid].get()
                        topic, payload, qos, retain = item
                        props = PahoProps(PacketTypes.PUBLISH)
                        props.UserProperty = [("mg_origin", f"bridge:{bid}")]
                        await client.publish(
                            topic, payload=payload, qos=qos, retain=retain, properties=props
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state.health = "down"
                state.last_error = str(exc)
                await self._set_health_db(bid, "down", str(exc))
                log.warning(
                    "bridge %s: remote недостъпен (%s), нов опит след %.1fs",
                    state.name,
                    exc,
                    backoff,
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                    break
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 30.0)

    async def _set_health_db(self, bid: str, health: str, error: str | None) -> None:
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE bridge_configs SET health=$1, last_error=$2,"
                    " last_error_at=now() WHERE id=$3",
                    health,
                    error,
                    bid,
                )
        except Exception:
            log.exception("bridge: не можах да запиша health")

    # --- inbound: външен брокер -> локалният (R2, по подразбиране изключено) ---

    @staticmethod
    def _auth_kwargs(state: "BridgeState") -> dict:
        if state.remote_username:
            return {"username": state.remote_username, "password": state.remote_password or ""}
        return {}

    async def _local_client(self):
        """Мързелив локален издател — съобщенията влизат през нормалния
        ingestion поток (запис + правила), само с origin маркер."""
        if self._local_pub is None:
            s = settings()
            self._local_pub = aiomqtt.Client(
                hostname=s.emqx_host,
                port=1883,
                username=s.emqx_ingest_user,
                password=s.emqx_ingest_password,
                identifier="meshgate-bridge-local",
                protocol=aiomqtt.ProtocolVersion.V5,
            )
            await self._local_pub.__aenter__()
        return self._local_pub

    async def _publish_local(self, topic: str, payload: bytes, origin_marker: str) -> None:
        props = PahoProps(PacketTypes.PUBLISH)
        props.UserProperty = [("mg_origin", origin_marker)]
        try:
            client = await self._local_client()
            await client.publish(topic, payload=payload, qos=0, properties=props)
        except Exception:
            # затваряме счупената връзка и пробваме веднъж пак
            try:
                if self._local_pub is not None:
                    await self._local_pub.__aexit__(None, None, None)
            except Exception:
                pass
            self._local_pub = None
            client = await self._local_client()
            await client.publish(topic, payload=payload, qos=0, properties=props)

    async def _inbound_loop(self, bid: str) -> None:
        """Абонира се за външния брокер и републикува локално. Защити:
        - ехо: съобщение, носещо чужд mg_origin (напр. наш ехо от remote), се
         .drop-ва — така цикълът distant -> local -> remote -> local се къса;
        - дедупликация (тема, payload) — публичните брокери републикуват едно
          и също от много gateway-и;
        - rate limit (съобщения/мин)."""
        from .rules import DedupeCache

        state = self.bridges[bid]
        dedupe = self._inbound_seen if self._inbound_seen is not None else DedupeCache(ttl_s=120.0)
        backoff = 1.0
        # какво слушаме отвън: от first topic_map entry (from_prefix), иначе '#'
        sub_pattern = "#"
        for m in state.topic_map:
            frm = (m.get("from_prefix") or "").strip("/")
            if frm:
                sub_pattern = frm + "/#"
                break
        while not self._stop.is_set():
            try:
                async with aiomqtt.Client(
                    hostname=state.remote_host,
                    port=state.remote_port,
                    identifier=f"meshgate-in-{bid[:8]}",
                    timeout=5.0,
                    protocol=aiomqtt.ProtocolVersion.V5,
                    **self._auth_kwargs(state),
                ) as client:
                    state.health = "up"
                    state.connected_at = time.monotonic()
                    state.last_error = None
                    backoff = 1.0
                    log.info(
                        "bridge %s (inbound): слушам %s:%s %s",
                        state.name, state.remote_host, state.remote_port, sub_pattern,
                    )
                    await client.subscribe(sub_pattern)
                    async for message in client.messages:
                        state.counters["received"] = state.counters.get("received", 0) + 1
                        topic = str(message.topic)
                        payload = bytes(message.payload)
                        # 1) ехо-защита: вече маркирано съобщение не се вдига
                        props = getattr(message, "properties", None)
                        user_props = getattr(props, "UserProperty", None) or []
                        if any(k == "mg_origin" for k, _ in user_props):
                            state.counters["echo_blocked"] = state.counters.get("echo_blocked", 0) + 1
                            continue
                        # 2) дедупликация (много gateway-и републикуват)
                        key = dedupe.key(topic, payload)
                        if dedupe.seen_recently(key):
                            state.counters["deduped"] = state.counters.get("deduped", 0) + 1
                            continue
                        # 3) rate limit
                        if state.policy.limiter and not state.policy.limiter.allow():
                            state.counters["rate_limited"] = state.counters.get("rate_limited", 0) + 1
                            continue
                        dedupe.add(key)
                        local_topic = map_topic(topic, state.topic_map) or topic
                        try:
                            await self._publish_local(local_topic, payload, f"bridge:{bid}")
                            state.counters["published"] = state.counters.get("published", 0) + 1
                        except Exception as exc:
                            state.last_error = f"local publish: {exc}"
                            log.warning("bridge %s inbound: %s", state.name, exc)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state.health = "down"
                state.last_error = str(exc)
                await self._set_health_db(bid, "down", str(exc))
                log.warning(
                    "bridge %s (inbound): remote недостъпен (%s), нов опит след %.1fs",
                    state.name, exc, backoff,
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                    break
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 30.0)

    async def _stop_bridge(self, bid: str) -> None:
        task = self._tasks.pop(bid, None)
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self.bridges.pop(bid, None)
        self._queues.pop(bid, None)

    async def stop(self) -> None:
        self._stop.set()
        for bid in list(self._tasks):
            await self._stop_bridge(bid)
        if self._local_pub is not None:
            try:
                await self._local_pub.__aexit__(None, None, None)
            except Exception:
                pass
            self._local_pub = None
