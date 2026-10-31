"""EMQX 5.8 Management REST API adapter (ADR-001: единственото място, което
знае за EMQX; останалият код говори с този интерфейс)."""

import time

import httpx

from ..config import settings


class BrokerUnavailable(Exception):
    pass


class EmqxAdapter:
    def __init__(self) -> None:
        s = settings()
        self._base = f"http://{s.emqx_host}:{s.emqx_api_port}/api/v5"
        self._user = s.emqx_dashboard_user
        self._password = s.emqx_dashboard_password
        self._client = httpx.AsyncClient(timeout=10)
        self._token: str | None = None
        self._token_exp: float = 0

    async def _login(self) -> None:
        r = await self._client.post(
            f"{self._base}/login",
            json={"username": self._user, "password": self._password},
        )
        r.raise_for_status()
        self._token = r.json()["token"]
        # EMQX токените живеят ~1 час; подновяваме на 45 минути
        self._token_exp = time.monotonic() + 45 * 60

    async def _req(
        self, method: str, path: str, json: dict | None = None, params: dict | None = None
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                if self._token is None or time.monotonic() > self._token_exp:
                    await self._login()
                r = await self._client.request(
                    method,
                    f"{self._base}{path}",
                    json=json,
                    params=params,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
                if r.status_code == 401 and attempt == 0:
                    self._token = None
                    continue
                return r
            except httpx.HTTPError as exc:
                last_exc = exc
                self._token = None
        raise BrokerUnavailable(str(last_exc))

    # --- статус и наблюдение ---

    async def status(self) -> dict:
        r = await self._req("GET", "/monitor_current")
        r.raise_for_status()
        stats = r.json()
        listeners = await self._req("GET", "/listeners")
        listeners.raise_for_status()
        return {
            "node_up": True,
            "connections": stats.get("connections", 0),
            "live_connections": stats.get("live_connections", 0),
            "topics": stats.get("topics", 0),
            "subscriptions": stats.get("subscriptions", 0),
            # monitor_current връща скорости (msg/s), не тотали
            "received_msg_rate": stats.get("received_msg_rate", 0),
            "sent_msg_rate": stats.get("sent_msg_rate", 0),
            "retained_msg_count": stats.get("retained_msg_count", 0),
            "listeners": [
                {
                    "id": l.get("id"),
                    "running": (l.get("status") or {}).get("running", False),
                    "bind": l.get("bind"),
                    "current_connections": (l.get("status") or {}).get(
                        "current_connections", 0
                    ),
                }
                for l in listeners.json()
            ],
        }

    async def clients(self, limit: int = 200) -> list[dict]:
        r = await self._req("GET", "/clients", params={"limit": limit})
        r.raise_for_status()
        return r.json().get("data", [])

    async def kick_client(self, client_id: str) -> None:
        r = await self._req("DELETE", f"/clients/{client_id}")
        if r.status_code not in (200, 204):
            r.raise_for_status()

    async def subscriptions(self, limit: int = 200) -> list[dict]:
        r = await self._req("GET", "/subscriptions", params={"limit": limit})
        r.raise_for_status()
        return r.json().get("data", [])

    # --- операции ---

    async def publish(self, topic: str, payload: str, qos: int = 0) -> None:
        r = await self._req(
            "POST",
            "/publish",
            json={"topic": topic, "payload": payload, "qos": qos, "retain": False},
        )
        if r.status_code not in (200, 204):
            r.raise_for_status()

    # --- MQTT потребители и ACL (built-in database) ---

    async def create_mqtt_user(self, username: str, password: str) -> None:
        r = await self._req(
            "POST",
            "/authentication/password_based:built_in_database/users",
            json={"user_id": username, "password": password, "is_superuser": False},
        )
        if r.status_code not in (200, 201, 204):
            raise BrokerUnavailable(f"create user -> {r.status_code}: {r.text}")

    async def delete_mqtt_user(self, username: str) -> None:
        r = await self._req(
            "DELETE", f"/authentication/password_based:built_in_database/users/{username}"
        )
        if r.status_code not in (200, 204, 404):
            raise BrokerUnavailable(f"delete user -> {r.status_code}: {r.text}")

    async def set_acl_rules(self, username: str, topics: list[str], action: str = "all") -> None:
        r = await self._req(
            "POST",
            "/authorization/sources/built_in_database/rules/users",
            json=[
                {
                    "username": username,
                    "rules": [
                        {
                            "permission": "allow",
                            "action": action,
                            "topic": t,
                            "qos": [0, 1, 2],
                            "retain": "all",
                        }
                        for t in topics
                    ],
                }
            ],
        )
        if r.status_code not in (200, 201, 204):
            raise BrokerUnavailable(f"set acl -> {r.status_code}: {r.text}")

    async def drop_acl_rules(self, username: str) -> None:
        r = await self._req(
            "DELETE",
            f"/authorization/sources/built_in_database/rules/users/{username}",
        )
        if r.status_code not in (200, 204, 404):
            raise BrokerUnavailable(f"drop acl -> {r.status_code}: {r.text}")

    async def close(self) -> None:
        await self._client.aclose()
