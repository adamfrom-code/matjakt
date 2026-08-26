"""
Gemensamma verktyg för alla butiksscrapers (ICA, Willys, Coop, ...).

Varje scraper (t.ex. ica_scraper.py) importerar Prisrad och skriv_csv
härifrån så vi har ETT gemensamt dataformat oavsett vilken butik
priset kommer från. Det gör det enkelt att slå ihop resultat från
flera kedjor senare (t.ex. för att jämföra vem som är billigast).
"""

from dataclasses import dataclass, asdict
import csv
import json
from pathlib import Path


@dataclass
class Prisrad:
    kedja: str            # "ICA", "Willys", "Coop"
    url: str
    produktnamn: str
    pris_kr: str           # sträng tills vi vet exakt format, t.ex. "18:90"
    enhet: str = ""        # t.ex. "st", "kg", "l"
    butik_postnummer: str = ""
    hamtad: str = ""       # ISO-tidsstämpel, sätts av scraper


def skriv_csv(rader: list[Prisrad], filnamn: str):
    """Skriver en lista Prisrad till CSV. Skapar filen om den inte finns."""
    path = Path(filnamn)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rader[0]).keys()) if rader else [])
        writer.writeheader()
        for rad in rader:
            writer.writerow(asdict(rad))
    print(f"Skrev {len(rader)} rader till {path.resolve()}")


def skriv_json(rader: list[Prisrad], filnamn: str):
    """Alternativ till CSV - praktiskt om frontend ska läsa datan direkt."""
    path = Path(filnamn)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in rader], f, ensure_ascii=False, indent=2)
    print(f"Skrev {len(rader)} rader till {path.resolve()}")


def las_produktlista(filnamn: str) -> list[dict]:
    """Läser en enkel JSON-lista med produkter som ska prisjämföras.
    Se sample_data/produkter.json för formatet."""
    with open(filnamn, encoding="utf-8") as f:
        return json.load(f)
