# -*- coding: utf-8 -*-
"""FULL PRISAUDIT: varje recept x ingrediens x kedja, med Adams flaggor.

    python backend/scripts/audit_pricing.py            (lokal databas)

Samma kärna (services/grocery/audit.run_pricing_audit) körs i produktion via
POST /api/admin/pricing-audit. Skriver flaggrapport till stdout och
resultatet som JSON till MATJAKT_DATA_DIR/audit/ (backend/data/audit/).
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

# Resultatet låg i repo-roten. Det är genererad data, och varje agent som
# körde auditen fick därmed en diff i roten - den perfekta konfliktgeneratorn
# när tjugo grenar är igång samtidigt. Nu skrivs det bredvid databaserna det
# beskriver, i den gitignorerade datakatalogen.
#
# Samma MATJAKT_DATA_DIR-override som resten av backenden, av samma skäl: en
# audit mot en testdatakatalog får inte skriva över produktionens senaste
# resultat, och två auditer i olika datakataloger ska inte kunna förväxlas.
AUDIT_DIR = Path(os.environ.get("MATJAKT_DATA_DIR") or (ROOT / "backend" / "data")) / "audit"

from services.grocery import api as gapi  # noqa: E402
from services.grocery.audit import run_pricing_audit  # noqa: E402
from services.recipes import api as rapi  # noqa: E402


def main() -> int:
    gs = gapi.open_store()
    rs = rapi.open_store()
    try:
        product_count = gs.connection.execute("SELECT COUNT(*) FROM grocery_products").fetchone()[0]
        # Prisdatans ålder, inte filens sökväg: en audit mot en gammal kopia
        # och en mot produktion har samma sökväg på olika maskiner, men olika
        # färskhet - och det är färskheten som avgör vad resultatet är värt.
        newest_price = gs.connection.execute(
            "SELECT MAX(fetched_at) FROM grocery_current_prices").fetchone()[0]
        if not product_count:
            # Fail closed: en tom prisdatabas ger "allt grönt" utan att ha
            # granskat något. Det är inget kvitto, det är en tom rapport.
            print("AVBRYTER: prisdatabasen är tom - 0 produkter. En audit utan "
                  "priser kan inte hitta ett enda fel och får inte skrivas som "
                  "resultat. Peka MATJAKT_DATA_DIR på en databas med kedjedata.",
                  file=sys.stderr)
            return 2
        result = run_pricing_audit(gs, rs, ["Willys", "Hemköp", "City Gross"])
    finally:
        gs.close(); rs.close()
    print(f"\n{'='*64}")
    print(f"AUDIT: {result['recept']} recept, {result['kontroller']} rad×kedja-kontroller -> gate {result['gate']}")
    for kind, n in result["flaggor"].items():
        print(f"  {kind:<24} {n}")
        for ex in result["exempel"].get(kind, [])[:6]:
            print(f"      {ex}")
    # VARIFRÅN siffrorna kommer, sparat med dem. En audit med 0 kontroller
    # ser ut som ett grönt kvitto men kan inte hitta ett enda fel, och en
    # audit mot en gammal backup är inte samma sak som mot produktion.
    # Utan den här raden gick de två inte att skilja åt i efterhand.
    result["produkter"] = product_count
    result["prisdata_senast"] = newest_price
    result["kord"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    utdata = AUDIT_DIR / "audit_result.json"
    utdata.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nResultatet skrivet till {utdata}")
    return 0 if result["gate"] == "GRÖN" else 1


if __name__ == "__main__":
    sys.exit(main())
