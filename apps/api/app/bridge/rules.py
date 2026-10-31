"""Чиста логика на bridge решенията — без I/O, за да е тестваема на единица."""

import hashlib
import time
from collections import deque
from dataclasses import dataclass, field


def mqtt_match(pattern: str, topic: str) -> bool:
    """MQTT topic match с + и # (поддържа и точен низ)."""
    if pattern == "#":
        return True
    p_parts = pattern.split("/")
    t_parts = topic.split("/")
    for i, pp in enumerate(p_parts):
        if pp == "#":
            return True
        if i >= len(t_parts):
            return False
        if pp != "+" and pp != t_parts[i]:
            return False
    return len(p_parts) == len(t_parts)


@dataclass
class Rule:
    kind: str  # 'allow' | 'deny'
    topic_pattern: str
    payload_type: str | None = None
    priority: int = 100
    reason: str = ""

    def matches(self, topic: str, payload_type: str) -> bool:
        if not mqtt_match(self.topic_pattern, topic):
            return False
        if self.payload_type is not None and self.payload_type != payload_type:
            return False
        return True


@dataclass
class Decision:
    action: str  # 'forward' | 'reject' | 'rate_limited' | 'loop_blocked' | 'skip'
    reason: str
    rule_id: str | None = None


class SlidingWindowLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._events: deque[float] = deque()

    def allow(self, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        while self._events and now - self._events[0] > 60:
            self._events.popleft()
        if len(self._events) >= self.per_minute:
            return False
        self._events.append(now)
        return True


class DedupeCache:
    """Защита срещу цикли втора линия: (тема, payload) наскоро препратени
    не се препращат втори път в рамките на TTL."""

    def __init__(self, ttl_s: float = 60.0, max_size: int = 4096):
        self.ttl_s = ttl_s
        self.max_size = max_size
        self._seen: dict[str, float] = {}

    def key(self, topic: str, payload: bytes) -> str:
        return hashlib.sha256(topic.encode() + b"\x00" + payload).hexdigest()

    def seen_recently(self, key: str, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        self._evict(now)
        exp = self._seen.get(key)
        return exp is not None and exp > now

    def add(self, key: str, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        self._evict(now)
        if len(self._seen) >= self.max_size:
            oldest = min(self._seen, key=self._seen.get)  # type: ignore[arg-type]
            del self._seen[oldest]
        self._seen[key] = now + self.ttl_s

    def _evict(self, now: float) -> None:
        if len(self._seen) < self.max_size // 2:
            return
        for k in [k for k, exp in self._seen.items() if exp <= now]:
            del self._seen[k]


@dataclass
class BridgePolicy:
    rules: list[Rule] = field(default_factory=list)
    rate_limit_per_min: int = 60
    limiter: SlidingWindowLimiter | None = None
    dedupe: DedupeCache | None = None

    def __post_init__(self) -> None:
        if self.limiter is None:
            self.limiter = SlidingWindowLimiter(self.rate_limit_per_min)
        if self.dedupe is None:
            self.dedupe = DedupeCache()

    def decide(
        self, topic: str, payload: bytes, payload_type: str, origin: str
    ) -> Decision:
        # 1) цикли: съобщение, което вече носи наш origin marker, не се препраща
        if origin != "local":
            return Decision("loop_blocked", f"origin marker: {origin}")
        # 2) цикли: dedupe наскоро препратени
        assert self.dedupe is not None
        key = self.dedupe.key(topic, payload)
        if self.dedupe.seen_recently(key):
            return Decision("loop_blocked", "dedupe: наскоро препратен (тема,payload)")
        # 3) правила — първото по приоритет, което пасва, решава
        for rule in sorted(self.rules, key=lambda r: r.priority):
            if rule.matches(topic, payload_type):
                if rule.kind == "deny":
                    return Decision(
                        "reject", rule.reason or f"deny правило: {rule.topic_pattern}"
                    )
                if not self.limiter.allow():
                    return Decision("rate_limited", "лимит съобщения/мин")
                self.dedupe.add(key)
                return Decision(
                    "forward", rule.reason or f"allow правило: {rule.topic_pattern}"
                )
        # 4) нищо не е позволило изрично -> не препращаме
        return Decision("reject", "няма пасващо allow правило (default deny)")


def map_topic(topic: str, topic_map: list[dict]) -> str:
    """topic_map: [{from_prefix, to_prefix}] — първият пасващ префект се заменя."""
    for m in topic_map:
        frm = m.get("from_prefix", "").rstrip("/")
        to = m.get("to_prefix", "").rstrip("/")
        if frm == "" or topic.startswith(frm + "/") or topic == frm:
            return (to + "/" + topic[len(frm):].lstrip("/")) if to else topic[len(frm):].lstrip("/")
    return topic
