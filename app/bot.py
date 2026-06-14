from __future__ import annotations

import asyncio
import html
import logging
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.game import (
    BUILDINGS,
    SHOP_ITEMS,
    APPOINTABLE_TITLES,
    active_incoming_raids,
    admin_stats,
    appoint_city_official,
    buy_shop_item,
    build_city_building,
    build_newspaper,
    building_payload,
    city_payload,
    city_population,
    collect_daily_reward,
    create_court_event,
    create_daily_event,
    create_drama_event,
    create_mayor_election,
    create_new_event_if_due,
    create_raid_challenge,
    daily_payload,
    display_player,
    event_payload,
    find_city_player_by_username,
    get_or_create_city,
    get_or_create_player,
    help_city_quest,
    join_city,
    maybe_roll_season,
    player_profile,
    quest_payload,
    recent_logs,
    resolve_event,
    resolve_raid_challenge,
    season_payload,
    shop_payload,
    start_war,
    top_cities,
    top_players,
    vote_event,
    weekly_summary,
    city_officials,
    city_alliances,
    create_city_alliance,
    register_city_referral,
    work,
)
from app.models import City

logger = logging.getLogger(__name__)
router = Router(name="chatograd-router")

BRAND = "Чатоград"


def h(value: Any) -> str:
    return html.escape(str(value), quote=False)


def is_group(message: Message) -> bool:
    return message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}


def is_private(message: Message) -> bool:
    return message.chat.type == ChatType.PRIVATE


def is_group_callback(callback: CallbackQuery) -> bool:
    message = callback.message
    return isinstance(message, Message) and message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}


async def delete_callback_message(callback: CallbackQuery) -> None:
    """Deprecated no-op.

    Older versions deleted the button message before sending a new one.
    v0.8.1 keeps the chat clean by editing the existing bot message instead.
    The function stays here so older callback handlers remain simple and safe.
    """
    return


def is_bot_owned_message(message: Message) -> bool:
    return bool(message.from_user and getattr(message.from_user, "is_bot", False))


async def try_edit_game_message(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup)
        return True
    except Exception:
        logger.debug("Could not edit managed bot message %s in chat %s", message_id, chat_id, exc_info=True)
        return False


def is_human_user(user: Any | None) -> bool:
    return bool(user and not getattr(user, "is_bot", False))


async def ensure_city_member_from_user(message: Message, user: Any | None, silent: bool = True) -> bool:
    if not is_group(message) or not is_human_user(user):
        return False
    owner = await is_user_chat_owner(message.bot, message.chat.id, user.id)
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        player, _, _ = get_or_create_player(db, user.id, user.username, user.first_name)
        _membership, created = join_city(db, city, player, is_chat_owner=owner)
    return created


def is_member_payload(db, city: City, user: Any | None) -> tuple[bool, bool]:
    if not is_human_user(user):
        return False, False
    from app.models import Membership, Player
    player = db.scalar(select(Player).where(Player.telegram_user_id == user.id))
    if not player:
        return False, False
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    if not membership:
        return False, False
    return True, membership.special_title == "Основатель района"


async def is_user_chat_owner(bot: Bot, chat_id: int, user_id: int | None) -> bool:
    if user_id is None:
        return False
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        logger.exception("Cannot check chat owner for chat %s user %s", chat_id, user_id)
        return False
    return member.status == ChatMemberStatus.CREATOR or str(member.status) == "creator"


def private_start_keyboard(bot_username: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if bot_username:
        rows.append([InlineKeyboardButton(text="➕ Добавить в чат", url=f"https://t.me/{bot_username}?startgroup=true")])
    rows.append([InlineKeyboardButton(text="🌍 Топ городов", callback_data="cc:global_top")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏙 Панель города", callback_data="cc:city")]])


def city_panel_keyboard(is_member: bool = True, is_founder: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if not is_member:
        rows.append([InlineKeyboardButton(text="✅ Вступить", callback_data="cc:join")])
    rows.extend([
        [
            InlineKeyboardButton(text="🏙 Город", callback_data="cc:city"),
            InlineKeyboardButton(text="👤 Я", callback_data="cc:profile"),
        ],
        [
            InlineKeyboardButton(text="🎲 Движ", callback_data="cc:move"),
            InlineKeyboardButton(text="⚔️ Война", callback_data="cc:war"),
        ],
        [
            InlineKeyboardButton(text="🌍 Топ городов", callback_data="cc:global_top"),
            InlineKeyboardButton(text="⚙️ Ещё", callback_data="cc:more"),
        ],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def move_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💼 Работать", callback_data="cc:work"),
            InlineKeyboardButton(text="🎁 Награда", callback_data="cc:daily"),
        ],
        [
            InlineKeyboardButton(text="🎯 Квест", callback_data="cc:quest"),
            InlineKeyboardButton(text="🎲 Событие", callback_data="cc:event"),
        ],
        [
            InlineKeyboardButton(text="🔥 Драма", callback_data="cc:drama"),
            InlineKeyboardButton(text="🗞 Газета", callback_data="cc:newspaper"),
        ],
        [InlineKeyboardButton(text="🏙 Назад", callback_data="cc:city")],
    ])


def war_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚔️ Рейд", callback_data="cc:raid_help"),
            InlineKeyboardButton(text="⚔️ Входящие", callback_data="cc:raids"),
        ],
        [
            InlineKeyboardButton(text="🤝 Союзы", callback_data="cc:alliances"),
            InlineKeyboardButton(text="📣 Позвать", callback_data="cc:invite_bot"),
        ],
        [InlineKeyboardButton(text="🏙 Назад", callback_data="cc:city")],
    ])


def more_keyboard(is_founder: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="🏗 Постройки", callback_data="cc:buildings"),
            InlineKeyboardButton(text="🛒 Магазин", callback_data="cc:shop"),
        ],
        [
            InlineKeyboardButton(text="⚖️ Суд", callback_data="cc:court"),
            InlineKeyboardButton(text="🗳 Выборы", callback_data="cc:election"),
        ],
        [
            InlineKeyboardButton(text="🧩 Должности", callback_data="cc:officials"),
            InlineKeyboardButton(text="📆 Сезон", callback_data="cc:season"),
        ],
        [
            InlineKeyboardButton(text="📆 Итоги", callback_data="cc:weekly"),
            InlineKeyboardButton(text="📜 Логи", callback_data="cc:logs"),
        ],
    ]
    if not is_founder:
        rows.append([InlineKeyboardButton(text="👑 Основатель", callback_data="cc:founder")])
    rows.append([InlineKeyboardButton(text="🏙 Назад", callback_data="cc:city")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def panel_keyboard_for_user(is_member: bool = True, is_founder: bool = False) -> InlineKeyboardMarkup:
    return city_panel_keyboard(is_member=is_member, is_founder=is_founder)


def event_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1️⃣ Голос 1", callback_data="cc:vote:1"),
                InlineKeyboardButton(text="2️⃣ Голос 2", callback_data="cc:vote:2"),
                InlineKeyboardButton(text="3️⃣ Голос 3", callback_data="cc:vote:3"),
            ],
            [InlineKeyboardButton(text="🏁 Завершить голосование", callback_data="cc:resolve")],
            [InlineKeyboardButton(text="🏙 Панель города", callback_data="cc:city")],
        ]
    )


