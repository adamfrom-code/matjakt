# -*- coding: utf-8 -*-
"""The acceptance test: can a person use Matjakt while an import is running?

    python backend/scripts/acceptance_speed.py

Provider imports are allowed to be slow. Matjakt is not. This walks the flow
a real person takes - build a week, open the shopping list, open one store's
cart, switch to another - and reports how long each step took and whether it
was answered from our own database.

Run it once on a quiet database, then again with a collector running, and the
numbers should barely move. That is the whole architecture in one check.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from services.grocery import api  # noqa: E402
from services.grocery.store import GroceryStore  # noqa: E402

# A real 7-dinner week's summed ingredients.
WEEK = [
    ("Ris", 500, "g"), ("Pasta", 500, "g"), ("Smör", 100, "g"), ("Ost", 150, "g"),
    ("Ägg", 6, "st"), ("Mjölk", 1, "l"), ("Grädde", 200, "ml"),
    ("Kycklingfilé", 600, "g"), ("Köttfärs", 500, "g"), ("Lax", 500, "g"),
    ("Potatis", 1000, "g"), ("Lök", 300, "g"), ("Paprika", 200, "g"),
    ("Tomat", 400, "g"), ("Morötter", 500, "g"), ("Citron", 1, "st"),
    ("Kokosmjölk", 400, "ml"), ("Linser", 250, "g"), ("Bönor", 400, "g"),
    ("Majs", 200, "g"), ("Yoghurt", 500, "g"),
]
ITEMS = [{"name": n, "amount": a, "unit": u} for n, a, u in WEEK]

TARGETS = {
    "Prissätt veckan (alla kedjor)": 3000,
    "Öppna butikskorg": 500,
    "Byt till annan butik": 500,
    "Öppna samma korg igen": 200,
}


def timed(label, fn):
    start = time.time()
    result = fn()
    elapsed = (time.time() - start) * 1000
    target = TARGETS.get(label)
    mark = "✅" if target is None or elapsed <= target else "❌"
    print(f"  {mark} {label:32} {elapsed:6.0f} ms" + (f"   (mål {target} ms)" if target else ""))
    return result, elapsed <= (target or 10 ** 9)


def main():
    store = GroceryStore(api.DB_PATH)
    try:
        running = store.connection.execute(
            "SELECT chain FROM grocery_collector_runs WHERE status = 'running'").fetchall()
        summary = api.database_summary()
        version = store.data_version()
    finally:
        store.close()

    print(f"\nPrisdatabas: {summary['totalProducts']} produkter, "
          f"{len(summary['chains'])} kedjor med data")
    print(f"Datavärsion: {version}")
    print("Pågående import: " + (", ".join(r["chain"] for r in running) if running else "ingen"))
    print()

    ok = True
    api.clear_cache()
    week, good = timed("Prissätt veckan (alla kedjor)", lambda: api.price_week(ITEMS)); ok &= good

    chains = [r["chain"] for r in week["results"] if r["realPriceItems"] > 0]
    if not chains:
        print("\n❌ Ingen kedja kunde prissätta något - inget att acceptanstesta.")
        return 1

    _, good = timed("Öppna butikskorg", lambda: api.shopping_list(ITEMS, chains[0])); ok &= good
    if len(chains) > 1:
        _, good = timed("Byt till annan butik", lambda: api.shopping_list(ITEMS, chains[1])); ok &= good
    _, good = timed("Öppna samma korg igen", lambda: api.shopping_list(ITEMS, chains[0])); ok &= good

    print("\n  Kedjor och totaler:")
    for result in week["results"]:
        print(f"    {result['chain']:12} {str(result['totalCheckoutCost']):>8} kr  "
              f"{result['realPriceItems']}/{result['totalItems']} varor "
              f"({result['coveragePercent']} %)  jämförbar={result['comparable']}")

    cart = api.shopping_list(ITEMS, chains[0])
    with_image = sum(1 for i in cart["items"] if i.get("imageUrl"))
    with_package = sum(1 for i in cart["items"] if i.get("packageSize"))
    print(f"\n  Butikskorgen hos {cart['store']['name']}:")
    print(f"    {cart['realPriceItems']}/{cart['totalItems']} prissatta, "
          f"{with_image} med bild, {with_package} med förpackning")
    for item in cart["items"][:4]:
        if item["priceStatus"] != "missing":
            print(f"      {item['ingredient']:14} {item['productName'][:32]:32} "
                  f"{item['packages']}x{item['packageSize'] or '?'} = {item['totalCost']} kr")

    print("\n" + ("ALLA MÅL KLARADE" if ok else "NÅGOT MÅL MISSADES"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
