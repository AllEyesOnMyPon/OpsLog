from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx


class Breaker:
    def __init__(
        self, failure_threshold: float = 0.2, window_sec: int = 30, half_open_after_sec: int = 20
    ):
        """
        failure_threshold: odsetek błędów (0.0–1.0), po którym breaker przechodzi w OPEN.
        window_sec:        (na przyszłość) szerokość okna; na razie liczymy prosto.
        half_open_after_sec: czas „ochłonięcia” zanim spróbujemy ponownie.
        """
        self.failure_threshold = failure_threshold
        self.window_sec = window_sec
        self.half_open_after_sec = half_open_after_sec
        self._fail_count = 0
        self._total_count = 0
        self._open_until = 0.0

    def record(self, ok: bool) -> None:
        self._total_count += 1
        if not ok:
            self._fail_count += 1

    def should_open(self) -> bool:
        if self._total_count == 0:
            return False
        ratio = self._fail_count / max(1, self._total_count)
        return ratio >= self.failure_threshold

    def state_allows(self) -> bool:
        return time.time() >= self._open_until

    def open(self) -> None:
        self._open_until = time.time() + self.half_open_after_sec
        self._fail_count = 0
        self._total_count = 0


async def post_with_retry(
    url: str,
    *,
    # Użyj jednego z dwóch:
    json_payload: Any | None = None,
    content: bytes | None = None,
    # Timeouty (connect_ms, read_ms)
    timeout_ms: tuple[int, int] = (2000, 5000),
    # Retry
    attempts: int = 3,
    base_delay_ms: int = 100,
    max_delay_ms: int = 1500,
    breaker: Breaker | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """
    Wysyłka z retry i prostym CB. Obsługuje JSON (json_payload) lub surowe body (content).
    - 5xx i błędy sieci → retry
    - 4xx → bez retry (zwracamy odpowiedź)
    - breaker.state_allows() == False → RuntimeError("circuit_open")
    """
    if json_payload is not None and content is not None:
        raise ValueError("Provide either json_payload or content, not both.")

    if breaker and not breaker.state_allows():
        raise RuntimeError("circuit_open")

    connect, read = timeout_ms
    timeout = httpx.Timeout(
        connect=connect / 1000.0, read=read / 1000.0, write=read / 1000.0, pool=connect / 1000.0
    )

    last_exc: Exception | None = None
    delay = base_delay_ms / 1000.0
    max_delay = max_delay_ms / 1000.0

    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(1, max(1, attempts) + 1):
            try:
                if content is not None:
                    resp = await client.post(url, content=content, headers=headers)
                else:
                    resp = await client.post(url, json=json_payload, headers=headers)

                # 4xx → bez retry
                if 400 <= resp.status_code < 500:
                    if breaker:
                        breaker.record(True)  # to nie błąd transportu
                    return resp

                # 5xx → można retry
                ok = resp.status_code < 500
                if breaker:
                    breaker.record(ok)
                    if breaker.should_open():
                        breaker.open()

                if ok:
                    return resp

            except Exception as e:
                last_exc = e
                if breaker:
                    breaker.record(False)
                    if breaker.should_open():
                        breaker.open()

            # tu wchodzimy jeśli wyjątek lub 5xx
            if attempt >= attempts:
                break
            await asyncio.sleep(min(delay, max_delay))
            delay = min(delay * 2, max_delay)

    raise RuntimeError(f"downstream_error: {last_exc!r}" if last_exc else "downstream_error")
