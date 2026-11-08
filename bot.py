from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage

import admin
import config
import creator
import db
import main_db
import ui
from remna import Remnawave

log = logging.getLogger("creator_bot")


async def sync_once(bot: Bot | None, remna: Remnawave | None) -> dict[str, int]:
    """Pull new users of creator campaigns from the main bot DB and credit those who connected."""
    result = {"new": 0, "qualified": 0, "duplicate_device": 0, "expired": 0}
    creators = {c["campaign_id"]: c for c in await db.all_creators()}
    if not creators:
        return result

    users = await main_db.invited_users(creators.keys())
    known = await db.known_referral_ids()
    by_tg: dict[int, dict] = {}
    new_items: list[tuple[int, int, int]] = []
    for u in users:
        owner = creators[u["invited_by"]]
        registered = main_db.parse_dt(u["created_at"])
        if registered is None or registered < owner["count_from"]:
            continue
        by_tg[u["telegram_id"]] = u
        if u["telegram_id"] not in known and owner["active"]:
            new_items.append((owner["id"], u["telegram_id"], registered))
    result["new"] = await db.add_referrals(new_items)

    min_bytes = config.MIN_TRAFFIC_MB * 1024 * 1024
    for ref in await db.pending_referrals():
        u = by_tg.get(ref["tg_id"])
        if u is None or not main_db.is_connected(u, min_bytes):
            continue
        hwids: list[str] = []
        if remna is not None and u.get("remnawave_username"):
            hwids = await remna.hwids_by_username(u["remnawave_username"])
        status, amount, owner = await db.qualify_referral(ref["id"], hwids)
        if status == "duplicate_device":
            result["duplicate_device"] += 1
            continue
        if status != "ok":
            continue
        result["qualified"] += 1
        log.info("qualified tg_id=%s creator=%s amount=%s", ref["tg_id"], owner["id"], amount)
        if bot is not None and owner["tg_id"]:
            st = await db.creator_stats(owner["id"], ui.day_start())
            try:
                await bot.send_message(
                    owner["tg_id"],
                    f"✅ Новый пользователь подключил устройство: +{ui.money(amount)}\n"
                    f"Доступно к выводу: {ui.money(st['available'])}",
                )
            except TelegramAPIError as exc:
                log.warning("cannot notify creator %s: %s", owner["id"], exc)

    # Expire only after the qualification pass, so already connected users are credited first
    result["expired"] = await db.expire_pending(db.now() - config.QUALIFY_DAYS * 86400)
    return result


async def sync_loop(bot: Bot, remna: Remnawave | None) -> None:
    while True:
        try:
            stats = await sync_once(bot, remna)
            if any(stats.values()):
                log.info("sync: %s", stats)
        except Exception:
            log.exception("sync cycle failed")
        await asyncio.sleep(config.CHECK_INTERVAL_SEC)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    if not config.BOT_TOKEN or not config.ADMIN_IDS:
        sys.exit("Fill in BOT_TOKEN and ADMIN_IDS in .env")

    await db.init(config.DB_PATH)
    bot = Bot(
        config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    config.BOT_USERNAME = (await bot.get_me()).username

    remna: Remnawave | None = None
    if config.REMNA_URL and config.REMNA_TOKEN:
        remna = Remnawave(config.REMNA_URL, config.REMNA_TOKEN)
        await remna.start()
        log.info("HWID check via Remnawave is enabled")

    syncer = asyncio.create_task(sync_loop(bot, remna))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_routers(creator.router, admin.router)
    log.info("creator bot @%s started", config.BOT_USERNAME)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        syncer.cancel()
        if remna is not None:
            await remna.close()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
