# services/authgw/downstream.py
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple

import httpx

logger = logging.getLogger("authgw.downstream")


@dataclass
class Breaker:
    """
    Prosty circuit breaker oparty o proporcję błędów w 'oknie' licznikowym.
    Stany:
      - closed     : normalna praca
      - open       : odcinamy ruch do czasu 'half_open_after_sec'
      - half_open  : przepuszczamy pojedyncze próby; sukces zamyka obwód

    Polityka:
      - przejście do open, gdy ratio(fails/total) >= failure_threshold
      - w half_open: sukces -> closed (zeruje okno), błąd -> open (reset timera)
      - lekkie „przycinanie” okna przy bardzo dużych licznikach
    """
    failure_threshold: float = 0.20     # np. 0.2 => 20%
    window_sec: int = 30                # (zostawione na przyszłość; teraz licznikowe okno)
    half_open_after_sec: int = 20

    _fails: int = 0
    _total: int = 0
    _opened_at: Optional[float] = None

    def _state(self, now: float) -> str:
        if self._opened_at is None:
            return "closed"
        if (now - self._opened_at) >= self.half_open_after_sec:
            return "half_open"
        return "open"

    def allow_request(self) -> bool:
        now = time.time()
        state = self._state(now)
        allowed = state != "open"
        if not allowed:
            logger.debug("breaker=OPEN deny request (will be half-open in %.1fs)",
                         max(0.0, self.half_open_after_sec - (now - (self._opened_at or now))))
        return allowed

    def _shrink_window(self) -> None:
        # proste „przycinanie” okna, by liczby nie rosły w nieskończoność
        if self._total >= 1000:
            ratio = self._fails / max(1, self._total)
            self._fails = int(ratio * 100)
            self._total = 100

    def record_success(self) -> None:
        now = time.time()
        state = self._state(now)
        self._total += 1

        if state == "half_open":
            # sukces w half-open zamyka obwód i zeruje okno
            self._opened_at = None
            self._fails = 0
            self._total = 0
            logger.info("breaker transition: HALF_OPEN -> CLOSED (success)")
            return

        self._shrink_window()

    def record_failure(self) -> None:
        now = time.time()
        state = self._state(now)
        self._total += 1
        self._fails += 1

        if state == "closed":
            ratio = self._fails / max(1, self._total)
            if ratio >= self.failure_threshold:
                self._opened_at = now
                logger.warning("breaker transition: CLOSED -> OPEN (ratio=%.3f >= %.3f)",
                               ratio, self.failure_threshold)
        elif state == "half_open":
            # błąd w half-open utrzymuje open (reset timera)
            self._opened_at = now
            logger.warning("breaker: HALF_OPEN -> OPEN (failure)")

        self._shrink_window()


async def post_with_retry(
    url: str,
    json_payload: Any,
    timeout_ms: Tuple[int, int] = (2000, 5000),  # (connect_ms, read_ms)
    attempts: int = 3,
    base_delay_ms: int = 100,
    max_delay_ms: int = 1500,
    breaker: Optional[Breaker] = None,
    headers: Optional[Dict[str, str]] = None,
) -> httpx.Response:
    """
    POST z retry + (opcjonalnie) circuit breakerem.

    - Próby ponawiamy dla błędów sieciowych i HTTP 5xx.
    - HTTP 4xx zwracamy bez retry (to raczej błąd klienta).
    - Przy stanie breaker=OPEN rzucamy RuntimeError("circuit_open").

    Zwraca: httpx.Response (jeśli uda się wysłać) lub
    rzuca RuntimeError po wyczerpaniu prób.
    """
    if not url:
        raise RuntimeError("forward_url_missing")

    attempts = max(1, int(attempts))
    connect_ms, read_ms = timeout_ms

    timeout = httpx.Timeout(
        connect=connect_ms / 1000.0,
        read=read_ms / 1000.0,
        write=read_ms / 1000.0,
        pool=connect_ms / 1000.0,
    )

    last_exc: Optional[Exception] = None

    for attempt in range(1, attempts + 1):
        if breaker and not breaker.allow_request():
            raise RuntimeError("circuit_open")

        try:
            logger.debug("downstream POST attempt=%d url=%s", attempt, url)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=json_payload, headers=headers)

            status = resp.status_code
            # 5xx traktujemy jako „awarię” downstream → retry/CB
            if 500 <= status < 600:
                logger.warning("downstream 5xx (status=%d) on attempt=%d", status, attempt)
                if breaker:
                    breaker.record_failure()
                last_exc = RuntimeError(f"http_{status}")
            else:
                if breaker:
                    breaker.record_success()
                return resp

        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as e:
            logger.warning("downstream network error on attempt=%d: %s", attempt, e.__class__.__name__)
            last_exc = e
            if breaker:
                breaker.record_failure()
        except Exception as e:
            logger.warning("downstream unexpected error on attempt=%d: %s", attempt, e)
            last_exc = e
            if breaker:
                breaker.record_failure()

        # jeżeli to nie była ostatnia próba — czekamy z backoffem
        if attempt < attempts:
            delay = min(base_delay_ms * (2 ** (attempt - 1)), max_delay_ms) / 1000.0
            logger.debug("retry sleeping %.3fs (attempt %d/%d)", delay, attempt, attempts)
            await asyncio.sleep(delay)

    # po wszystkich próbach – zgłoś błąd z ostatnim wyjątkiem
    if last_exc is None:
        raise RuntimeError("downstream_error: unknown")
    raise RuntimeError(f"downstream_error: {type(last_exc).__name__}: {last_exc}")
