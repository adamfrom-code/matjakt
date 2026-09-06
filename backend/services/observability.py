# -*- coding: utf-8 -*-
"""Strukturerad loggning, request-id och räknare - så vi ser problem innan
användarna gör det.

 - Varje begäran får ett request-id (klientens X-Request-Id om det är
   välformat, annars ett nytt). Det följer med i varje loggrad som skrivs
   medan begäran behandlas (contextvar) och ekas tillbaka i svaret, så en
   supportfråga kan matchas mot exakt rätt rader i Render-loggen.
 - I produktion skrivs loggen som en JSON-rad per händelse (MATJAKT_LOG_FORMAT
   =json, standard på Render); lokalt som läsbar text.
 - METRICS är enkla räknare i processen (begäranden, 4xx/5xx, långsamma svar,
   misslyckade inloggningar, avvisade Stripe-webhookar, mejlfel, prisgate-
   stopp, databasfel). De visas i /api/health - siffror, aldrig innehåll.

Inga personuppgifter i accessloggen: sökvägen utan query, IP maskerad till
/24 (IPv4) eller /64 (IPv6), ingen User-Agent.
"""

import contextvars
import json
import logging
import os
import re
import threading
import time
import uuid

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("matjakt_request_id", default="-")

_REQUEST_ID_OK = re.compile(r"^[A-Za-z0-9._\-]{8,64}$")
STARTED_AT = time.time()


def new_request_id(incoming: str | None = None) -> str:
    """Behåll ett välformat inkommande id (proxyn eller appen kan sätta det),
    annars ett nytt. Aldrig godtycklig text in i loggen."""
    if incoming and _REQUEST_ID_OK.match(incoming):
        return incoming
    return uuid.uuid4().hex[:16]


def mask_ip(ip: str) -> str:
    """IP-adress utan sista delen - tillräckligt för att se mönster, inte en
    person."""
    if not ip:
        return "-"
    if ":" in ip:
        parts = ip.split(":")
        return ":".join(parts[:4]) + "::"
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3]) + ".0"
    return ip[:16]


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """En JSON-rad per händelse. Extra fält (record.__dict__["fields"])
    läggs platt så en loggtjänst kan filtrera på dem."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)[-4000:]
        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict) and fields:
            base += " " + " ".join(f"{key}={value}" for key, value in fields.items())
        return base


def log_format_from_env() -> str:
    explicit = os.environ.get("MATJAKT_LOG_FORMAT", "").strip().lower()
    if explicit in ("json", "text"):
        return explicit
    return "json" if os.environ.get("RENDER") else "text"


def configure_logging(fmt: str | None = None, level: int = logging.INFO) -> None:
    """Idempotent: byter ut rotloggerns handlers mot en enda med rätt format
    och request-id-filtret."""
    fmt = fmt or log_format_from_env()
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter("%(levelname)s:%(name)s:[%(request_id)s] %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)


class Metrics:
    """Trådsäkra räknare i processen. Nollställs vid omstart - de svarar på
    "händer det nu?", inte "hur många gånger i år?"."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}

    def incr(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counts[name] = self._counts.get(name, 0) + amount

    def snapshot(self) -> dict:
        with self._lock:
            counts = dict(sorted(self._counts.items()))
        counts["uptime_seconds"] = int(time.time() - STARTED_AT)
        return counts

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


METRICS = Metrics()
access_logger = logging.getLogger("matjakt.access")


def log_access(*, method: str, path: str, status: int, duration_ms: float, client_ip: str, request_id: str) -> None:
    """En rad per begäran. Sökväg utan query (den kan bära postnummer,
    sökord eller token), IP maskerad."""
    access_logger.info(
        "%s %s -> %s (%.0f ms)", method, path, status, duration_ms,
        extra={"fields": {"method": method, "path": path[:200], "status": status,
                          "duration_ms": round(duration_ms, 1), "ip": mask_ip(client_ip),
                          "rid": request_id}})
    METRICS.incr("requests_total")
    if status >= 500:
        METRICS.incr("responses_5xx")
    elif status >= 400:
        METRICS.incr("responses_4xx")
    if duration_ms >= 2000:
        METRICS.incr("slow_requests_2s")
