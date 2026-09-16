# -*- coding: utf-8 -*-
"""Det kanoniska ingredienslagret.

P05a. Receptbanken hade 212 distinkta ingrediensnamn och 212 normaliserade
id - normaliseringen (services/recipes/store.normalize_ingredient_id) gör
stavningen konsekvent men slår aldrig ihop något. "tomat" (4 rader) och
"tomater" (10) var två råvaror. "lök" (5) och "gul lök" (78) var två. Och
prissättningen nycklar sina regler på namn med accenter ("kycklingfilé")
medan recepten nycklar på slug ("kycklingfile"): två vokabulärer för samma
sak, hållna isär av ingenting.

Det här lagret är EN vokabulär, som en datafil (kanoniska.json) bredvid
koden. Varje post bär:

  id              kanoniskt id, samma slug-form som recepten redan använder
  namn            visningsnamn
  alias           andra id (och därmed namn) som betyder samma råvara
  standardenhet   den enhet banken oftast anger råvaran i, eller None
  enhetsfamilj    massa | volym | antal | None - härledd ur standardenheten
  skafferi        samma svar som services/recipes/pantry.is_pantry_staple
  omvandling      {"g_per_st": ..., "kalla": "..."} - TOM tills någon kan ange
                  en källa. Ett tal utan källa är en gissning, och en gissad
                  omvandling påverkar pris. Testet vägrar tal utan källa.

Tre regler som styrt hur listan blev till, för nästa person:

1. ALIAS BARA DÄR REFERENTEN ÄR ENTYDIG. tomat->tomater, ja. grädde->
   vispgrädde, NEJ: olika fetthalt, olika produkt. olja->olivolja, nej.
   ris->jasminris, nej. kycklingfilé->kycklinglårfilé, nej. köttfärs->
   nötfärs, nej (blandfärs är inte nötfärs). Liknande text betyder inte
   samma produkt - det är hela skillnaden mellan det här lagret och en
   Jaccard-score.

2. ENHETSFAMILJERNA ÄR PRISSÄTTNINGENS. Det fanns redan två definitioner
   (grocery/pricing._MASS/_VOLUME/COUNT_UNITS och frontendens UNIT_TO_BASE)
   och de råkar vara överens. Den här modulen är inte en tredje: den
   importerar prissättningens tabeller, och ett test håller alla tre ihop.

3. INGEN OMVANDLING ÖVER FAMILJEGRÄNS UTAN DATA. 224 g fiskpinnar är inte
   224 paket. 10 g persilja är inte 10 knippen. convert_amount() svarar
   redan None där; det här lagret ger den en plats att lägga en VERIFIERAD
   vikt per styck när någon har en - och vägrar tills dess.

Resolve() svarar None för ett okänt namn. Ett okänt namn ska stå som
"Mängd osäker"/"Pris saknas" hos anroparen, aldrig gissas till närmaste.
"""

from __future__ import annotations

import json
import unicodedata
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# Prissättningens enhetstabeller. Importeras, kopieras inte: se regel 2.
from services.grocery.pricing import COUNT_UNITS, _MASS, _VOLUME

DATAFIL = Path(__file__).resolve().parent / "kanoniska.json"

MASSA, VOLYM, ANTAL = "massa", "volym", "antal"


def _slug(name: str) -> str:
    """Samma härledning som services/recipes/store.normalize_ingredient_id.
    Upprepad här i stället för importerad för att slippa cirkeln
    ingredients -> recipes.store -> recipes.pantry -> ingredients; ett test
    håller de två identiska."""
    lowered = str(name or "").lower().strip()
    folded = "".join(c for c in unicodedata.normalize("NFD", lowered)
                     if unicodedata.category(c) != "Mn")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", folded)).strip("-")


def unit_family(unit: str | None) -> str | None:
    """massa | volym | antal | None. Samma svar som prissättningen ger."""
    u = _slug(unit or "")
    if not u:
        return None
    if u in _MASS:
        return MASSA
    if u in _VOLUME:
        return VOLYM
    if u in COUNT_UNITS or u in ("klyfta", "skiva", "knippe", "burk", "pase", "paket", "forpackning"):
        return ANTAL
    return None


@dataclass(frozen=True)
class Kanonisk:
    id: str
    namn: str
    alias: tuple[str, ...] = ()
    standardenhet: str | None = None
    enhetsfamilj: str | None = None
    skafferi: bool = False
    omvandling: dict = field(default_factory=dict)

    def g_per_st(self) -> float | None:
        """Verifierad vikt per styck, eller None. Aldrig ett antagande."""
        v = self.omvandling.get("g_per_st")
        return float(v) if v is not None and self.omvandling.get("kalla") else None


@lru_cache(maxsize=1)
def ladda() -> dict[str, Kanonisk]:
    """Alla kanoniska poster, nycklade på id. Läses en gång per process."""
    rader = json.loads(DATAFIL.read_text(encoding="utf-8"))
    ut: dict[str, Kanonisk] = {}
    for r in rader:
        k = Kanonisk(
            id=r["id"], namn=r["namn"], alias=tuple(r.get("alias") or ()),
            standardenhet=r.get("standardenhet"),
            enhetsfamilj=r.get("enhetsfamilj"),
            skafferi=bool(r.get("skafferi")),
            omvandling=dict(r.get("omvandling") or {}),
        )
        if k.id in ut:
            raise ValueError(f"kanoniska.json: dubbelt id {k.id!r}")
        ut[k.id] = k
    return ut


@lru_cache(maxsize=1)
def _aliasindex() -> dict[str, str]:
    index: dict[str, str] = {}
    for k in ladda().values():
        for a in k.alias:
            if a in index or a in ladda():
                raise ValueError(f"kanoniska.json: aliaset {a!r} pekar på fler än ett id")
            index[a] = k.id
    return index


def resolve(name_or_id: str | None) -> Kanonisk | None:
    """Namn eller id -> kanonisk post. None om okänt - gissa aldrig."""
    key = _slug(name_or_id or "")
    if not key:
        return None
    poster = ladda()
    if key in poster:
        return poster[key]
    kanoniskt = _aliasindex().get(key)
    return poster[kanoniskt] if kanoniskt else None


def canonical_id(name_or_id: str | None) -> str | None:
    k = resolve(name_or_id)
    return k.id if k else None


def alla() -> list[Kanonisk]:
    return sorted(ladda().values(), key=lambda k: k.id)
