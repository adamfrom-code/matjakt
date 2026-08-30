"""Imports real products from ONE City Gross store into the grocery database.

Usage (from the repo root):
    python -m backend.services.grocery.collectors.citygross --store 3209 --limit 100

--store is City Gross' storeNumber from /api/v1/sites (3209 = City Gross
Gävle). Note: the store id/siteId are NOT accepted by the search endpoint -
only storeNumber. See providers/citygross.py.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from services.grocery.collectors.axfood import print_report, run  # noqa: E402
from services.grocery.providers.citygross import CityGrossProvider  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import real City Gross products into the grocery database.")
    parser.add_argument("--store", required=True, help="City Gross storeNumber (e.g. 3209 = Gävle)")
    parser.add_argument("--limit", type=int, default=100, help="Max products to import (default 100)")
    args = parser.parse_args()

    result = run(CityGrossProvider(), store_id=args.store, limit=args.limit)
    print_report(args.store, result)
