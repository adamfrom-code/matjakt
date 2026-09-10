# -*- coding: utf-8 -*-
"""Revisionslogg för admin-ytan: vem kom in, var, och när.

WHY. Admin-token är EN bärarhemlighet utan utgång, utan rotation och utan
identitet. Läcker den finns ingen skillnad mellan Adam och den som hittade
den i en gammal commit - och utan den här raden finns inte heller något
sätt att i efterhand se att någon annan varit inne. En accesslograd säger
bara att `/api/admin/insights` svarade 200; den säger inte att svaret gavs
för att någon visade rätt hemlighet.

Det som loggas är sökvägen, en maskerad IP (/24 respektive /64, samma
maskning som accessloggen) och request-id:t som knyter raden till resten av
begäran. Aldrig token, aldrig ett prefix av den: en revisionslogg som bär
hemligheten den bevakar är en läcka med tidsstämpel.

Räknaren i METRICS syns i /api/health. Ett hopp i `admin_authorized_total`
en natt då ingen jobbade är hela poängen.
"""

import logging

from .observability import METRICS, mask_ip, request_id_var

logger = logging.getLogger("matjakt.admin")


def log_admin_access(*, path: str, client_ip: str, scope: str = "control-room",
                     request_id: str | None = None) -> None:
    """En rad per GODKÄND admin-kontroll. Avvisade försök syns redan som
    404 i accessloggen och i rate limiterns räknare."""
    rid = request_id or request_id_var.get()
    logger.info(
        "admin godkänd: %s %s", scope, path,
        extra={"fields": {"admin_scope": scope, "path": (path or "")[:200],
                          "ip": mask_ip(client_ip or ""), "rid": rid}})
    METRICS.incr("admin_authorized_total")
    if scope != "control-room":
        METRICS.incr(f"admin_authorized_{scope.replace('-', '_')}")
