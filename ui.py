from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import Row

TZ = ZoneInfo(config.TIMEZONE)

WITHDRAWAL_STATUS = {
    "pending": "⏳ в обработке",
    "paid": "✅ выплачено",
    "rejected": "❌ отклонено",
}

REFERRAL_STATUS = {
    "pending": "⏳ ждёт подключения",
    "qualified": "✅ засчитан",
    "rejected": "❌ не засчитан",
    "expired": "⌛ не подключился",
}

REJECT_REASON = {
    "duplicate_device": "повторное устройство",
    "no_connection": "не подключил устройство",
}


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₽"


def days(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        word = "день"
    elif n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        word = "дня"
    else:
        word = "дней"
    return f"{n} {word}"


def fmt_date(ts: int | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, TZ).strftime("%d.%m.%Y %H:%M")


def day_start() -> int:
    now = datetime.now(TZ)
    return int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def ref_link(creator: Row) -> str:
    return creator["ref_link"]


def invite_link(creator: Row) -> str:
    return f"https://t.me/{config.BOT_USERNAME}?start={creator['invite_token']}"


def stats_block(st: dict[str, int]) -> str:
    lines = [
        "📊 <b>Статистика</b>",
        f"Пришли по ссылке: <b>{st['joined']}</b> (сегодня {st['joined_today']})",
        f"Подключили устройство: <b>{st['qualified']}</b> (сегодня {st['qualified_today']})",
        f"Ожидают подключения: {st['pending']}",
    ]
    if st["rejected"]:
        lines.append(f"Не засчитаны: {st['rejected']} (не подключились за {days(config.QUALIFY_DAYS)} или повторное устройство)")
    lines += [
        "",
        "💵 <b>Финансы</b>",
        f"Заработано: {money(st['earned'])}",
        f"Выплачено: {money(st['paid'])}",
    ]
    if st["on_hold"]:
        lines.append(f"На выводе: {money(st['on_hold'])}")
    lines.append(f"Доступно к выводу: <b>{money(st['available'])}</b>")
    return "\n".join(lines)


def cabinet_text(creator: Row, st: dict[str, int]) -> str:
    paused = "" if creator["active"] else "⏸ Ссылка временно отключена, новые пользователи не засчитываются.\n\n"
    return (
        f"👤 <b>Кабинет автора: {escape(creator['name'])}</b>\n\n"
        f"🔗 Ваша ссылка:\n<code>{ref_link(creator)}</code>\n\n"
        f"{paused}"
        f"💰 Ставка: <b>{money(creator['rate'])}</b> за каждого нового пользователя, "
        f"который зарегистрировался и подключил устройство.\n\n"
        f"{stats_block(st)}\n\n"
        f"Вывод доступен от {money(config.MIN_PAYOUT)}."
    )


def cabinet_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Обновить", callback_data="me:refresh")
    kb.button(text="💸 Вывести средства", callback_data="me:withdraw")
    kb.button(text="📜 История выплат", callback_data="me:history")
    kb.adjust(1)
    return kb.as_markup()


def creator_contact(creator: Row) -> str:
    if creator["tg_id"] is None:
        return "ещё не подключился"
    if creator["tg_username"]:
        return f"@{escape(creator['tg_username'])} (id {creator['tg_id']})"
    return f"id {creator['tg_id']}"


def admin_creator_text(creator: Row, st: dict[str, int]) -> str:
    state = "активен" if creator["active"] else "⏸ отключён (новые пользователи не засчитываются)"
    parts = [
        f"👤 <b>{escape(creator['name'])}</b> — {state}",
        f"Telegram: {creator_contact(creator)}",
        f"Создан: {fmt_date(creator['created_at'])}",
        f"Ставка: <b>{money(creator['rate'])}</b>",
        f"Кампания: {escape(creator['campaign_name'] or '')} (ID <code>{creator['campaign_id']}</code>)",
        f"Учёт с: {fmt_date(creator['count_from']) if creator['count_from'] else 'с запуска кампании'}",
        "",
        f"Реферальная ссылка:\n<code>{ref_link(creator)}</code>",
    ]
    if creator["tg_id"] is None:
        parts += ["", f"Приглашение в кабинет (отправьте креатору):\n<code>{invite_link(creator)}</code>"]
    parts += ["", stats_block(st)]
    return "\n".join(parts)


def admin_creator_kb(creator: Row) -> InlineKeyboardMarkup:
    cid = creator["id"]
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Изменить ставку", callback_data=f"adm:rate:{cid}")
    kb.button(text="📋 Последние пользователи", callback_data=f"adm:refs:{cid}")
    kb.button(
        text="⏸ Отключить" if creator["active"] else "▶️ Включить",
        callback_data=f"adm:toggle:{cid}",
    )
    kb.button(text="🔄 Обновить", callback_data=f"adm:c:{cid}")
    kb.button(text="⬅️ К списку", callback_data="adm:list:0")
    kb.adjust(1)
    return kb.as_markup()


def created_text(creator: Row) -> str:
    return (
        f"✅ Креатор «{escape(creator['name'])}» создан. Ставка: {money(creator['rate'])}.\n"
        f"Кампания: {escape(creator['campaign_name'] or '')} (ID {creator['campaign_id']}).\n\n"
        f"1️⃣ Приглашение в кабинет — отправьте креатору, по нему он откроет свою статистику:\n"
        f"<code>{invite_link(creator)}</code>\n\n"
        f"2️⃣ Реферальная ссылка — её креатор размещает у себя (она также будет в его кабинете):\n"
        f"<code>{ref_link(creator)}</code>"
    )


def withdrawal_text(w: Row) -> str:
    who = escape(w["creator_name"])
    if w["creator_username"]:
        who += f" (@{escape(w['creator_username'])})"
    return (
        f"💸 <b>Заявка на вывод №{w['id']}</b>\n"
        f"Креатор: {who}\n"
        f"Сумма: <b>{money(w['amount'])}</b>\n"
        f"Создана: {fmt_date(w['created_at'])}\n"
        f"Реквизиты:\n<code>{escape(w['details'])}</code>"
    )


def withdrawal_kb(withdrawal_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Выплачено", callback_data=f"wd:paid:{withdrawal_id}")
    kb.button(text="❌ Отклонить", callback_data=f"wd:rejected:{withdrawal_id}")
    kb.adjust(2)
    return kb.as_markup()
