"""Own database of the creator bot (creators.db)."""
from __future__ import annotations

import asyncio
import secrets
import string
import time
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS creators (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    campaign_id    INTEGER NOT NULL UNIQUE,   -- inviter ID in the main bot ("Продвижение" campaign)
    campaign_name  TEXT,
    ref_link       TEXT    NOT NULL,
    count_from     INTEGER NOT NULL,          -- only users registered after this moment are counted
    invite_token   TEXT    NOT NULL UNIQUE,   -- start payload for this bot, e.g. join_...
    tg_id          INTEGER UNIQUE,
    tg_username    TEXT,
    rate           INTEGER NOT NULL,          -- RUB per qualified user
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS referrals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id     INTEGER NOT NULL REFERENCES creators(id),
    tg_id          INTEGER NOT NULL UNIQUE,
    registered_at  INTEGER NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'pending',  -- pending | qualified | rejected | expired
    reason         TEXT,
    amount         INTEGER NOT NULL DEFAULT 0,
    qualified_at   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_referrals_creator ON referrals(creator_id, status);
CREATE INDEX IF NOT EXISTS idx_referrals_status ON referrals(status);

CREATE TABLE IF NOT EXISTS devices (
    hwid           TEXT    PRIMARY KEY,
    referral_id    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS withdrawals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id     INTEGER NOT NULL REFERENCES creators(id),
    amount         INTEGER NOT NULL,
    details        TEXT    NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'pending',  -- pending | paid | rejected
    created_at     INTEGER NOT NULL,
    processed_at   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_withdrawals_creator ON withdrawals(creator_id, status);
"""

_ALPHABET = string.ascii_lowercase + string.digits
_conn: aiosqlite.Connection | None = None
# Serializes multi-step writes on the single shared connection
_lock = asyncio.Lock()

Row = aiosqlite.Row


def now() -> int:
    return int(time.time())


def _token(n: int) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def _db() -> aiosqlite.Connection:
    if _conn is None:
        raise RuntimeError("database is not initialized")
    return _conn


async def init(path: str) -> None:
    global _conn
    _conn = await aiosqlite.connect(path)
    _conn.row_factory = aiosqlite.Row
    await _conn.execute("PRAGMA journal_mode=WAL")
    await _conn.execute("PRAGMA foreign_keys=ON")
    await _conn.executescript(SCHEMA)
    await _conn.commit()


async def close() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


async def _one(sql: str, *args: Any) -> Row | None:
    async with _db().execute(sql, args) as cur:
        return await cur.fetchone()


async def _all(sql: str, *args: Any) -> list[Row]:
    async with _db().execute(sql, args) as cur:
        return list(await cur.fetchall())


# ---------- creators ----------

async def create_creator(
    name: str, rate: int, campaign_id: int, campaign_name: str, ref_link: str, count_from: int
) -> Row | None:
    """Returns None if this campaign is already attached to another creator."""
    async with _lock:
        if await _one("SELECT 1 FROM creators WHERE campaign_id = ?", campaign_id):
            return None
        cur = await _db().execute(
            """
            INSERT INTO creators (name, campaign_id, campaign_name, ref_link, count_from, invite_token, rate, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, campaign_id, campaign_name, ref_link, count_from, "join_" + _token(16), rate, now()),
        )
        await _db().commit()
        return await get_creator(cur.lastrowid)


async def get_creator(creator_id: int) -> Row | None:
    return await _one("SELECT * FROM creators WHERE id = ?", creator_id)


async def get_creator_by_tg(tg_id: int) -> Row | None:
    return await _one("SELECT * FROM creators WHERE tg_id = ?", tg_id)


async def get_creator_by_campaign(campaign_id: int) -> Row | None:
    return await _one("SELECT * FROM creators WHERE campaign_id = ?", campaign_id)


async def all_creators() -> list[Row]:
    return await _all("SELECT * FROM creators")


async def bind_creator(invite: str, tg_id: int, username: str | None) -> tuple[str, Row | None]:
    """Attach a Telegram account to a creator. Status: bound | same | invalid | taken | already."""
    async with _lock:
        creator = await _one("SELECT * FROM creators WHERE invite_token = ?", invite)
        if creator is None:
            return "invalid", None
        if creator["tg_id"] == tg_id:
            return "same", creator
        if creator["tg_id"] is not None:
            return "taken", creator
        other = await _one("SELECT * FROM creators WHERE tg_id = ?", tg_id)
        if other is not None:
            return "already", other
        await _db().execute(
            "UPDATE creators SET tg_id = ?, tg_username = ? WHERE id = ?",
            (tg_id, username, creator["id"]),
        )
        await _db().commit()
        return "bound", await get_creator(creator["id"])


async def update_username(creator_id: int, username: str | None) -> None:
    await _db().execute("UPDATE creators SET tg_username = ? WHERE id = ?", (username, creator_id))
    await _db().commit()


async def list_creators() -> list[Row]:
    return await _all(
        """
        SELECT c.*,
               (SELECT COUNT(*) FROM referrals r WHERE r.creator_id = c.id) AS joined,
               (SELECT COUNT(*) FROM referrals r WHERE r.creator_id = c.id AND r.status = 'qualified') AS qualified
        FROM creators c
        ORDER BY c.id DESC
        """
    )


async def set_rate(creator_id: int, rate: int) -> None:
    await _db().execute("UPDATE creators SET rate = ? WHERE id = ?", (rate, creator_id))
    await _db().commit()


async def set_active(creator_id: int, active: bool) -> None:
    await _db().execute("UPDATE creators SET active = ? WHERE id = ?", (int(active), creator_id))
    await _db().commit()


# ---------- referrals ----------

async def known_referral_ids() -> set[int]:
    return {r[0] for r in await _all("SELECT tg_id FROM referrals")}


async def add_referrals(items: list[tuple[int, int, int]]) -> int:
    """items: (creator_id, tg_id, registered_at). Already known users are ignored."""
    if not items:
        return 0
    async with _lock:
        before = _db().total_changes
        await _db().executemany(
            "INSERT OR IGNORE INTO referrals (creator_id, tg_id, registered_at) VALUES (?, ?, ?)",
            items,
        )
        await _db().commit()
        return _db().total_changes - before


async def pending_referrals() -> list[Row]:
    return await _all("SELECT * FROM referrals WHERE status = 'pending' ORDER BY id")


async def expire_pending(before_ts: int) -> int:
    cur = await _db().execute(
        "UPDATE referrals SET status = 'expired', reason = 'no_connection' WHERE status = 'pending' AND registered_at < ?",
        (before_ts,),
    )
    await _db().commit()
    return cur.rowcount


async def qualify_referral(ref_id: int, hwids: list[str]) -> tuple[str, int, Row | None]:
    """Credit the creator at the current rate. Status: ok | duplicate_device | skip."""
    async with _lock:
        ref = await _one(
            "SELECT r.*, c.rate FROM referrals r JOIN creators c ON c.id = r.creator_id WHERE r.id = ?",
            ref_id,
        )
        if ref is None or ref["status"] != "pending":
            return "skip", 0, None
        hwids = sorted(set(hwids))
        if hwids:
            marks = ",".join("?" * len(hwids))
            if await _one(f"SELECT 1 FROM devices WHERE hwid IN ({marks})", *hwids):
                await _db().execute(
                    "UPDATE referrals SET status = 'rejected', reason = 'duplicate_device' WHERE id = ?",
                    (ref_id,),
                )
                await _db().commit()
                return "duplicate_device", 0, None
        amount = int(ref["rate"])
        await _db().execute(
            "UPDATE referrals SET status = 'qualified', amount = ?, qualified_at = ? WHERE id = ?",
            (amount, now(), ref_id),
        )
        await _db().executemany(
            "INSERT OR IGNORE INTO devices (hwid, referral_id) VALUES (?, ?)",
            [(h, ref_id) for h in hwids],
        )
        await _db().commit()
        return "ok", amount, await get_creator(ref["creator_id"])


async def recent_referrals(creator_id: int, limit: int = 20) -> list[Row]:
    return await _all(
        "SELECT * FROM referrals WHERE creator_id = ? ORDER BY registered_at DESC LIMIT ?",
        creator_id, limit,
    )


# ---------- stats ----------

async def creator_stats(creator_id: int, day_start_ts: int) -> dict[str, int]:
    ref = await _one(
        """
        SELECT COUNT(*)                                                   AS joined,
               SUM(registered_at >= ?)                                    AS joined_today,
               SUM(status = 'qualified')                                  AS qualified,
               SUM(status = 'qualified' AND qualified_at >= ?)            AS qualified_today,
               SUM(status = 'pending')                                    AS pending,
               SUM(status IN ('rejected', 'expired'))                     AS rejected,
               SUM(CASE WHEN status = 'qualified' THEN amount ELSE 0 END) AS earned
        FROM referrals WHERE creator_id = ?
        """,
        day_start_ts, day_start_ts, creator_id,
    )
    wd = await _one(
        """
        SELECT SUM(CASE WHEN status = 'paid' THEN amount ELSE 0 END)    AS paid,
               SUM(CASE WHEN status = 'pending' THEN amount ELSE 0 END) AS on_hold
        FROM withdrawals WHERE creator_id = ?
        """,
        creator_id,
    )
    stats = {key: int(ref[key] or 0) for key in ref.keys()}
    stats["paid"] = int(wd["paid"] or 0)
    stats["on_hold"] = int(wd["on_hold"] or 0)
    stats["available"] = stats["earned"] - stats["paid"] - stats["on_hold"]
    return stats


async def totals() -> dict[str, int]:
    row = await _one(
        """
        SELECT (SELECT COUNT(*) FROM creators)                                             AS creators,
               (SELECT COUNT(*) FROM referrals)                                            AS joined,
               (SELECT COUNT(*) FROM referrals WHERE status = 'qualified')                 AS qualified,
               (SELECT COUNT(*) FROM referrals WHERE status = 'pending')                   AS pending,
               (SELECT COALESCE(SUM(amount), 0) FROM referrals WHERE status = 'qualified') AS earned,
               (SELECT COALESCE(SUM(amount), 0) FROM withdrawals WHERE status = 'paid')    AS paid,
               (SELECT COALESCE(SUM(amount), 0) FROM withdrawals WHERE status = 'pending') AS on_hold,
               (SELECT COUNT(*) FROM withdrawals WHERE status = 'pending')                 AS pending_requests
        """
    )
    return {key: int(row[key] or 0) for key in row.keys()}


# ---------- withdrawals ----------

_WITHDRAWAL_SELECT = """
    SELECT w.*, c.name AS creator_name, c.tg_id AS creator_tg, c.tg_username AS creator_username
    FROM withdrawals w JOIN creators c ON c.id = w.creator_id
"""


async def get_withdrawal(withdrawal_id: int) -> Row | None:
    return await _one(_WITHDRAWAL_SELECT + " WHERE w.id = ?", withdrawal_id)


async def create_withdrawal(creator_id: int, details: str, min_amount: int) -> tuple[str, Row | None]:
    """Request payout of the whole available balance. Status: ok | has_pending | too_low."""
    async with _lock:
        if await _one("SELECT 1 FROM withdrawals WHERE creator_id = ? AND status = 'pending'", creator_id):
            return "has_pending", None
        stats = await creator_stats(creator_id, now())
        amount = stats["available"]
        if amount < min_amount:
            return "too_low", None
        cur = await _db().execute(
            "INSERT INTO withdrawals (creator_id, amount, details, created_at) VALUES (?, ?, ?, ?)",
            (creator_id, amount, details, now()),
        )
        await _db().commit()
        return "ok", await get_withdrawal(cur.lastrowid)


async def finish_withdrawal(withdrawal_id: int, status: str) -> Row | None:
    """Move a pending request to paid/rejected. Returns None if it was already processed."""
    if status not in {"paid", "rejected"}:
        raise ValueError(status)
    async with _lock:
        row = await get_withdrawal(withdrawal_id)
        if row is None or row["status"] != "pending":
            return None
        await _db().execute(
            "UPDATE withdrawals SET status = ?, processed_at = ? WHERE id = ?",
            (status, now(), withdrawal_id),
        )
        await _db().commit()
        return await get_withdrawal(withdrawal_id)


async def pending_withdrawals() -> list[Row]:
    return await _all(_WITHDRAWAL_SELECT + " WHERE w.status = 'pending' ORDER BY w.id")


async def creator_withdrawals(creator_id: int, limit: int = 10) -> list[Row]:
    return await _all(
        "SELECT * FROM withdrawals WHERE creator_id = ? ORDER BY id DESC LIMIT ?",
        creator_id, limit,
    )
