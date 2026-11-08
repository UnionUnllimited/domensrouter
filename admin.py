from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import db
import main_db
import ui

log = logging.getLogger(__name__)
router = Router(name="admin")
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

PAGE_SIZE = 20
MAX_RATE = 100_000


class NewCreator(StatesGroup):
    name = State()
    rate = State()
    campaign = State()
    history = State()


class EditRate(StatesGroup):
    rate = State()


def _parse_rate(text: str) -> int | None:
    raw = text.replace(" ", "").replace("₽", "").replace("руб", "")
    if not raw.isdigit():
        return None
    value = int(raw)
    return value if 0 < value <= MAX_RATE else None


def menu_kb(pending_requests: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Новый креатор", callback_data="adm:new")
    kb.button(text="👥 Креаторы", callback_data="adm:list:0")
    kb.button(
        text=f"💸 Заявки на вывод ({pending_requests})" if pending_requests else "💸 Заявки на вывод",
        callback_data="adm:wd",
    )
    kb.button(text="📊 Сводка", callback_data="adm:sum")
    kb.adjust(1)
    return kb.as_markup()


async def show_menu(message: Message, edit: bool = False) -> None:
    t = await db.totals()
    text = "🛠 <b>Панель администратора</b>"
    if edit:
        try:
            await message.edit_text(text, reply_markup=menu_kb(t["pending_requests"]))
            return
        except TelegramBadRequest:
            pass
    await message.answer(text, reply_markup=menu_kb(t["pending_requests"]))


async def _send_card(message: Message, creator_id: int, edit: bool) -> None:
    creator = await db.get_creator(creator_id)
    if creator is None:
        await message.answer("Креатор не найден.")
        return
    st = await db.creator_stats(creator_id, ui.day_start())
    text = ui.admin_creator_text(creator, st)
    kb = ui.admin_creator_kb(creator)
    if edit:
        try:
            await message.edit_text(text, reply_markup=kb)
            return
        except TelegramBadRequest as exc:
            if "not modified" in str(exc):
                return
    await message.answer(text, reply_markup=kb)


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_menu(message)


@router.callback_query(F.data == "adm:menu")
async def cb_menu(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show_menu(call.message, edit=True)
    await call.answer()


# ---------- new creator ----------

@router.callback_query(F.data == "adm:new")
async def new_creator(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(NewCreator.name)
    await call.message.answer("Введите имя креатора (например, ник в TikTok).\nДля отмены отправьте /cancel.")
    await call.answer()


@router.message(NewCreator.name, F.text)
async def new_creator_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()[:64]
    if not name:
        await message.answer("Имя не может быть пустым.")
        return
    await state.update_data(name=name)
    await state.set_state(NewCreator.rate)
    await message.answer(
        "Сколько рублей креатор получит за одного нового пользователя, "
        "который зарегистрировался и подключил устройство? Введите число."
    )


@router.message(NewCreator.rate, F.text)
async def new_creator_rate(message: Message, state: FSMContext) -> None:
    rate = _parse_rate(message.text)
    if rate is None:
        await message.answer(f"Введите целое число от 1 до {MAX_RATE}.")
        return
    await state.update_data(rate=rate)
    await state.set_state(NewCreator.campaign)
    await message.answer(
        "Создайте для креатора кампанию в админке основного бота (раздел «Продвижение») "
        "и пришлите сюда её ссылку. Можно прислать и ID кампании."
    )


@router.message(NewCreator.campaign, F.text)
async def new_creator_campaign(message: Message, state: FSMContext) -> None:
    try:
        campaign = await main_db.find_campaign(message.text)
    except Exception:
        log.exception("main database lookup failed")
        await message.answer("Не удалось прочитать базу основного бота. Проверьте MAIN_DB_PATH в .env.")
        return
    if campaign is None:
        await message.answer("Кампания не найдена. Проверьте ссылку или ID и пришлите ещё раз.")
        return
    owner = await db.get_creator_by_campaign(campaign["id"])
    if owner is not None:
        await message.answer(f"Эта кампания уже закреплена за креатором «{escape(owner['name'])}».")
        return
    await state.update_data(campaign=campaign)
    if campaign["invited"] == 0:
        await _finish_creator(message, state, count_from=db.now())
        return
    await state.set_state(NewCreator.history)
    kb = InlineKeyboardBuilder()
    kb.button(text="Только новых", callback_data="adm:from:new")
    kb.button(text=f"Засчитать уже пришедших ({campaign['invited']})", callback_data="adm:from:all")
    kb.adjust(1)
    await message.answer(
        f"Кампания: <b>{escape(campaign['name'])}</b> (ID {campaign['id']}).\n"
        f"По ней уже пришло {campaign['invited']} чел. Засчитать их креатору или учитывать только новых?\n\n"
        f"Если засчитать, оплачиваются все из них, кто уже подключал устройство.",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(NewCreator.history, F.data.startswith("adm:from:"))
async def new_creator_history(call: CallbackQuery, state: FSMContext) -> None:
    count_from = 0 if call.data.endswith(":all") else db.now()
    await call.message.edit_reply_markup(reply_markup=None)
    await _finish_creator(call.message, state, count_from)
    await call.answer()


async def _finish_creator(message: Message, state: FSMContext, count_from: int) -> None:
    data = await state.get_data()
    await state.clear()
    campaign = data["campaign"]
    creator = await db.create_creator(
        data["name"], data["rate"], campaign["id"], campaign["name"], campaign["link"], count_from
    )
    if creator is None:
        await message.answer("Эта кампания уже закреплена за другим креатором.")
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="Открыть карточку", callback_data=f"adm:c:{creator['id']}")
    kb.button(text="⬅️ В меню", callback_data="adm:menu")
    kb.adjust(1)
    text = ui.created_text(creator)
    if campaign["link_from_template"]:
        text += "\n\n⚠️ Ссылка собрана по ID. Сверьте её со ссылкой кампании в админке основного бота."
    await message.answer(text, reply_markup=kb.as_markup())


# ---------- creators list and card ----------

@router.callback_query(F.data.startswith("adm:list:"))
async def creators_list(call: CallbackQuery) -> None:
    page = max(int(call.data.split(":")[2]), 0)
    rows = await db.list_creators()
    if not rows:
        await call.answer("Креаторов пока нет.", show_alert=True)
        return
    pages = (len(rows) - 1) // PAGE_SIZE + 1
    page = min(page, pages - 1)
    kb = InlineKeyboardBuilder()
    for r in rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
        mark = "" if r["active"] else "⏸ "
        kb.button(
            text=f"{mark}{r['name']} · {r['rate']} ₽ · {r['qualified']}/{r['joined']}",
            callback_data=f"adm:c:{r['id']}",
        )
    sizes = [1] * min(PAGE_SIZE, len(rows) - page * PAGE_SIZE)
    nav = 0
    if page > 0:
        kb.button(text="◀️", callback_data=f"adm:list:{page - 1}")
        nav += 1
    if page < pages - 1:
        kb.button(text="▶️", callback_data=f"adm:list:{page + 1}")
        nav += 1
    if nav:
        sizes.append(nav)
    kb.button(text="⬅️ В меню", callback_data="adm:menu")
    sizes.append(1)
    kb.adjust(*sizes)
    text = f"👥 <b>Креаторы</b> (подключили / пришли), стр. {page + 1} из {pages}"
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest:
        await call.message.answer(text, reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("adm:c:"))
async def creator_card(call: CallbackQuery) -> None:
    await _send_card(call.message, int(call.data.split(":")[2]), edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("adm:toggle:"))
async def creator_toggle(call: CallbackQuery) -> None:
    cid = int(call.data.split(":")[2])
    creator = await db.get_creator(cid)
    if creator is None:
        await call.answer("Креатор не найден.", show_alert=True)
        return
    await db.set_active(cid, not creator["active"])
    await _send_card(call.message, cid, edit=True)
    await call.answer("Креатор включён" if not creator["active"] else "Креатор отключён")


@router.callback_query(F.data.startswith("adm:refs:"))
async def creator_refs(call: CallbackQuery) -> None:
    cid = int(call.data.split(":")[2])
    rows = await db.recent_referrals(cid, 20)
    if not rows:
        await call.answer("Пользователей пока нет.", show_alert=True)
        return
    lines = ["📋 <b>Последние 20 пользователей</b>", ""]
    for r in rows:
        status = ui.REFERRAL_STATUS.get(r["status"], r["status"])
        if r["reason"] in ui.REJECT_REASON and r["status"] != "expired":
            status += f" ({ui.REJECT_REASON[r['reason']]})"
        amount = f" · +{ui.money(r['amount'])}" if r["status"] == "qualified" else ""
        lines.append(f"<code>{r['tg_id']}</code> · {ui.fmt_date(r['registered_at'])} · {status}{amount}")
    await call.message.answer("\n".join(lines))
    await call.answer()


@router.callback_query(F.data.startswith("adm:rate:"))
async def rate_start(call: CallbackQuery, state: FSMContext) -> None:
    cid = int(call.data.split(":")[2])
    creator = await db.get_creator(cid)
    if creator is None:
        await call.answer("Креатор не найден.", show_alert=True)
        return
    await state.set_state(EditRate.rate)
    await state.update_data(creator_id=cid)
    await call.message.answer(
        f"Введите новую ставку для «{escape(creator['name'])}» (сейчас {ui.money(creator['rate'])}).\n"
        "Она будет применяться к новым подключениям. Для отмены отправьте /cancel."
    )
    await call.answer()


@router.message(EditRate.rate, F.text)
async def rate_set(message: Message, state: FSMContext, bot: Bot) -> None:
    rate = _parse_rate(message.text)
    if rate is None:
        await message.answer(f"Введите целое число от 1 до {MAX_RATE}.")
        return
    cid = (await state.get_data())["creator_id"]
    await state.clear()
    await db.set_rate(cid, rate)
    creator = await db.get_creator(cid)
    await message.answer(f"Ставка для «{escape(creator['name'])}» обновлена: {ui.money(rate)}.")
    if creator["tg_id"]:
        try:
            await bot.send_message(
                creator["tg_id"],
                f"💰 Ваша ставка изменена: теперь {ui.money(rate)} за каждого нового пользователя, "
                "который подключил устройство.",
            )
        except TelegramAPIError as exc:
            log.warning("cannot notify creator %s: %s", cid, exc)
    await _send_card(message, cid, edit=False)


# ---------- withdrawals ----------

@router.callback_query(F.data == "adm:wd")
async def withdrawals_list(call: CallbackQuery) -> None:
    rows = await db.pending_withdrawals()
    if not rows:
        await call.answer("Заявок на вывод нет.", show_alert=True)
        return
    for w in rows:
        await call.message.answer(ui.withdrawal_text(w), reply_markup=ui.withdrawal_kb(w["id"]))
    await call.answer()


@router.callback_query(F.data.startswith("wd:"))
async def withdrawal_action(call: CallbackQuery, bot: Bot) -> None:
    _, status, wid = call.data.split(":")
    w = await db.finish_withdrawal(int(wid), status)
    if w is None:
        await call.answer("Заявка уже обработана.", show_alert=True)
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        return
    label = "✅ Выплачено" if status == "paid" else "❌ Отклонено, сумма возвращена на баланс"
    await call.message.edit_text(f"{ui.withdrawal_text(w)}\n\n<b>{label}</b>", reply_markup=None)
    await call.answer()
    if w["creator_tg"]:
        if status == "paid":
            text = f"✅ Выплата по заявке №{w['id']} на {ui.money(w['amount'])} отправлена."
        else:
            text = (
                f"Заявка №{w['id']} на {ui.money(w['amount'])} отклонена, сумма возвращена на баланс.\n"
                f"По вопросам обращайтесь к {config.SUPPORT_CONTACT}."
            )
        try:
            await bot.send_message(w["creator_tg"], text)
        except TelegramAPIError as exc:
            log.warning("cannot notify creator about withdrawal %s: %s", wid, exc)


# ---------- summary ----------

@router.callback_query(F.data == "adm:sum")
async def summary(call: CallbackQuery) -> None:
    t = await db.totals()
    text = (
        "📊 <b>Сводка</b>\n\n"
        f"Креаторов: {t['creators']}\n"
        f"Пришли по ссылкам: {t['joined']}\n"
        f"Подключили устройство: {t['qualified']}\n"
        f"Ожидают подключения: {t['pending']}\n\n"
        f"Начислено креаторам: {ui.money(t['earned'])}\n"
        f"Выплачено: {ui.money(t['paid'])}\n"
        f"В заявках на вывод: {ui.money(t['on_hold'])} ({t['pending_requests']} шт.)\n"
        f"Всего к выплате: <b>{ui.money(t['earned'] - t['paid'])}</b>"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В меню", callback_data="adm:menu")
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest:
        pass
    await call.answer()
