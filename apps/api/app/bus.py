import asyncio


class Bus:
    """In-process pub/sub за live потоците (WebSocket). Един uvicorn process —
    наложително ограничение докато bus-ът е в паметта."""

    def __init__(self, maxsize: int = 500):
        self._subs: set[asyncio.Queue] = set()
        self._maxsize = maxsize

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, event: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # бавен клиент: изпускаме най-старото, за да не блокира останалите
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass


bus = Bus()