async def get_bot_username(bot: Bot) -> str | None:
    try:
        me = await bot.get_me()
        return me.username
    except Exception:
        logger.exception("Cannot fetch bot username")
        return None


def render_city_status(payload: dict[str, Any], created: bool = False) -> str:
    created_line = "\nГород основан." if created else ""
    buildings = payload.get("buildings") or []
    building_line = ", ".join(h(item) for item in buildings[:4]) if buildings else "нет"
    trophies = payload.get("trophies") or []
    trophy_line = ", ".join(h(item) for item in trophies[:3]) if trophies else "нет"
    return (
        f"🏙 <b>{h(payload['name'])}</b>{created_line}\n\n"
        f"Чат: <b>{h(payload['title'])}</b>\n"
        f"Статус: <b>{h(payload.get('rank', 'Подъезд'))}</b>\n"
        f"Уровень: <b>{payload['level']}</b> · Опыт: <b>{payload['xp']}</b>\n"
        f"Казна: <b>{payload['treasury']}</b> · Жители: <b>{payload['population']}</b>\n"
        f"Сила: <b>{payload['power']}</b> · Угроза: <b>{payload['threat']}</b>\n"
        f"Постройки: {building_line}\n"
        f"Трофеи: {trophy_line}\n"
        f"Код рейдов: <code>{h(payload['invite_code'])}</code>"
    )


def render_event(payload: dict[str, Any]) -> str:
    return (
        f"🎲 <b>{h(payload['title'])}</b>\n\n"
        f"{h(payload['text'])}\n\n"
        f"1️⃣ {h(payload['options'][0])}\n"
        f"2️⃣ {h(payload['options'][1])}\n"
        f"3️⃣ {h(payload['options'][2])}\n\n"
        f"Голоса: 1️⃣ <b>{payload['votes']['1']}</b> · "
        f"2️⃣ <b>{payload['votes']['2']}</b> · "
        f"3️⃣ <b>{payload['votes']['3']}</b>"
    )


def render_quest(payload: dict[str, Any]) -> str:
    status = "✅ выполнен" if payload["completed"] else "🔥 активен"
    return (
        f"🎯 <b>{h(payload['title'])}</b> — {status}\n\n"
        f"{h(payload['text'])}\n\n"
        f"Прогресс: <b>{payload['progress']}</b>/<b>{payload['goal']}</b>\n"
        f"Награда города: <b>+{payload['reward']}</b> монет в казну"
    )


def quest_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤝 Помочь квесту", callback_data="cc:quest_help")],
            [InlineKeyboardButton(text="🏙 Панель города", callback_data="cc:city")],
        ]
    )


def render_newspaper(payload: dict[str, Any]) -> str:
    city = payload["city"]
    quest = payload["quest"]
    hero = payload.get("hero")
    suspect = payload.get("suspect")
    event = payload.get("event")
    lines = [
        f"🗞 <b>Газета Чатограда: {h(city['name'])}</b>",
        "",
        f"🏙 {h(city.get('rank', 'Подъезд'))} · ур. <b>{city['level']}</b> · казна <b>{city['treasury']}</b> · жители <b>{city['population']}</b> · сила <b>{city['power']}</b>",
        f"🎯 Квест дня: <b>{quest['progress']}/{quest['goal']}</b>",
    ]
    if city.get("buildings"):
        lines.append("🏗 Постройки: " + ", ".join(h(item) for item in city["buildings"][:4]))
    if city.get("trophies"):
        lines.append("🏆 Трофеи: " + ", ".join(h(item) for item in city["trophies"][:3]))
    if hero:
        lines.append(f"⭐ Герой выпуска: <b>{h(hero['name'])}</b> — {h(hero['title'])}")
    if suspect:
        lines.append(f"🕵️ Подозрительный тип дня: <b>{h(suspect['name'])}</b>. Без доказательств, чисто вайб.")
    if event:
        lines.append(f"🎲 Активное событие: <b>{h(event['title'])}</b>")
    if payload["logs"]:
        lines.append("\n📌 Последние новости:")
        lines.extend(f"• {h(item['text'])}" for item in payload["logs"][:5])
    else:
        lines.append("\n📌 Новостей нет. Город слишком тихий, это почти преступление.")
    return "\n".join(lines)


def render_profile(payload: dict[str, Any]) -> str:
    daily = "доступна" if payload.get("daily_available") else "забрана"
    return (
        f"👤 <b>{h(payload['name'])}</b>\n\n"
        f"Титул: <b>{h(payload['title'])}</b>\n"
        f"Роль: <b>{h(payload['role'])}</b>\n"
        f"Статус: <b>{h(payload['status'])}</b>\n"
        f"Уровень: <b>{payload['level']}</b> · XP: <b>{payload['xp_in_level']}</b>/<b>{payload['xp_for_next']}</b>\n"
        f"Монеты: <b>{payload['coins']}</b> · Серия: <b>{payload['daily_streak']}</b> дней · Награда: <b>{daily}</b>\n"
        f"Влияние: <b>{payload['influence']}</b> · Репутация: <b>{payload['reputation']}</b>\n"
        f"Судимости: <b>{payload['convictions']}</b>"
    )


def render_buildings(payload: dict[str, Any], city_treasury: int) -> str:
    lines = [f"🏗 <b>Постройки города</b>", "", f"Казна: <b>{city_treasury}</b>", ""]
    for item in payload["items"]:
        lines.append(f"{h(item['name'])} · ур. <b>{item['level']}</b> · цена <b>{item['cost']}</b>")
    return "\n".join(lines)


