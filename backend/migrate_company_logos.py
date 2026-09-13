#!/usr/bin/env python3
"""
Migration: update existing company logo URLs to real, verified logos.
17 companies use Simple Icons (cdn.simpleicons.org) - actual official brand
SVG marks, verified to exist via direct HTTP check against the project's
repo before being added here. The remaining 8 companies (Microsoft, Amazon,
Berkshire Hathaway, Disney, Johnson & Johnson, Pfizer, UnitedHealth, Taiwan
Semiconductor) are not in that library, so they use Google's favicon
service as a fallback - still a real logo/icon, just smaller resolution.

Clearbit's Logo API was permanently shut down Dec 8, 2025, hence this
migration away from it.

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

from db import get_db

COMPANY_LOGOS = {
    "Tesla Inc": "https://cdn.simpleicons.org/tesla",
    "Microsoft Corporation": "https://www.google.com/s2/favicons?domain=microsoft.com&sz=128",
    "Apple Inc": "https://cdn.simpleicons.org/apple",
    "Alphabet Inc": "https://cdn.simpleicons.org/google",
    "Amazon.com Inc": "https://www.google.com/s2/favicons?domain=amazon.com&sz=128",
    "NVIDIA Corporation": "https://cdn.simpleicons.org/nvidia",
    "Meta Platforms": "https://cdn.simpleicons.org/meta",
    "Berkshire Hathaway": "https://www.google.com/s2/favicons?domain=berkshirehathaway.com&sz=128",
    "JPMorgan Chase": "https://cdn.simpleicons.org/chase",
    "Visa Inc": "https://cdn.simpleicons.org/visa",
    "Netflix Inc": "https://cdn.simpleicons.org/netflix",
    "Disney Company": "https://www.google.com/s2/favicons?domain=disney.com&sz=128",
    "Intel Corporation": "https://cdn.simpleicons.org/intel",
    "Mastercard Inc": "https://cdn.simpleicons.org/mastercard",
    "Johnson & Johnson": "https://www.google.com/s2/favicons?domain=jnj.com&sz=128",
    "Coca-Cola Company": "https://cdn.simpleicons.org/cocacola",
    "Pfizer Inc": "https://www.google.com/s2/favicons?domain=pfizer.com&sz=128",
    "Nike Inc": "https://cdn.simpleicons.org/nike",
    "UnitedHealth Group": "https://www.google.com/s2/favicons?domain=unitedhealthgroup.com&sz=128",
    "McDonald Corporation": "https://cdn.simpleicons.org/mcdonalds",
    "Qualcomm Inc": "https://cdn.simpleicons.org/qualcomm",
    "Taiwan Semiconductor": "https://www.google.com/s2/favicons?domain=tsmc.com&sz=128",
    "Advanced Micro Devices": "https://cdn.simpleicons.org/amd",
    "Broadcom Inc": "https://cdn.simpleicons.org/broadcom",
    "AbbVie Inc": "https://cdn.simpleicons.org/abbvie",
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
