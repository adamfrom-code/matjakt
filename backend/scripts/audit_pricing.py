# -*- coding: utf-8 -*-
"""FULL PRISAUDIT: varje recept x ingrediens x kedja, med Adams flaggor.

    python backend/scripts/audit_pricing.py            (lokal databas)

Samma kärna (services/grocery/audit.run_pricing_audit) körs i produktion via
POST /api/admin/pricing-audit. Skriver flaggrapport till stdout.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from services.grocery import api as gapi  # noqa: E402
from services.grocery.audit import run_pricing_audit  # noqa: E402
from services.recipes import api as rapi  # noqa: E402


def main() -> int:
    gs = gapi.open_store()
    rs = rapi.open_store()
    try:
        result = run_pricing_audit(gs, rs, ["Willys", "Hemköp", "City Gross"])
    finally:
        gs.close(); rs.close()
    print(f"\n{'='*64}")
    print(f"AUDIT: {result['recept']} recept, {result['kontroller']} rad×kedja-kontroller -> gate {result['gate']}")
    for kind, n in result["flaggor"].items():
        print(f"  {kind:<24} {n}")
        for ex in result["exempel"].get(kind, [])[:6]:
            print(f"      {ex}")
    (ROOT / "audit_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if result["gate"] == "GRÖN" else 1


if __name__ == "__main__":
    sys.exit(main())
