# -*- coding: utf-8 -*-
"""Tak för antalet samtidiga anslutningar.

WHY. `ThreadingHTTPServer` startar en tråd per anslutning utan gräns.
Handlerns `timeout = 30` skyddar mot Slowloris *per anslutning* - en klient
som öppnar och tiger släpps efter trettio sekunder - men ingenting hindrade
femtusen sådana samtidigt. Varje tråd kostar stackminne och en plats i
schemaläggaren, och instansen har 512 MB. Utfallet är inte ett långsamt
API: det är en död process, och SQLite-lagren bakom ett processglobalt
RLock gör kön ännu längre.

ETT TAK, INTE EN KÖ. Anslutning nummer N+1 avvisas direkt med 503 och
`Retry-After` - innan någon tråd skapas. Det är hela poängen: en kö som
växer fritt är samma problem med ett annat namn. En riktig besökare möter
ett svar hon förstår; en flod möter ett tak.

TAKET ÄR INTE EN RATE LIMITER. Rate limitern räknar begäranden per IP över
tid; det här räknar levande sockets just nu, oavsett vem de kommer från.
Båda behövs: den ena mot uthållig gissning, den andra mot en plötslig flod.
"""

import threading
from http.server import ThreadingHTTPServer

DEFAULT_MAX_CONNECTIONS = 64
REFUSAL_BODY = b'{"error":"Servern har fullt just nu. Forsok igen om nagra sekunder.","retryAfter":2}'
# Kort och egen: svaret skickas utanför handlern, på en socket vi ändå ska
# stänga. Blir klienten inte av med det inom en sekund är det inte värt en
# blockerad accept-loop.
REFUSAL_TIMEOUT_SECONDS = 1.0


def _refusal_bytes() -> bytes:
    return (b"HTTP/1.1 503 Service Unavailable\r\n"
            b"Content-Type: application/json; charset=utf-8\r\n"
            b"Retry-After: 2\r\n"
            b"Cache-Control: no-store\r\n"
            b"Connection: close\r\n"
            + f"Content-Length: {len(REFUSAL_BODY)}\r\n\r\n".encode("ascii")
            + REFUSAL_BODY)


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer med ett hårt tak på samtidiga anslutningar."""

    def __init__(self, *args, max_connections: int = DEFAULT_MAX_CONNECTIONS,
                 on_refused=None, **kwargs):
        self.max_connections = max(1, int(max_connections or DEFAULT_MAX_CONNECTIONS))
        self._slots = threading.BoundedSemaphore(self.max_connections)
        self._counter_lock = threading.Lock()
        self._active = 0
        self._refused = 0
        self._on_refused = on_refused
        super().__init__(*args, **kwargs)

    # ---- observerbarhet ----------------------------------------------------

    def stats(self) -> dict:
        with self._counter_lock:
            return {"active": self._active, "max": self.max_connections, "refused": self._refused}

    @property
    def active_connections(self) -> int:
        with self._counter_lock:
            return self._active

    # ---- taket -------------------------------------------------------------

    def process_request(self, request, client_address):
        """Körs i accept-loopens tråd. Platsen tas HÄR, före tråden skapas -
        annars är taket bara en fördröjd krasch."""
        if not self._slots.acquire(blocking=False):
            with self._counter_lock:
                self._refused += 1
            if self._on_refused is not None:
                try:
                    self._on_refused()
                except Exception:
                    pass
            self._refuse(request)
            self.shutdown_request(request)
            return
        with self._counter_lock:
            self._active += 1
        try:
            super().process_request(request, client_address)
        except Exception:
            # Tråden startade aldrig - lämna tillbaka platsen, annars läcker
            # taket nedåt tills servern vägrar allt.
            self._release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._release()

    def _release(self):
        with self._counter_lock:
            self._active = max(0, self._active - 1)
        try:
            self._slots.release()
        except ValueError:      # aldrig fler släpp än tagningar
            pass

    def _refuse(self, request):
        try:
            request.settimeout(REFUSAL_TIMEOUT_SECONDS)
            request.sendall(_refusal_bytes())
        except OSError:
            pass                # klienten är redan borta - det är helt i sin ordning
