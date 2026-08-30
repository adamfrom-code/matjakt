"""Imports real products from ONE Willys store into the grocery database.

Usage (from the repo root):
    python -m backend.services.grocery.collectors.willys --store 2132 --limit 100

--store is Willys' own storeId from the Axfood store list (2132 = Willys
Gävle Gestrike). NOTE: Willys prices are national, not per store - the store
is used for attribution only. See providers/willys.py.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from services.grocery.collectors.axfood import print_report, run  # noqa: E402
from services.grocery.providers.willys import WillysProvider  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import real Willys products for one store into the grocery database.")
    parser.add_argument("--store", required=True, help="Willys storeId (e.g. 2132 = Willys Gävle Gestrike)")
    parser.add_argument("--limit", type=int, default=100, help="Max products to import (default 100)")
    args = parser.parse_args()

    result = run(WillysProvider(), store_id=args.store, limit=args.limit)
    print_report(args.store, result)
