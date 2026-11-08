from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _int_set(raw: str) -> frozenset[int]:
    return frozenset(int(x) for x in raw.replace(" ", "").split(",") if x)


# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = _int_set(os.getenv("ADMIN_IDS", ""))
MAIN_BOT_USERNAME = os.getenv("MAIN_BOT_USERNAME", "TitanVPS_bot").lstrip("@")
SUPPORT_CONTACT = os.getenv("SUPPORT_CONTACT", "@TitanVPS_SMM")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Samara")

# Own database of the creator bot
DB_PATH = os.getenv("DB_PATH", "creators.db")

# Main bot database, opened strictly read-only
MAIN_DB_PATH = os.getenv("MAIN_DB_PATH", "/root/bot/vpn_bot.db")
# Used only when the admin sends a campaign ID instead of a link
CAMPAIGN_LINK_TEMPLATE = os.getenv("CAMPAIGN_LINK_TEMPLATE", "https://t.me/{bot}?start={code}")

# Optional Remnawave access (GET requests only) for the "one device = one payment" check
REMNA_URL = os.getenv("REMNA_URL", "").rstrip("/")
REMNA_TOKEN = os.getenv("REMNA_TOKEN", "")

# Business rules
MIN_PAYOUT = int(os.getenv("MIN_PAYOUT", "1000"))
MIN_TRAFFIC_MB = int(os.getenv("MIN_TRAFFIC_MB", "5"))
QUALIFY_DAYS = int(os.getenv("QUALIFY_DAYS", "3"))
CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "300"))

# Filled at startup from bot.get_me()
BOT_USERNAME = ""
