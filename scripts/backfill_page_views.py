#!/usr/bin/env python3
"""One-shot backfill: classify historical page_views rows.

Older page_views rows were recorded before page_type/category/content_id
labeling existed. This script re-runs classify_path() over their saved paths
and fills those columns in, marking each processed row classified=1 so later
runs never re-scan it.

Run this ON DEMAND (e.g. once after deploying the `classified` column) --
NEVER at gunicorn worker boot. Worker boot must stay fast; see
database.init_db()'s docstring.

Usage:
    python scripts/backfill_page_views.py [--batch-size N] [--max-batches N]

Each batch processes at most --batch-size distinct paths (default 500). The
script loops until no unclassified rows remain or --max-batches is reached
(0 = no limit). New page views are recorded with classified=1 at insert time,
so after one full run this script is a cheap no-op.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analytics_common import backfill_page_view_classification
from database import get_db, init_db


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-size", type=int, default=500,
                        help="distinct paths processed per batch (default 500)")
    parser.add_argument("--max-batches", type=int, default=0,
                        help="stop after this many batches; 0 = no limit (default 0)")
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be >= 1")

    # Ensure the classified column and its index exist. Fast schema check
    # only -- init_db() never backfills.
    init_db()

    conn = get_db()
    try:
        batches = 0
        grand_total = 0
        start = time.monotonic()
        while True:
            if args.max_batches and batches >= args.max_batches:
                print(f"stopping: --max-batches {args.max_batches} reached "
                      f"({grand_total} rows classified so far)")
                break
            n = backfill_page_view_classification(conn, limit=args.batch_size)
            batches += 1
            grand_total += n
            elapsed = time.monotonic() - start
            print(f"batch {batches}: {n} rows classified ({elapsed:.1f}s elapsed)",
                  flush=True)
            if n == 0:
                break
        print(f"done: {grand_total} rows classified in {batches} batch(es), "
              f"{time.monotonic() - start:.1f}s total")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