def buildings_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for key, spec in BUILDINGS.items():
        rows.append([InlineKeyboardButton(text=str(spec["name"]), callback_data=f"cc:build:{key}")])
    rows.append([InlineKeyboardButton(text="🏙 Панель города", callback_data="cc:city")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def raid_accept_keyboard(war_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ Принять рейд", callback_data=f"cc:raid_accept:{war_id}")],
            [InlineKeyboardButton(text="🏙 Панель города", callback_data="cc:city")],
        ]
    )


def render_incoming_raids(items: list[dict[str, Any]]) -> str:
    if not items:
        return "⚔️ <b>Рейды</b>\n\nВходящих вызовов нет. Соседи пока делают вид, что мирные."
    lines = ["⚔️ <b>Входящие рейды</b>", ""]
    for item in items:
        lines.append(f"#{item['id']} — <b>{h(item['attacker'])}</b> · сила {item['attacker_power']}")
    return "\n".join(lines)


def render_officials(items: list[dict[str, Any]]) -> str:
    if not items:
        return "🧩 <b>Должности</b>\n\nПока никто не у власти. Подозрительно здоровая атмосфера."
    lines = ["🧩 <b>Должности района</b>", ""]
    for item in items:
        lines.append(f"• <b>{h(item['name'])}</b> — {h(item['title'])} · влияние {item['influence']}")
    return "\n".join(lines)


def render_weekly_summary(payload: dict[str, Any]) -> str:
    city = payload["city"]
    lines = [
        f"📆 <b>Итоги недели: {h(city['name'])}</b>",
        "",
        f"🏙 {h(city.get('rank', 'Подъезд'))} · ур. <b>{city['level']}</b> · казна <b>{city['treasury']}</b> · жители <b>{city['population']}</b>",
        f"⚙️ Движений за неделю: <b>{payload['actions']}</b>",
        f"⚔️ Рейдовых событий: <b>{payload['raids_won']}</b>",
    ]
    if payload.get("richest"):
        richest = payload["richest"]
        lines.append(f"💰 Богач недели: <b>{h(richest['name'])}</b> · {richest['coins']} монет")
    if payload.get("suspect"):
        suspect = payload["suspect"]
        lines.append(f"🕵️ Подозреваемый недели: <b>{h(suspect['name'])}</b> · судимости {suspect['convictions']}")
    if payload.get("top"):
        lines.append("\n🏆 Топ недели:")
        for index, item in enumerate(payload["top"][:5], start=1):
            lines.append(f"{index}. <b>{h(item['name'])}</b> — {h(item['title'])} · влияние {item['influence']}")
    if payload.get("trophies"):
        lines.append("\n🏆 Трофеи: " + ", ".join(h(item) for item in payload["trophies"][:5]))
    return "\n".join(lines)




def render_more_menu() -> str:
    return "⚙️ <b>Ещё</b>\n\nПостройки, суды, должности, сезон и логи. Всё, чем район обычно ломает себе жизнь."


def render_move_menu() -> str:
    return "🎲 <b>Движ</b>\n\nРабота, награда, квесты, события и драма."


def render_war_menu() -> str:
    return "⚔️ <b>Война и связи</b>\n\nРейды, союзы и ссылка, чтобы притащить Чатоград в другие чаты."


def render_alliances(items: list[dict[str, Any]], city_code: str) -> str:
    lines = ["🤝 <b>Союзы города</b>", "", f"Код вашего города: <code>{h(city_code)}</code>"]
    if not items:
        lines.append("\nСоюзов пока нет. Район одинок, но держится красиво.")
        lines.append("\nСоздать союз: <code>/ally CXXXXXXX</code>")
        return "\n".join(lines)
    lines.append("")
    for item in items:
        lines.append(f"• <b>{h(item['name'])}</b> · {h(item['rank'])} · ур. {item['level']} · код <code>{h(item['invite_code'])}</code>")
    lines.append("\nСоздать новый союз: <code>/ally CXXXXXXX</code>")
    return "\n".join(lines)


def render_admin_stats(payload: dict[str, Any]) -> str:
    top_action = payload.get("top_action") or {}
    top_city = payload.get("top_city") or {}
    lines = [
        "🛠 <b>Админ-статистика Чатограда</b>",
        "",
        f"Городов: <b>{payload['cities_total']}</b>",
        f"Игроков: <b>{payload['players_total']}</b>",
        f"Жителей в городах: <b>{payload['memberships_total']}</b>",
        f"Активных игроков за 24ч: <b>{payload['active_players_day']}</b>",
        f"Действий за 24ч: <b>{payload['actions_day']}</b>",
        f"Новых городов за 24ч: <b>{payload['new_cities_day']}</b>",
        f"Реферальных городов: <b>{payload['referrals_total']}</b>",
        f"Союзов: <b>{payload['alliances_total']}</b>",
        f"Рейдов: активных <b>{payload['raids_active']}</b> · завершённых <b>{payload['raids_finished']}</b>",
    ]
    if top_action:
        lines.append(f"Самое частое действие за 24ч: <b>{h(top_action.get('action'))}</b> · {top_action.get('count')}")
    if top_city:
        lines.append(f"Топ-город: <b>{h(top_city.get('name'))}</b> · ур. {top_city.get('level')} · жители {top_city.get('population')}")
    return "\n".join(lines)


def render_daily(payload: dict[str, Any], text: str | None = None) -> str:
    base = text or "🎁 Ежедневная награда"
    status = "забрана" if payload.get("collected") else "доступна"
    return (
        f"🎁 <b>Ежедневная награда</b> — {h(status)}\n\n"
        f"{h(base)}\n\n"
        f"Серия: <b>{payload.get('streak', 0)}</b> дней\n"
        f"Следующая серия: <b>{payload.get('next_streak', 1)}</b>\n"
        f"Награда: <b>{payload.get('reward', 0)}</b> монет"
    )


def render_shop(payload: dict[str, Any], city_treasury: int) -> str:
    lines = ["🛒 <b>Магазин города</b>", "", f"Казна: <b>{city_treasury}</b>", ""]
    for item in payload["items"]:
        lines.append(f"{h(item['name'])} · куплено <b>{item['count']}</b> · цена <b>{item['cost']}</b>")
    return "\n".join(lines)


def shop_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for key, spec in SHOP_ITEMS.items():
        rows.append([InlineKeyboardButton(text=str(spec["name"]), callback_data=f"cc:shop_buy:{key}")])
    rows.append([InlineKeyboardButton(text="🏙 Панель города", callback_data="cc:city")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def render_season(payload: dict[str, Any]) -> str:
    return (
        f"📆 <b>Сезон {payload['number']}</b>\n\n"
        f"Статус города: <b>{h(payload['rank'])}</b>\n"
        f"Прошло дней: <b>{payload['days_passed']}</b>/<b>{payload['duration_days']}</b>\n"
        f"До конца: <b>{payload['days_left']}</b> дней"
    )


def season_keyboard(expired: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if expired:
        rows.append([InlineKeyboardButton(text="🏅 Закрыть сезон", callback_data="cc:season_roll")])
    rows.append([InlineKeyboardButton(text="🏙 Панель города", callback_data="cc:city")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def delete_user_command_message(message: Message) -> None:
    if not is_group(message):
        return
    text = message.text or ""
    if not text.startswith("/"):
        return
    try:
        await message.delete()
    except Exception:
        logger.debug("Could not delete user command message", exc_info=True)


async def send_game_message(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> Message:
    if not is_group(message):
        return await message.bot.send_message(message.chat.id, text, reply_markup=reply_markup)

    await delete_user_command_message(message)

    old_message_id: int | None = None
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        old_message_id = city.last_bot_message_id

    candidate_message_id: int | None = None

    # Callback buttons come from the bot's own message. Edit that exact message,
    # so votes/events/panels do not jump around the chat.
    if is_bot_owned_message(message):
        candidate_message_id = message.message_id

    # Commands and scheduled events should update the last managed panel if it exists.
    if not candidate_message_id and old_message_id and old_message_id != message.message_id:
        candidate_message_id = old_message_id

    if candidate_message_id:
        edited = await try_edit_game_message(message.bot, message.chat.id, candidate_message_id, text, reply_markup)
        if edited:
            with session_scope() as db:
                city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
                city.last_bot_message_id = candidate_message_id
            return message

    # Fallback: if Telegram refuses editing, send a fresh managed message.
    # Do not hard-delete the previous message here: failed edits often happen because
    # the message is already gone/too old, and forced deletes create extra API noise.
    sent = await message.bot.send_message(message.chat.id, text, reply_markup=reply_markup)
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        city.last_bot_message_id = sent.message_id
    return sent


async def send_managed_bot_message(bot: Bot, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    old_message_id: int | None = None
    with session_scope() as db:
        city = db.scalar(select(City).where(City.chat_id == chat_id))
        if city:
            old_message_id = city.last_bot_message_id
    if old_message_id:
        edited = await try_edit_game_message(bot, chat_id, old_message_id, text, reply_markup)
        if edited:
            return
    sent = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    with session_scope() as db:
        city = db.scalar(select(City).where(City.chat_id == chat_id))
        if city:
            city.last_bot_message_id = sent.message_id


async def send_city_panel(message: Message, created: bool = False, user: Any | None = None) -> None:
    user = user or message.from_user
    if is_group(message) and is_human_user(user):
        await ensure_city_member_from_user(message, user)
    with session_scope() as db:
        city, was_created = get_or_create_city(db, message.chat.id, message.chat.title)
        payload = city_payload(db, city)
        is_member, is_founder = is_member_payload(db, city, user)
    await send_game_message(message, 
        render_city_status(payload, created or was_created),
        reply_markup=city_panel_keyboard(is_member=is_member, is_founder=is_founder),
    )

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, bot: Bot) -> None:
    args = (command.args or "").strip()
    referral_code = args if args and not args.startswith("city_") else None
    bot_username = await get_bot_username(bot)

    if is_group(message):
        user = message.from_user
        owner = await is_user_chat_owner(message.bot, message.chat.id, user.id if user else None)
        founder_line = ""
        referral_line = ""
        with session_scope() as db:
            city, created = get_or_create_city(db, message.chat.id, message.chat.title)
            if args.startswith("city_") or args.startswith("C"):
                _ok_ref, ref_text = register_city_referral(db, city, args)
                if ref_text:
                    referral_line = "\n" + ref_text
            is_founder = False
            if is_human_user(user):
                player, _, _ = get_or_create_player(db, user.id, user.username, user.first_name)
                membership, _ = join_city(db, city, player, is_chat_owner=owner)
                is_founder = bool(getattr(membership, "special_title", None) == "Основатель района")
                if is_founder:
                    founder_line = f"\n👑 Основатель района: <b>{h(display_player(player))}</b>"
            payload = city_payload(db, city)
        status = "основан" if created else "уже существует"
        await send_game_message(message, 
            f"🏙 <b>{BRAND} активирован.</b>\n\n"
            f"Город <b>{h(payload['name'])}</b> {status}.\n"
            f"Уровень: <b>{payload['level']}</b> · Казна: <b>{payload['treasury']}</b> · Жители: <b>{payload['population']}</b>{founder_line}{referral_line}\n"
            f"Код рейдов: <code>{h(payload['invite_code'])}</code>",
            reply_markup=city_panel_keyboard(is_member=True, is_founder=is_founder),
        )
        return

    user = message.from_user
    if not user:
        return

    with session_scope() as db:
        player, created, reward = get_or_create_player(db, user.id, user.username, user.first_name, referral_code)
    intro = "создан" if created else "найден"
    reward_line = f"\n\n{h(reward)}" if reward else ""
    ref_link = f"https://t.me/{bot_username}?start={player.ref_code}" if bot_username else player.ref_code

    await send_game_message(message, 
        f"🏙 <b>{BRAND}</b>\n\n"
        f"Профиль {intro}: <b>{h(display_player(player))}</b>\n"
        f"Роль: <b>{h(player.role)}</b>\n"
        f"Монеты: <b>{player.coins}</b>\n"
        f"Реф-код: <code>{h(player.ref_code)}</code>{reward_line}\n\n"
        f"Реферальная ссылка:\n<code>{h(ref_link)}</code>",
        reply_markup=private_start_keyboard(bot_username),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    if is_group(message):
        await send_game_message(message, 
            f"🧭 <b>{BRAND}</b>\n\n"
            "Панель города открыта.",
            reply_markup=city_panel_keyboard(),
        )
    else:
        await send_game_message(message, 
            f"🏙 <b>{BRAND}</b>",
            reply_markup=private_start_keyboard(await get_bot_username(message.bot)),
        )


@router.message(Command("menu"))
@router.message(Command("panel"))
async def cmd_menu(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Панель доступна в группе.")
        return
    await send_city_panel(message, user=message.from_user)


@router.message(Command("city"))
async def cmd_city(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Город доступен в группе.")
        return
    await send_city_panel(message, user=message.from_user)


@router.message(Command("join"))
async def cmd_join(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Вступление доступно в группе.")
        return
    await perform_join(message, message.from_user)


@router.message(Command("founder"))
async def cmd_founder(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Титул доступен в группе.")
        return
    await perform_founder(message, message.from_user)


@router.message(Command("work"))
async def cmd_work(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Работа доступна в группе.")
        return
    await perform_work(message, message.from_user)


@router.message(Command("event"))
async def cmd_event(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "События доступны в группе.")
        return
    await perform_event(message)


@router.message(Command("drama"))
async def cmd_drama(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Драма доступна в группе.")
        return
    await perform_drama(message)


@router.message(Command("election"))
async def cmd_election(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Выборы доступны в группе.")
        return
    await perform_election(message)


@router.message(Command("quest"))
async def cmd_quest(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Квест доступен в группе.")
        return
    await perform_quest(message, message.from_user, help_now=False)


@router.message(Command("gazeta", "newspaper"))
async def cmd_gazeta(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Газета доступна в группе.")
        return
    await perform_newspaper(message)


@router.message(Command("vote"))
async def cmd_vote(message: Message, command: CommandObject) -> None:
    if not is_group(message):
        await send_game_message(message, "Голосование доступно в группе.")
        return
    user = message.from_user
    if not user:
        return
    try:
        option = int((command.args or "").strip())
    except ValueError:
        await send_game_message(message, "Нужен вариант: <b>1</b>, <b>2</b> или <b>3</b>.")
        return
    await perform_vote(message, user, option)


@router.message(Command("resolve"))
async def cmd_resolve(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Завершение доступно в группе.")
        return
    await perform_resolve(message)


@router.message(Command("top"))
async def cmd_top(message: Message) -> None:
    if is_group(message):
        await perform_top(message)
        return
    await send_global_top(message)


@router.message(Command("globaltop"))
async def cmd_globaltop(message: Message) -> None:
    await send_global_top(message)


@router.message(Command("raid"))
async def cmd_raid(message: Message, command: CommandObject) -> None:
    if not is_group(message):
        await send_game_message(message, "Рейды доступны в группе.")
        return
    code = (command.args or "").strip().upper()
    if not code:
        await send_game_message(message, 
            "⚔️ <b>Рейд</b>\n\n"
            "Код города: <code>/raid CXXXXXXX</code>",
            reply_markup=back_keyboard(),
        )
        return
    await perform_raid_challenge(message, code)


@router.message(Command("ally"))
async def cmd_ally(message: Message, command: CommandObject) -> None:
    if not is_group(message):
        await send_game_message(message, "Союзы доступны в группе.")
        return
    code = (command.args or "").strip().upper()
    if not code:
        await perform_alliances(message)
        return
    await perform_create_alliance(message, code)


@router.message(Command("alliances"))
async def cmd_alliances(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Союзы доступны в группе.")
        return
    await perform_alliances(message)


@router.message(Command("admin_stats"))
async def cmd_admin_stats(message: Message) -> None:
    await perform_admin_stats(message)


@router.message(Command("raids"))
async def cmd_raids(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Рейды доступны в группе.")
        return
    await perform_raids(message)


@router.message(Command("weekly"))
async def cmd_weekly(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Итоги доступны в группе.")
        return
    await perform_weekly(message)


@router.message(Command("officials"))
async def cmd_officials(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Должности доступны в группе.")
        return
    await perform_officials(message)


@router.message(Command("appoint"))
async def cmd_appoint(message: Message, command: CommandObject) -> None:
    if not is_group(message):
        await send_game_message(message, "Должности доступны в группе.")
        return
    await perform_appoint(message, command.args or "")


@router.message(Command("logs"))
async def cmd_logs(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Логи доступны в группе.")
        return
    await perform_logs(message)


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Профиль доступен в группе.")
        return
    await perform_profile(message, message.from_user)


@router.message(Command("court"))
async def cmd_court(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Суд доступен в группе.")
        return
    await perform_court(message)


@router.message(Command("build"))
async def cmd_build(message: Message, command: CommandObject) -> None:
    if not is_group(message):
        await send_game_message(message, "Постройки доступны в группе.")
        return
    key = (command.args or "").strip().lower()
    if key:
        await perform_build(message, key)
    else:
        await perform_buildings(message)



@router.message(Command("daily"))
async def cmd_daily(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Награда доступна в группе.")
        return
    await perform_daily(message, message.from_user)


@router.message(Command("shop"))
async def cmd_shop(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Магазин доступен в группе.")
        return
    await perform_shop(message)


@router.message(Command("season"))
async def cmd_season(message: Message) -> None:
    if not is_group(message):
        await send_game_message(message, "Сезон доступен в группе.")
        return
    await perform_season(message)



async def perform_more(message: Message, user: Any | None = None) -> None:
    is_founder = False
    if user and is_human_user(user):
        with session_scope() as db:
            city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
            _is_member, is_founder = is_member_payload(db, city, user)
    await send_game_message(message, render_more_menu(), reply_markup=more_keyboard(is_founder=is_founder))


async def perform_daily(message: Message, user: Any | None) -> None:
    if not user:
        return
    owner = await is_user_chat_owner(message.bot, message.chat.id, user.id)
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        player, _, _ = get_or_create_player(db, user.id, user.username, user.first_name)
        join_city(db, city, player, is_chat_owner=owner)
        ok, text, payload = collect_daily_reward(db, city, player)
    await send_game_message(message, render_daily(payload, text), reply_markup=back_keyboard())


async def perform_shop(message: Message) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        payload = shop_payload(city)
        treasury = city.treasury
    await send_game_message(message, render_shop(payload, treasury), reply_markup=shop_keyboard())


async def perform_shop_buy(message: Message, key: str) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        ok, text, payload = buy_shop_item(db, city, key)
        treasury = city.treasury
    prefix = "✅" if ok else "⛔"
    await send_game_message(message, f"{prefix} {h(text)}\n\n" + render_shop(payload, treasury), reply_markup=shop_keyboard())


async def perform_season(message: Message) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        payload = season_payload(city)
    await send_game_message(message, render_season(payload), reply_markup=season_keyboard(expired=payload.get("expired", False)))


async def perform_season_roll(message: Message) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        ok, text, payload = maybe_roll_season(db, city)
    prefix = "🏅" if ok else "⏳"
    await send_game_message(message, f"{prefix} {h(text)}\n\n" + render_season(payload), reply_markup=season_keyboard(expired=payload.get("expired", False)))


async def perform_join(message: Message, user: Any | None) -> None:
    if not user:
        return
    owner = await is_user_chat_owner(message.bot, message.chat.id, user.id)
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        player, _, _ = get_or_create_player(db, user.id, user.username, user.first_name)
        membership, created = join_city(db, city, player, is_chat_owner=owner)
        payload = city_payload(db, city)

    title_line = "\n👑 Титул: <b>Основатель района</b>" if getattr(membership, "special_title", None) == "Основатель района" else ""
    if created:
        await send_game_message(message, 
            f"✅ <b>{h(display_player(player))}</b> вступил в <b>{h(payload['name'])}</b>.\n"
            f"Роль: <b>{h(player.role)}</b>\n"
            f"Влияние: <b>{membership.influence}</b>{title_line}\n"
            f"Казна города: <b>{payload['treasury']}</b>",
            reply_markup=back_keyboard(),
        )
    else:
        await send_game_message(message, 
            f"Ты уже житель <b>{h(payload['name'])}</b>.\n"
            f"Роль: <b>{h(player.role)}</b>\n"
            f"Влияние: <b>{membership.influence}</b>{title_line}",
            reply_markup=back_keyboard(),
        )


async def perform_founder(message: Message, user: Any | None) -> None:
    if not user:
        return
    owner = await is_user_chat_owner(message.bot, message.chat.id, user.id)
    if not owner:
        await send_game_message(message, 
            "👑 <b>Основатель района</b> доступен только владельцу чата.",
            reply_markup=back_keyboard(),
        )
        return

    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        player, _, _ = get_or_create_player(db, user.id, user.username, user.first_name)
        membership, _ = join_city(db, city, player, is_chat_owner=True)
        payload = city_payload(db, city)

    await send_game_message(message, 
        f"👑 <b>{h(display_player(player))}</b> — Основатель района.\n"
        f"Город: <b>{h(payload['name'])}</b>\n"
        f"Влияние: <b>{membership.influence}</b> · Казна: <b>{payload['treasury']}</b>",
        reply_markup=back_keyboard(),
    )


async def perform_work(message: Message, user: Any | None) -> None:
    if not user:
        return
    owner = await is_user_chat_owner(message.bot, message.chat.id, user.id)
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        player, _, _ = get_or_create_player(db, user.id, user.username, user.first_name)
        join_city(db, city, player, is_chat_owner=owner)
        result = work(db, city, player)
        payload = city_payload(db, city)

    if result.cooldown_left_minutes:
        await send_game_message(message, 
            f"⏳ {h(result.text)}\nОсталось примерно: <b>{result.cooldown_left_minutes} мин.</b>",
            reply_markup=back_keyboard(),
        )
        return

    await send_game_message(message, 
        f"💼 {h(result.text)}\n\n"
        f"Тебе: <b>+{result.coins}</b> монет, <b>+{result.xp}</b> опыта\n"
        f"Городу: <b>+{result.treasury}</b> в казну\n"
        f"Казна города: <b>{payload['treasury']}</b>\n"
        f"Уровень города: <b>{payload['level']}</b>",
        reply_markup=back_keyboard(),
    )


async def perform_event(message: Message) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        event = create_daily_event(db, city)
        if event is None:
            await send_game_message(message, 
                "Сегодня событие уже было. Город переваривает последствия.",
                reply_markup=back_keyboard(),
            )
            return
        payload = event_payload(event)
    if payload:
        await send_game_message(message, render_event(payload), reply_markup=event_keyboard())


async def perform_vote(message: Message, user: Any, option: int) -> None:
    owner = await is_user_chat_owner(message.bot, message.chat.id, user.id)
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        player, _, _ = get_or_create_player(db, user.id, user.username, user.first_name)
        join_city(db, city, player, is_chat_owner=owner)
        event, text = vote_event(db, city, player, option)
        payload = event_payload(event) if event else None

    if payload:
        await send_game_message(message, f"🗳 {h(text)}\n\n{render_event(payload)}", reply_markup=event_keyboard())
    else:
        await send_game_message(message, h(text), reply_markup=back_keyboard())


async def perform_resolve(message: Message) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        text = resolve_event(db, city)
        payload = city_payload(db, city)
    await send_game_message(message, 
        f"🏁 {h(text)}\n\nКазна: <b>{payload['treasury']}</b> · Уровень: <b>{payload['level']}</b>",
        reply_markup=back_keyboard(),
    )


async def perform_drama(message: Message) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        event = create_drama_event(db, city, force=True)
        payload = event_payload(event) if event else None
    if not payload:
        await send_game_message(message, 
            "🔥 Для драмы нужно хотя бы 2 жителя.",
            reply_markup=back_keyboard(),
        )
        return
    await send_game_message(message, "🔥 <b>Драма дня</b>\n\n" + render_event(payload), reply_markup=event_keyboard())


async def perform_election(message: Message) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        event = create_mayor_election(db, city)
        payload = event_payload(event) if event else None
    if not payload:
        await send_game_message(message, 
            "🗳 Выборы не стартовали: нужно 2+ жителя или завершение активного события.",
            reply_markup=back_keyboard(),
        )
        return
    await send_game_message(message, "🗳 <b>Выборы мэра</b>\n\n" + render_event(payload), reply_markup=event_keyboard())


async def perform_quest(message: Message, user: Any | None, help_now: bool = False) -> None:
    owner = await is_user_chat_owner(message.bot, message.chat.id, user.id) if help_now and user else False
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        text = None
        if help_now and user:
            player, _, _ = get_or_create_player(db, user.id, user.username, user.first_name)
            join_city(db, city, player, is_chat_owner=owner)
            payload, text = help_city_quest(db, city, player)
        else:
            payload = quest_payload(db, city)
    prefix = f"{h(text)}\n\n" if text else ""
    await send_game_message(message, prefix + render_quest(payload), reply_markup=quest_keyboard())


async def perform_newspaper(message: Message) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        payload = build_newspaper(db, city)
    await send_game_message(message, render_newspaper(payload), reply_markup=back_keyboard())


async def perform_top(message: Message) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        players = top_players(db, city, limit=10)
        city_name = city.name

    if not players:
        await send_game_message(message, "Топ пуст. Пока тут парковка без машин.", reply_markup=back_keyboard())
        return
    lines = [f"🏆 <b>Топ жителей: {h(city_name)}</b>"]
    for index, item in enumerate(players, start=1):
        lines.append(
            f"{index}. <b>{h(item['name'])}</b> — {h(item['title'])} · роль: {h(item['role'])} · влияние {item['influence']} · монеты {item['coins']}"
        )
    await send_game_message(message, "\n".join(lines), reply_markup=back_keyboard())


async def send_global_top(message: Message) -> None:
    with session_scope() as db:
        cities = top_cities(db, limit=10)
    if not cities:
        await send_game_message(message, "Городов пока нет.")
        return
    lines = [f"🌍 <b>{BRAND}: топ городов</b>", ""]
    for index, item in enumerate(cities, start=1):
        lines.append(
            f"{index}. <b>{h(item['name'])}</b> · {h(item['rank'])} · ур. {item['level']} · жители {item['population']} · "
            f"трофеи {item.get('trophies_count', 0)} · союзы {item.get('alliances_count', 0)} · привёл {item.get('referrals_count', 0)}"
        )
    await send_game_message(message, "\n".join(lines), reply_markup=back_keyboard() if is_group(message) else None)


async def perform_logs(message: Message) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        logs = recent_logs(db, city.id, limit=8)
    if not logs:
        await send_game_message(message, "Лог пуст. Подозрительно тихий город.", reply_markup=back_keyboard())
        return
    lines = ["📜 <b>Последние действия</b>"]
    lines.extend(f"• {h(item['text'])}" for item in logs)
    await send_game_message(message, "\n".join(lines), reply_markup=back_keyboard())


async def perform_profile(message: Message, user: Any | None) -> None:
    if not user:
        return
    owner = await is_user_chat_owner(message.bot, message.chat.id, user.id)
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        player, _, _ = get_or_create_player(db, user.id, user.username, user.first_name)
        join_city(db, city, player, is_chat_owner=owner)
        payload = player_profile(db, city, player)
    await send_game_message(message, render_profile(payload), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 Награда", callback_data="cc:daily")],[InlineKeyboardButton(text="🏙 Панель города", callback_data="cc:city")]]))


async def perform_buildings(message: Message) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        payload = building_payload(city)
        treasury = city.treasury
    await send_game_message(message, render_buildings(payload, treasury), reply_markup=buildings_keyboard())


async def perform_build(message: Message, key: str) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        ok, text, payload = build_city_building(db, city, key)
        treasury = city.treasury
    prefix = "✅" if ok else "⛔"
    await send_game_message(message, f"{prefix} {h(text)}\n\n" + render_buildings(payload, treasury), reply_markup=buildings_keyboard())


async def perform_court(message: Message) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        event = create_court_event(db, city, force=True)
        payload = event_payload(event) if event else None
    if not payload:
        await send_game_message(message, "⚖️ Для суда нужен хотя бы один житель.", reply_markup=back_keyboard())
        return
    await send_game_message(message, "⚖️ <b>Суд Чатограда</b>\n\n" + render_event(payload), reply_markup=event_keyboard())


async def perform_raid_challenge(message: Message, code: str) -> None:
    with session_scope() as db:
        attacker, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        war, text, defender, created = create_raid_challenge(db, attacker, code)
        attacker_payload = city_payload(db, attacker)
    if not war or not defender:
        await send_game_message(message, f"⚔️ {h(text)}", reply_markup=back_keyboard())
        return
    accept_text = "\n\nВторой город должен открыть /raids и принять вызов." if created else ""
    await send_game_message(message, 
        f"⚔️ <b>Рейд объявлен</b>\n\n{h(text)}{accept_text}\n\n"
        f"Сила вашего города: <b>{attacker_payload['power']}</b>",
        reply_markup=back_keyboard(),
    )


async def perform_raids(message: Message) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        items = active_incoming_raids(db, city)
    keyboard = raid_accept_keyboard(items[0]["id"]) if items else back_keyboard()
    await send_game_message(message, render_incoming_raids(items), reply_markup=keyboard)


async def perform_raid_accept(message: Message, war_id: int) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        war, text = resolve_raid_challenge(db, city, war_id)
        payload = city_payload(db, city)
    score_line = f"\nСчёт: <b>{war.attacker_score}</b> vs <b>{war.defender_score}</b>" if war else ""
    await send_game_message(message, 
        f"⚔️ <b>Рейд завершён</b>\n\n{h(text)}{score_line}\n\n"
        f"Казна: <b>{payload['treasury']}</b> · Уровень: <b>{payload['level']}</b>",
        reply_markup=back_keyboard(),
    )


async def perform_alliances(message: Message) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        items = city_alliances(db, city)
        code = city.invite_code
    await send_game_message(message, render_alliances(items, code), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🤝 Создать союз", callback_data="cc:ally_help")], [InlineKeyboardButton(text="⚔️ Назад", callback_data="cc:war")]]))


async def perform_create_alliance(message: Message, code: str) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        ok, text, _target = create_city_alliance(db, city, code)
        items = city_alliances(db, city)
        city_code = city.invite_code
    prefix = "✅" if ok else "⛔"
    await send_game_message(message, f"{prefix} {h(text)}\n\n" + render_alliances(items, city_code), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚔️ Назад", callback_data="cc:war")], [InlineKeyboardButton(text="🏙 Панель города", callback_data="cc:city")]]))


async def perform_admin_stats(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None
    settings = get_settings()
    if user_id not in settings.admin_ids:
        await send_game_message(message, "Админка закрыта.")
        return
    with session_scope() as db:
        payload = admin_stats(db)
    await send_game_message(message, render_admin_stats(payload))


async def perform_officials(message: Message) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        items = city_officials(db, city)
    await send_game_message(message, render_officials(items), reply_markup=back_keyboard())


async def perform_weekly(message: Message) -> None:
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        payload = weekly_summary(db, city)
    await send_game_message(message, render_weekly_summary(payload), reply_markup=back_keyboard())


async def perform_appoint(message: Message, raw_args: str) -> None:
    owner = await is_user_chat_owner(message.bot, message.chat.id, message.from_user.id if message.from_user else None)
    if not owner:
        await send_game_message(message, "🧩 Назначать должности может только владелец чата.", reply_markup=back_keyboard())
        return
    parts = raw_args.split()
    if len(parts) < 2:
        available = ", ".join(APPOINTABLE_TITLES.keys())
        await send_game_message(message, f"🧩 Формат: <code>/appoint @user должность</code>\nДоступно: {h(available)}", reply_markup=back_keyboard())
        return
    username = parts[0]
    title_key = " ".join(parts[1:])
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        target = find_city_player_by_username(db, city, username)
        if not target:
            await send_game_message(message, "Не нашёл такого жителя в городе.", reply_markup=back_keyboard())
            return
        ok, text = appoint_city_official(db, city, target, title_key)
    prefix = "✅" if ok else "⛔"
    await send_game_message(message, f"{prefix} {h(text)}", reply_markup=back_keyboard())


@router.callback_query(F.data == "cc:city")
async def cb_city(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Эта кнопка работает в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await send_city_panel(callback.message, user=callback.from_user)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:join")
async def cb_join(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Вступать надо в группе.", show_alert=True)
        return
    await callback.answer("Вступаем в город…")
    await delete_callback_message(callback)
    await perform_join(callback.message, callback.from_user)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:profile")
async def cb_profile(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Профиль работает в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await perform_profile(callback.message, callback.from_user)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:buildings")
async def cb_buildings(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Постройки работают в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await perform_buildings(callback.message)  # type: ignore[arg-type]


@router.callback_query(F.data.startswith("cc:build:"))
async def cb_build(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Строить можно только в группе.", show_alert=True)
        return
    key = (callback.data or "").split(":")[-1]
    await callback.answer("Строим…")
    await delete_callback_message(callback)
    await perform_build(callback.message, key)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:court")
async def cb_court(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Суд работает в группе.", show_alert=True)
        return
    await callback.answer("Открываем суд…")
    await delete_callback_message(callback)
    await perform_court(callback.message)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:founder")
async def cb_founder(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Только в группе.", show_alert=True)
        return
    owner = await is_user_chat_owner(callback.bot, callback.message.chat.id, callback.from_user.id)  # type: ignore[union-attr]
    if not owner:
        await callback.answer("Только владелец чата может забрать этот титул.", show_alert=True)
        return
    await callback.answer("Корона оформляется…")
    await delete_callback_message(callback)
    await perform_founder(callback.message, callback.from_user)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:invite_bot")
async def cb_invite_bot(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    bot_username = await get_bot_username(callback.bot)
    if not bot_username:
        await callback.answer("Не смог получить username бота.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    with session_scope() as db:
        city, _ = get_or_create_city(db, callback.message.chat.id, callback.message.chat.title)
        code = city.invite_code
    await send_game_message(callback.message, 
        "📣 <b>Позвать Чатоград</b>\n\n"
        "Если по ссылке добавят бота в другой чат, ваш город получит награду.\n\n"
        f"https://t.me/{h(bot_username)}?startgroup=city_{h(code)}",
        reply_markup=back_keyboard(),
    )


@router.callback_query(F.data == "cc:work")
async def cb_work(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Работать надо в городе-группе.", show_alert=True)
        return
    await callback.answer("Работаем…")
    await delete_callback_message(callback)
    await perform_work(callback.message, callback.from_user)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:quest")
async def cb_quest(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Квест живёт в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await perform_quest(callback.message, callback.from_user, help_now=False)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:quest_help")
async def cb_quest_help(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Помогать квесту можно только в группе.", show_alert=True)
        return
    await callback.answer("Помогаем городу…")
    await delete_callback_message(callback)
    await perform_quest(callback.message, callback.from_user, help_now=True)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:newspaper")
async def cb_newspaper(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Газета работает в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await perform_newspaper(callback.message)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:drama")
async def cb_drama(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Драма работает в группе.", show_alert=True)
        return
    await callback.answer("Запускаем драму…")
    await delete_callback_message(callback)
    await perform_drama(callback.message)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:election")
async def cb_election(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Выборы работают в группе.", show_alert=True)
        return
    await callback.answer("Запускаем выборы…")
    await delete_callback_message(callback)
    await perform_election(callback.message)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:event")
async def cb_event(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("События живут в группе.", show_alert=True)
        return
    await callback.answer("Смотрим событие…")
    await delete_callback_message(callback)
    await perform_event(callback.message)  # type: ignore[arg-type]


@router.callback_query(F.data.startswith("cc:vote:"))
async def cb_vote(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Голосовать можно только в группе.", show_alert=True)
        return
    option_text = (callback.data or "").split(":")[-1]
    try:
        option = int(option_text)
    except ValueError:
        await callback.answer("Кривая кнопка. Бывает, Telegram тоже человек.", show_alert=True)
        return
    await callback.answer("Голос принят")
    await delete_callback_message(callback)
    await perform_vote(callback.message, callback.from_user, option)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:resolve")
async def cb_resolve(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Завершать событие можно только в группе.", show_alert=True)
        return
    await callback.answer("Завершаем…")
    await delete_callback_message(callback)
    await perform_resolve(callback.message)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:top")
async def cb_top(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Топ жителей работает в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await perform_top(callback.message)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:logs")
async def cb_logs(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Логи города работают в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await perform_logs(callback.message)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:raid_help")
async def cb_raid_help(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Рейды запускаются из группы.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    message = callback.message
    assert isinstance(message, Message)
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        payload = city_payload(db, city)
    await send_game_message(message, 
        "⚔️ <b>Рейд</b>\n\n"
        f"Код вашего города: <code>{h(payload['invite_code'])}</code>\n"
        "Атака: <code>/raid CXXXXXXX</code>\n"
        "Входящие: <code>/raids</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚔️ Входящие рейды", callback_data="cc:raids")], [InlineKeyboardButton(text="🏙 Панель города", callback_data="cc:city")]]),
    )


@router.callback_query(F.data == "cc:raids")
async def cb_raids(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Рейды доступны в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await perform_raids(callback.message)  # type: ignore[arg-type]


@router.callback_query(F.data.startswith("cc:raid_accept:"))
async def cb_raid_accept(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Принимать рейд надо в группе.", show_alert=True)
        return
    try:
        war_id = int((callback.data or "").split(":")[-1])
    except ValueError:
        await callback.answer("Кривой рейд.", show_alert=True)
        return
    await callback.answer("Рейд принимается…")
    await delete_callback_message(callback)
    await perform_raid_accept(callback.message, war_id)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:officials")
async def cb_officials(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Должности работают в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await perform_officials(callback.message)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:weekly")
async def cb_weekly(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Итоги работают в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await perform_weekly(callback.message)  # type: ignore[arg-type]



@router.callback_query(F.data == "cc:move")
async def cb_move(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Это работает в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await send_game_message(callback.message, render_move_menu(), reply_markup=move_keyboard())  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:war")
async def cb_war(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Это работает в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await send_game_message(callback.message, render_war_menu(), reply_markup=war_keyboard())  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:alliances")
async def cb_alliances(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Союзы работают в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await perform_alliances(callback.message)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:ally_help")
async def cb_ally_help(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Союзы работают в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await send_game_message(callback.message, "🤝 <b>Создать союз</b>\n\nОтправь команду: <code>/ally CXXXXXXX</code>", reply_markup=war_keyboard())  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:more")
async def cb_more(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Это работает в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await perform_more(callback.message, callback.from_user)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:daily")
async def cb_daily(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Награда работает в группе.", show_alert=True)
        return
    await callback.answer("Забираем…")
    await delete_callback_message(callback)
    await perform_daily(callback.message, callback.from_user)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:shop")
async def cb_shop(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Магазин работает в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await perform_shop(callback.message)  # type: ignore[arg-type]


@router.callback_query(F.data.startswith("cc:shop_buy:"))
async def cb_shop_buy(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Покупки работают в группе.", show_alert=True)
        return
    key = (callback.data or "").split(":")[-1]
    await callback.answer("Покупаем…")
    await delete_callback_message(callback)
    await perform_shop_buy(callback.message, key)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:season")
async def cb_season(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Сезон работает в группе.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await perform_season(callback.message)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:season_roll")
async def cb_season_roll(callback: CallbackQuery) -> None:
    if not is_group_callback(callback):
        await callback.answer("Сезон работает в группе.", show_alert=True)
        return
    await callback.answer("Закрываем сезон…")
    await delete_callback_message(callback)
    await perform_season_roll(callback.message)  # type: ignore[arg-type]


@router.callback_query(F.data == "cc:global_top")
async def cb_global_top(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    await callback.answer()
    await delete_callback_message(callback)
    await send_global_top(callback.message)


@router.message(F.new_chat_members)
async def on_new_members(message: Message) -> None:
    if not is_group(message):
        return
    bot_id = (await message.bot.get_me()).id
    bot_was_added = any(member.id == bot_id for member in message.new_chat_members)
    if bot_was_added:
        owner = await is_user_chat_owner(message.bot, message.chat.id, message.from_user.id if message.from_user else None)
        with session_scope() as db:
            city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
            if is_human_user(message.from_user):
                player, _, _ = get_or_create_player(db, message.from_user.id, message.from_user.username, message.from_user.first_name)
                join_city(db, city, player, is_chat_owner=owner)
            payload = city_payload(db, city)
        await send_game_message(message, 
            f"🏙 <b>{BRAND} прибыл.</b>\n\n"
            f"Город создан: <b>{h(payload['name'])}</b>",
            reply_markup=back_keyboard(),
        )
        return

    new_people = [member for member in message.new_chat_members if not member.is_bot]
    if not new_people:
        return
    with session_scope() as db:
        city, _ = get_or_create_city(db, message.chat.id, message.chat.title)
        for member in new_people:
            player, _, _ = get_or_create_player(db, member.id, member.username, member.first_name)
            join_city(db, city, player, is_chat_owner=False)


@router.message()
async def auto_register_human_message(message: Message) -> None:
    if not is_group(message) or not is_human_user(message.from_user):
        return
    await ensure_city_member_from_user(message, message.from_user)


async def auto_event_loop(bot: Bot) -> None:
    settings = get_settings()
    interval = max(5, settings.auto_event_interval_minutes) * 60
    await asyncio.sleep(20)
    while True:
        try:
            events_to_send: list[tuple[int, dict[str, Any]]] = []
            with session_scope() as db:
                cities = db.scalars(select(City).order_by(City.updated_at.desc()).limit(200)).all()
                for city in cities:
                    if city_population(db, city.id) < settings.auto_event_min_population:
                        continue
                    event = create_new_event_if_due(db, city)
                    payload = event_payload(event) if event else None
                    if payload:
                        events_to_send.append((city.chat_id, payload))
            for chat_id, payload in events_to_send:
                try:
                    await send_managed_bot_message(
                        bot,
                        chat_id,
                        "📣 <b>Автособытие дня</b>\n\n" + render_event(payload),
                        reply_markup=event_keyboard(),
                    )
                except Exception:
                    logger.exception("Cannot send auto event to chat %s", chat_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Auto event loop failed")
        await asyncio.sleep(interval)


async def run_bot_polling() -> None:
    settings = get_settings()
    if not settings.has_bot_token:
        logger.warning("BOT_TOKEN is empty or placeholder. Telegram polling is disabled.")
        return

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    auto_task: asyncio.Task | None = None

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        if settings.enable_auto_events:
            auto_task = asyncio.create_task(auto_event_loop(bot))
            logger.info("Auto event loop started")
        logger.info("Starting Telegram bot polling")
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("Telegram bot polling cancelled")
        raise
    finally:
        if auto_task:
            auto_task.cancel()
            try:
                await auto_task
            except asyncio.CancelledError:
                logger.info("Auto event loop stopped")
        await bot.session.close()
