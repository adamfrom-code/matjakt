"""Imports real products from ONE Hemköp store into the grocery database.

Usage (from the repo root):
    python -m backend.services.grocery.collectors.hemkop --store 4256 --limit 100

--store is Hemköp's own storeId from the Axfood store list. There is no
Hemköp store in Gävle; 4256 (Hemköp Uppsala Svava C) is the nearest online
one. NOTE: Hemköp prices are national, not per store - the store is used for
attribution only. See providers/hemkop.py.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from services.grocery.collectors.axfood import print_report, run  # noqa: E402
from services.grocery.providers.hemkop import HemkopProvider  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import real Hemköp products for one store into the grocery database.")
    parser.add_argument("--store", required=True, help="Hemköp storeId (e.g. 4256 = Hemköp Uppsala Svava C)")
    parser.add_argument("--limit", type=int, default=100, help="Max products to import (default 100)")
    args = parser.parse_args()

    result = run(HemkopProvider(), store_id=args.store, limit=args.limit)
    print_report(args.store, result)
