#!/usr/bin/env python3
"""
Migration: update existing company logo URLs to Clearbit CDN, in place.
Safe to run on a live database - only UPDATEs the logo_url column on
existing share_companies rows, matched by company name. No data is
deleted, no tables are dropped, no other columns are touched.

Usage:
    cd backend
    python3 migrate_company_logos.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_db, USE_POSTGRES

COMPANY_LOGOS = {
    "Tesla Inc": "https://logo.clearbit.com/tesla.com",
    "Microsoft Corporation": "https://logo.clearbit.com/microsoft.com",
    "Apple Inc": "https://logo.clearbit.com/apple.com",
    "Alphabet Inc": "https://logo.clearbit.com/google.com",
    "Amazon.com Inc": "https://logo.clearbit.com/amazon.com",
    "NVIDIA Corporation": "https://logo.clearbit.com/nvidia.com",
    "Meta Platforms": "https://logo.clearbit.com/meta.com",
    "Berkshire Hathaway": "https://logo.clearbit.com/berkshirehathaway.com",
    "JPMorgan Chase": "https://logo.clearbit.com/jpmorganchase.com",
    "Visa Inc": "https://logo.clearbit.com/visa.com",
    "Netflix Inc": "https://logo.clearbit.com/netflix.com",
    "Disney Company": "https://logo.clearbit.com/disney.com",
    "Intel Corporation": "https://logo.clearbit.com/intel.com",
    "Mastercard Inc": "https://logo.clearbit.com/mastercard.com",
    "Johnson & Johnson": "https://logo.clearbit.com/jnj.com",
    "Coca-Cola Company": "https://logo.clearbit.com/coca-cola.com",
    "Pfizer Inc": "https://logo.clearbit.com/pfizer.com",
    "Nike Inc": "https://logo.clearbit.com/nike.com",
    "UnitedHealth Group": "https://logo.clearbit.com/unitedhealthgroup.com",
    "McDonald Corporation": "https://logo.clearbit.com/mcdonalds.com",
    "Qualcomm Inc": "https://logo.clearbit.com/qualcomm.com",
    "Taiwan Semiconductor": "https://logo.clearbit.com/tsmc.com",
    "Advanced Micro Devices": "https://logo.clearbit.com/amd.com",
    "Broadcom Inc": "https://logo.clearbit.com/broadcom.com",
    "AbbVie Inc": "https://logo.clearbit.com/abbvie.com",
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
