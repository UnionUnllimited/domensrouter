"""Dry run on the real main bot DB (read-only): what the creator bot would count for a campaign.

Usage: venv/bin/python check_campaign.py <campaign link or ID> [days]
"""
from __future__ import annotations

import asyncio
import sys
import time

import config
import main_db


async def run(query: str, days: int) -> None:
    campaign = await main_db.find_campaign(query)
    if campaign is None:
        sys.exit("Campaign not found")
    print(f"Campaign: {campaign['name']} (ID {campaign['id']})")
    print(f"Link:     {campaign['link']}{'  (built from template, verify it)' if campaign['link_from_template'] else ''}")

    since = int(time.time()) - days * 86400
    min_bytes = config.MIN_TRAFFIC_MB * 1024 * 1024
    users = await main_db.invited_users([campaign["id"]])
    recent = [u for u in users if (main_db.parse_dt(u["created_at"]) or 0) >= since]
    connected = [u for u in recent if main_db.is_connected(u, min_bytes)]
    print(f"All time: {len(users)} users")
    print(f"Last {days} days: {len(recent)} registered, {len(connected)} connected (>= {config.MIN_TRAFFIC_MB} MB)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    asyncio.run(run(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 7))
