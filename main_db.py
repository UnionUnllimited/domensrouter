"""Read-only access to the main bot database (vpn_bot.db). Nothing is ever written there."""
from __future__ import annotations

import asyncio
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Iterable

import config


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{config.MAIN_DB_PATH}?mode=ro", uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = 1")
    return con


def parse_dt(value: Any) -> int | None:
    """Handle both '2026-09-07 11:18:59' and '2026-11-08T10:29:05.199487+00:00'. Naive values are UTC."""
    if not value:
        return None
    text = str(value).strip().replace(" ", "T", 1).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def is_connected(user: dict, min_bytes: int) -> bool:
    traffic = max(int(user.get("total_total_bytes") or 0), int(user.get("total_bytes") or 0))
    return bool(user.get("online_at")) and traffic >= min_bytes


# ---------- invited users ----------

def _invited_users(campaign_ids: list[int]) -> list[dict]:
    marks = ",".join("?" * len(campaign_ids))
    with closing(_connect()) as con:
        rows = con.execute(
            f"""
            SELECT telegram_id, invited_by, created_at, online_at, total_bytes, total_total_bytes,
                   remnawave_username
            FROM users WHERE invited_by IN ({marks})
            """,
            campaign_ids,
        ).fetchall()
    return [dict(r) for r in rows]


async def invited_users(campaign_ids: Iterable[int]) -> list[dict]:
    ids = list(campaign_ids)
    if not ids:
        return []
    return await asyncio.to_thread(_invited_users, ids)


# ---------- campaign lookup ----------

def _campaign_row(con: sqlite3.Connection, text: str) -> sqlite3.Row | None:
    match = re.search(r"start=([\w-]+)", text)
    payload = match.group(1) if match else text.strip()
    if not payload:
        return None
    columns = "telegram_id, username, partner_ref_code"
    row = con.execute(f"SELECT {columns} FROM users WHERE partner_ref_code = ?", (payload,)).fetchone()
    if row is None and match:
        row = con.execute(
            f"""
            SELECT {columns} FROM users
            WHERE partner_ref_code IS NOT NULL AND partner_ref_code != '' AND instr(?, partner_ref_code) > 0
            ORDER BY length(partner_ref_code) DESC LIMIT 1
            """,
            (payload,),
        ).fetchone()
    if row is None:
        for digits in re.findall(r"\d{6,}", payload):
            row = con.execute(f"SELECT {columns} FROM users WHERE telegram_id = ?", (int(digits),)).fetchone()
            if row is not None:
                break
    return row


def _find_campaign(text: str) -> dict | None:
    with closing(_connect()) as con:
        row = _campaign_row(con, text)
        if row is None:
            return None
        invited = con.execute(
            "SELECT COUNT(*) FROM users WHERE invited_by = ?", (row["telegram_id"],)
        ).fetchone()[0]
    is_link = "start=" in text
    code = row["partner_ref_code"] or str(row["telegram_id"])
    link = text.strip() if is_link else config.CAMPAIGN_LINK_TEMPLATE.format(bot=config.MAIN_BOT_USERNAME, code=code)
    return {
        "id": int(row["telegram_id"]),
        "name": row["username"] or str(row["telegram_id"]),
        "link": link,
        "link_from_template": not is_link,
        "invited": int(invited),
    }


async def find_campaign(text: str) -> dict | None:
    """Find a campaign (or any inviter) by its link, start code or ID."""
    return await asyncio.to_thread(_find_campaign, text)
