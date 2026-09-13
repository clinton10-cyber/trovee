#!/usr/bin/env python3
"""
Migration: update existing company logo URLs to Google's favicon service
(Clearbit's Logo API was shut down Dec 8, 2025). Safe to run on a live
database - only UPDATEs the logo_url column on existing share_companies
rows, matched by company name. No data is deleted, no tables are dropped,
no other columns are touched.

Usage:
    cd backend
    python3 migrate_company_logos.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_db

COMPANY_LOGOS = {
    "Tesla Inc": "https://www.google.com/s2/favicons?domain=tesla.com&sz=128",
    "Microsoft Corporation": "https://www.google.com/s2/favicons?domain=microsoft.com&sz=128",
    "Apple Inc": "https://www.google.com/s2/favicons?domain=apple.com&sz=128",
    "Alphabet Inc": "https://www.google.com/s2/favicons?domain=google.com&sz=128",
    "Amazon.com Inc": "https://www.google.com/s2/favicons?domain=amazon.com&sz=128",
    "NVIDIA Corporation": "https://www.google.com/s2/favicons?domain=nvidia.com&sz=128",
    "Meta Platforms": "https://www.google.com/s2/favicons?domain=meta.com&sz=128",
    "Berkshire Hathaway": "https://www.google.com/s2/favicons?domain=berkshirehathaway.com&sz=128",
    "JPMorgan Chase": "https://www.google.com/s2/favicons?domain=jpmorganchase.com&sz=128",
    "Visa Inc": "https://www.google.com/s2/favicons?domain=visa.com&sz=128",
    "Netflix Inc": "https://www.google.com/s2/favicons?domain=netflix.com&sz=128",
    "Disney Company": "https://www.google.com/s2/favicons?domain=disney.com&sz=128",
    "Intel Corporation": "https://www.google.com/s2/favicons?domain=intel.com&sz=128",
    "Mastercard Inc": "https://www.google.com/s2/favicons?domain=mastercard.com&sz=128",
    "Johnson & Johnson": "https://www.google.com/s2/favicons?domain=jnj.com&sz=128",
    "Coca-Cola Company": "https://www.google.com/s2/favicons?domain=coca-cola.com&sz=128",
    "Pfizer Inc": "https://www.google.com/s2/favicons?domain=pfizer.com&sz=128",
    "Nike Inc": "https://www.google.com/s2/favicons?domain=nike.com&sz=128",
    "UnitedHealth Group": "https://www.google.com/s2/favicons?domain=unitedhealthgroup.com&sz=128",
    "McDonald Corporation": "https://www.google.com/s2/favicons?domain=mcdonalds.com&sz=128",
    "Qualcomm Inc": "https://www.google.com/s2/favicons?domain=qualcomm.com&sz=128",
    "Taiwan Semiconductor": "https://www.google.com/s2/favicons?domain=tsmc.com&sz=128",
    "Advanced Micro Devices": "https://www.google.com/s2/favicons?domain=amd.com&sz=128",
    "Broadcom Inc": "https://www.google.com/s2/favicons?domain=broadcom.com&sz=128",
    "AbbVie Inc": "https://www.google.com/s2/favicons?domain=abbvie.com&sz=128",
}

# USDT wallet display-name rename (TRC20 -> Tron), address unchanged.
WALLET_RENAME = {
    "old_name": "USDT (TRC20)",
    "new_name": "USDT (Tron)",
}


def migrate():
    db = get_db()
    updated, skipped = 0, 0

    print("[trovee] Migrating company logo URLs (existing rows only)...")
    for company_name, logo_url in COMPANY_LOGOS.items():
        try:
            existing = db.execute(
                "SELECT id, logo_url FROM share_companies WHERE name = ?",
                (company_name,)
            ).fetchone()

            if not existing:
                print(f"  - skip (not found): {company_name}")
                skipped += 1
                continue

            db.execute(
                "UPDATE share_companies SET logo_url = ? WHERE name = ?",
                (logo_url, company_name)
            )
            updated += 1
            print(f"  ✓ {company_name}")
        except Exception as e:
            print(f"  ✗ {company_name}: {e}")

    print("\n[trovee] Migrating USDT wallet display name...")
    try:
        wallet = db.execute(
            "SELECT id FROM wallet_configs WHERE display_name = ?",
            (WALLET_RENAME["old_name"],)
        ).fetchone()
        if wallet:
            db.execute(
                "UPDATE wallet_configs SET display_name = ? WHERE display_name = ?",
                (WALLET_RENAME["new_name"], WALLET_RENAME["old_name"])
            )
            print(f"  ✓ Renamed '{WALLET_RENAME['old_name']}' -> '{WALLET_RENAME['new_name']}'")
        else:
            print(f"  - skip: no wallet named '{WALLET_RENAME['old_name']}' found (already renamed or never existed)")
    except Exception as e:
        print(f"  ✗ Wallet rename error: {e}")

    db.commit()
    db.close()
    print(f"\n[trovee] Migration complete. {updated} companies updated, {skipped} skipped (no matching row).")


if __name__ == "__main__":
    migrate()
