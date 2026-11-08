from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import admin
import config
import db
import ui

log = logging.getLogger(__name__)
router = Router(name="creator")


class Withdraw(StatesGroup):
    details = State()


async def _cabinet(creator: db.Row) -> str:
    st = await db.creator_stats(creator["id"], ui.day_start())
    return ui.cabinet_text(creator, st)


async def notify_admins(bot: Bot, text: str, **kwargs) -> None:
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, **kwargs)
        except TelegramAPIError as exc:
            log.warning("cannot notify admin %s: %s", admin_id, exc)


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено.")


@router.message(CommandStart())
async def start(message: Message, command: CommandObject, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    user = message.from_user
    args = (command.args or "").strip()

    if args.startswith("join_"):
        status, creator = await db.bind_creator(args, user.id, user.username)
        if status == "invalid":
            await message.answer("Ссылка-приглашение недействительна. Обратитесь к администратору.")
            return
        if status == "taken":
            await message.answer("Это приглашение уже использовано другим аккаунтом.")
            return
        if status == "already":
            await message.answer(f"Ваш аккаунт уже подключён к кабинету «{escape(creator['name'])}».")
        if status == "bound":
            await notify_admins(
                bot,
                f"🔔 Креатор «{escape(creator['name'])}» подключился к кабинету: {ui.creator_contact(creator)}",
            )

    creator = await db.get_creator_by_tg(user.id)
    if creator is not None:
        if creator["tg_username"] != user.username:
            await db.update_username(creator["id"], user.username)
        await message.answer(await _cabinet(creator), reply_markup=ui.cabinet_kb())
        return

    if user.id in config.ADMIN_IDS:
        await admin.show_menu(message)
        return

    await message.answer(
        "Этот бот предназначен для авторов TITAN VPS.\n"
        f"Чтобы стать автором, напишите {config.SUPPORT_CONTACT}."
    )


@router.callback_query(F.data == "me:refresh")
async def refresh(call: CallbackQuery) -> None:
    creator = await db.get_creator_by_tg(call.from_user.id)
    if creator is None:
        await call.answer()
        return
    try:
        await call.message.edit_text(await _cabinet(creator), reply_markup=ui.cabinet_kb())
    except TelegramBadRequest:
        pass  # message is not modified
    await call.answer("Обновлено")


@router.callback_query(F.data == "me:history")
async def history(call: CallbackQuery) -> None:
    creator = await db.get_creator_by_tg(call.from_user.id)
    if creator is None:
        await call.answer()
        return
    rows = await db.creator_withdrawals(creator["id"])
    if not rows:
        await call.answer("Выплат пока не было.", show_alert=True)
        return
    lines = ["📜 <b>Последние заявки на вывод</b>", ""]
    for w in rows:
        lines.append(
            f"№{w['id']} · {ui.fmt_date(w['created_at'])} · {ui.money(w['amount'])} · "
            f"{ui.WITHDRAWAL_STATUS.get(w['status'], w['status'])}"
        )
    await call.message.answer("\n".join(lines))
    await call.answer()


@router.callback_query(F.data == "me:withdraw")
async def withdraw_start(call: CallbackQuery, state: FSMContext) -> None:
    creator = await db.get_creator_by_tg(call.from_user.id)
    if creator is None:
        await call.answer()
        return
    st = await db.creator_stats(creator["id"], ui.day_start())
    if st["on_hold"]:
        await call.answer("У вас уже есть заявка на вывод в обработке.", show_alert=True)
        return
    if st["available"] < config.MIN_PAYOUT:
        await call.answer(
            f"Вывод доступен от {ui.money(config.MIN_PAYOUT)}. Сейчас доступно {ui.money(st['available'])}.",
            show_alert=True,
        )
        return
    await state.set_state(Withdraw.details)
    await call.message.answer(
        f"К выводу: <b>{ui.money(st['available'])}</b>.\n\n"
        "Отправьте реквизиты одним сообщением: номер карты или телефон для СБП с названием банка "
        "либо адрес кошелька USDT (TRC-20).\n\n"
        "Для отмены отправьте /cancel."
    )
    await call.answer()


@router.message(Withdraw.details, F.text)
async def withdraw_details(message: Message, state: FSMContext, bot: Bot) -> None:
    creator = await db.get_creator_by_tg(message.from_user.id)
    await state.clear()
    if creator is None:
        return
    details = message.text.strip()[:300]
    status, w = await db.create_withdrawal(creator["id"], details, config.MIN_PAYOUT)
    if status == "has_pending":
        await message.answer("У вас уже есть заявка на вывод в обработке.")
        return
    if status == "too_low":
        await message.answer(f"Недостаточно средств: вывод доступен от {ui.money(config.MIN_PAYOUT)}.")
        return
    await message.answer(
        f"✅ Заявка №{w['id']} на {ui.money(w['amount'])} принята. "
        "Мы сообщим, когда выплата будет отправлена."
    )
    await notify_admins(bot, ui.withdrawal_text(w), reply_markup=ui.withdrawal_kb(w["id"]))


@router.message(Withdraw.details)
async def withdraw_details_not_text(message: Message) -> None:
    await message.answer("Отправьте реквизиты текстом или /cancel для отмены.")
