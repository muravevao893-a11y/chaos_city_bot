from __future__ import annotations

import hashlib
import hmac
import json
import random
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ActionLog, AllianceStatus, City, CityAlliance, CityEvent, CityReferral, CityStatus, Duel, DuelStatus, Membership, Player, Purchase, PurchaseStatus, War, utcnow

CITY_PREFIXES = [
    "Неоновый", "Шумный", "Подпольный", "Кибер", "Бешеный", "Сонный", "Золотой", "Пиксельный",
    "Легендарный", "Мемный", "Бархатный", "Грозный", "Косой", "Турбо", "Лютый", "Дикий",
]
CITY_NOUNS = [
    "Подъезд", "Район", "Бульвар", "Сити", "Форт", "Улей", "Квартал", "Городок",
    "Союз", "Клан", "Округ", "Штаб", "Мегаполис", "Двор", "Порт", "Блок",
]
FOUNDER_TITLE = "Основатель района"
JAIL_TITLE = "В подвале"

TROPHY_POOL = [
    "🏆 Золотая лавочка власти",
    "🚩 Флаг соседнего района",
    "🧱 Кирпич авторитета",
    "🥇 Кубок подъезда",
    "🕳 Ключ от подвала",
    "👑 Пыльная корона рейда",
    "⚔️ Табличка «мы тут главные»",
    "🥙 Священная шаурма победителя",
]

APPOINTABLE_TITLES = {
    "мэр": "👑 Мэр",
    "казначей": "💰 Казначей",
    "судья": "⚖️ Судья",
    "журналист": "📰 Журналист",
    "участковый": "🚔 Начальник участка",
    "воевода": "⚔️ Воевода",
    "архитектор": "🏗 Архитектор",
}

BUILDINGS: dict[str, dict[str, Any]] = {
    "shawarma": {
        "name": "🥙 Шаурмечная",
        "cost": 80,
        "text": "район теперь пахнет бизнесом и подозрительным чесночным соусом",
        "treasury_bonus": 12,
        "xp_bonus": 16,
    },
    "bank": {
        "name": "🏦 Банк",
        "cost": 140,
        "text": "казна стала выглядеть солиднее, хотя охранник всё ещё один",
        "treasury_bonus": 18,
        "xp_bonus": 22,
    },
    "police": {
        "name": "🚔 Участок",
        "cost": 120,
        "text": "жулики стали красть тише и с уважением",
        "treasury_bonus": 8,
        "xp_bonus": 20,
    },
    "newspaper": {
        "name": "📰 Газета",
        "cost": 100,
        "text": "теперь любой скандал можно назвать журналистикой",
        "treasury_bonus": 10,
        "xp_bonus": 24,
    },
    "arena": {
        "name": "⚔️ Арена",
        "cost": 170,
        "text": "жители получили место, где спорить официально",
        "treasury_bonus": 15,
        "xp_bonus": 30,
    },
    "cityhall": {
        "name": "🏛 Мэрия",
        "cost": 220,
        "text": "город получил здание для важных решений и красивых обещаний",
        "treasury_bonus": 25,
        "xp_bonus": 40,
    },
}

SEASON_DAYS = 14

ACTIVITY_MODES: dict[str, dict[str, Any]] = {
    "quiet": {"name": "🔕 Тихо", "hours": 30, "text": "редкие автособытия, минимум шума"},
    "normal": {"name": "⚖️ Нормально", "hours": 18, "text": "баланс движа и спокойствия"},
    "chaos": {"name": "🔥 Хаос", "hours": 8, "text": "частый движ для активных чатов"},
}

ACHIEVEMENTS: dict[str, dict[str, str]] = {
    "first_steps": {"name": "🏙 Первый житель", "text": "вступил в город"},
    "founder": {"name": "👑 Основатель", "text": "забрал титул владельца района"},
    "worker": {"name": "💼 Работяга", "text": "накопил первый рабочий опыт"},
    "rich_100": {"name": "💰 Первый капитал", "text": "накопил 100 монет"},
    "rep_20": {"name": "⭐ Уважаемый мутный тип", "text": "добрался до 20 репутации"},
    "convict": {"name": "⚖️ Судимый районный", "text": "получил первую судимость"},
    "faction": {"name": "🧱 Человек фракции", "text": "выбрал сторону в районе"},
    "items": {"name": "🎒 Барахольщик", "text": "завёл первый предмет"},
    "escape": {"name": "🕳 Беглец", "text": "выбрался из подвала"},
    "thief": {"name": "🕶 Руки у казны", "text": "попытался ограбить казну"},
    "rebel": {"name": "🔥 Организатор бунта", "text": "поднял район на бунт"},
    "duelist": {"name": "⚔️ Дуэлянт", "text": "участвовал в дуэли"},
    "mission": {"name": "🎯 Выполнил миссию", "text": "закрыл личную секретную задачу"},
    "secret_role": {"name": "🕵️ Тайная роль", "text": "получил скрытую роль района"},
}


BLACK_MARKET_ITEMS: dict[str, dict[str, Any]] = {
    "fake_rep": {
        "name": "🪪 Фальшивая репутация",
        "cost": 35,
        "text": "репутация стала выше, но район подозревает подвох",
    },
    "judge_bribe": {
        "name": "⚖️ Конверт судье",
        "cost": 55,
        "text": "одна судимость растворилась в бюрократии",
    },
    "hide_coins": {
        "name": "🕳 Спрятать монеты",
        "cost": 45,
        "text": "монеты спрятаны так хорошо, что часть нашла казна",
    },
    "rumor_bomb": {
        "name": "🗣 Запустить слух",
        "cost": 25,
        "text": "район получил новый слух и повод спорить",
    },
}

FACTIONS: dict[str, dict[str, Any]] = {
    "workers": {"name": "🧱 Работяги", "bonus": "больше дохода за работу и строительство"},
    "mafia": {"name": "🕶 Мафия", "bonus": "лучше кражи и мутные дуэли"},
    "bankers": {"name": "🏦 Банкиры", "bonus": "больше монет и защита казны"},
    "press": {"name": "📰 Пресса", "bonus": "сильнее слухи и репутация за движ"},
    "law": {"name": "⚖️ Законники", "bonus": "лучше суды и меньше штрафов"},
    "rebels": {"name": "🔥 Бунтари", "bonus": "сильнее бунты и побеги"},
}

ITEMS: dict[str, dict[str, Any]] = {
    "lockpick": {"name": "🔑 Ключ от подвала", "text": "даёт шанс выбраться из подвала"},
    "immunity": {"name": "🛡 Иммунитет суда", "text": "смягчает следующий штраф/подвал"},
    "compromat": {"name": "📜 Компромат", "text": "бьёт по репутации случайного соперника"},
    "smoke": {"name": "💨 Дымовая шашка", "text": "помогает при краже казны"},
    "fake_crown": {"name": "👑 Фальшивая корона", "text": "даёт влияние и смешной статус"},
}


SECRET_ROLES: dict[str, dict[str, str]] = {
    "thief": {"name": "🕶 Подпольный вор", "text": "лучше чувствует мутные сделки и кражи"},
    "informant": {"name": "📰 Информатор", "text": "любит слухи и газеты"},
    "mayor_agent": {"name": "👑 Агент мэрии", "text": "получает уважение при политическом движе"},
    "double_agent": {"name": "🎭 Двойной агент", "text": "в рейдах всегда выглядит подозрительно полезным"},
    "banker_shadow": {"name": "🏦 Теневой банкир", "text": "сильнее играет вокруг казны"},
    "provocateur": {"name": "🔥 Провокатор", "text": "бунты и драмы липнут сами"},
}

MISSIONS: dict[str, dict[str, Any]] = {
    "work_once": {"name": "💼 Отметиться на работе", "text": "поработай 1 раз", "action": "work", "need": 1, "coins": 18, "rep": 2},
    "help_quest": {"name": "🎯 Помочь району", "text": "помоги общему квесту", "action": "quest", "need": 1, "coins": 20, "rep": 2},
    "daily": {"name": "🎁 Забрать пайку", "text": "забери ежедневную награду", "action": "daily", "need": 1, "coins": 16, "rep": 1},
    "rumor": {"name": "🗣 Подогреть слухи", "text": "запусти слух района", "action": "rumor", "need": 1, "coins": 22, "rep": 2},
    "black_market": {"name": "🕶 Мутная покупка", "text": "купи что-нибудь на чёрном рынке", "action": "black_market", "need": 1, "coins": 25, "rep": 1},
    "duel": {"name": "⚔️ Проверка характера", "text": "создай или заверши дуэль", "action": "duel_created", "need": 1, "coins": 25, "rep": 3},
}

STARS_PRODUCTS: dict[str, dict[str, Any]] = {
    "ai_newspaper": {
        "name": "🗞 AI-газета",
        "stars": 10,
        "text": "один премиум-выпуск газеты с AI-ведущим",
        "kind": "city",
    },
    "rename_city": {
        "name": "🏷 Переименование города",
        "stars": 15,
        "text": "токен на косметическую смену названия города",
        "kind": "city",
    },
    "premium_event": {
        "name": "🎭 Большое событие",
        "stars": 35,
        "text": "запуск красивого события для всего чата без pay-to-win",
        "kind": "city",
    },
    "city_style": {
        "name": "🌆 Стиль города",
        "stars": 45,
        "text": "косметический стиль города для статуса и понтов",
        "kind": "city",
    },
    "premium_title": {
        "name": "👑 Премиум-титул",
        "stars": 25,
        "text": "косметический титул в профиле и топе",
        "kind": "player",
    },
    "season_bundle": {
        "name": "🏆 Сезонный набор",
        "stars": 99,
        "text": "трофей, праздник и косметика сезона для города",
        "kind": "city",
    },
}

TITLE_MARKET: dict[str, dict[str, Any]] = {
    "batya": {"name": "Батя района", "cost": 120, "rep": 2},
    "sus": {"name": "Официально подозрительный", "cost": 90, "rep": 1},
    "banker": {"name": "Казначей без совести", "cost": 140, "rep": 2},
    "legend_basement": {"name": "Легенда подвала", "cost": 110, "rep": 2},
    "gray": {"name": "Серый кардинал", "cost": 160, "rep": 3},
    "mayor_min": {"name": "Мэр на минималках", "cost": 130, "rep": 2},
}

PREMIUM_TITLE_POOL = [
    "👑 Премиум-батя района",
    "💎 Золотой подозреваемый",
    "🕶 VIP-мутный тип",
    "🏛 Почётный гражданин хаоса",
    "🔥 Легенда раннего доступа",
    "🗞 Главный герой газеты",
]

CITY_STYLE_POOL = [
    "🌆 Неоновый район",
    "🏛 Имперский двор",
    "🌃 Ночная мэрия",
    "🥇 Золотой подъезд",
    "🧊 Холодная республика",
]

REFERRAL_MILESTONES: dict[int, dict[str, Any]] = {
    1: {"trophy": "🌱 Первый приведённый район", "treasury": 80, "xp": 50},
    3: {"trophy": "🚦 Узел сарафанки", "treasury": 180, "xp": 120, "style": "🌆 Сарафанный район"},
    5: {"trophy": "📣 Голос района", "treasury": 300, "xp": 220, "style": "🏛 Район-магнит"},
    10: {"trophy": "👑 Лорд сарафанки", "treasury": 700, "xp": 500, "style": "👑 Империя приглашений"},
}

LEGENDARY_EVENTS = [
    "👑 В районе нашли древнюю корону. Никто не понял, чья она, но спорят все.",
    "🛸 НЛО пролетело над мэрией и забрало отчётность. Казна облегчённо выдохнула.",
    "🐈 Кот сел на документы и стал временным советником города.",
    "💸 Казна внезапно выросла. Казначей просит не задавать вопросов.",
    "🔥 Народ случайно устроил праздник вместо собрания. Эффективность выросла.",
]

EARLY_CITY_LIMIT = 100
EARLY_CITY_TROPHY = "🏛 Основатели Чатограда"
SHAME_TROPHIES = [
    "🤡 Позорная табличка рейда",
    "🧦 Носок проигранной войны",
    "📉 Грамота за стратегическое падение",
    "🥄 Деревянная медаль обороны",
]

AI_LEADER_FALLBACKS = [
    "район сегодня шумит так, будто у казны появился личный телохранитель",
    "жители делают вид, что всё под контролем, но подвал уже забронирован",
    "мэрия уверяет, что хаоса нет, хотя хаос уже записался в очередь",
]

SHOP_ITEMS: dict[str, dict[str, Any]] = {
    "festival": {
        "name": "🎉 Районный праздник",
        "cost": 80,
        "text": "город шумно отпраздновал и получил прилив активности",
        "xp_bonus": 45,
        "treasury_bonus": 4,
        "threat_delta": -1,
    },
    "shield": {
        "name": "🛡 Защита района",
        "cost": 110,
        "text": "район укрепился перед рейдами и стал менее нервным",
        "xp_bonus": 25,
        "treasury_bonus": 0,
        "threat_delta": -4,
    },
    "propaganda": {
        "name": "📢 Агитбригада",
        "cost": 70,
        "text": "жители сделали вид, что всё идёт по плану",
        "xp_bonus": 35,
        "treasury_bonus": 10,
        "threat_delta": 1,
    },
    "drums": {
        "name": "🥁 Рейдовые барабаны",
        "cost": 130,
        "text": "город получил боевой настрой и пару громких соседских жалоб",
        "xp_bonus": 55,
        "treasury_bonus": 8,
        "threat_delta": 2,
    },
    "monument": {
        "name": "🗿 Памятник основателям",
        "cost": 220,
        "text": "в районе появился монумент, теперь пафоса официально больше",
        "xp_bonus": 80,
        "treasury_bonus": 15,
        "threat_delta": 0,
        "trophy": "🗿 Памятник основателям",
    },
}

ROLES = [
    "Мэр без бюджета",
    "Олигарх на минималках",
    "Мафия района",
    "Полицейский с блокнотом",
    "Хакер из подвала",
    "Журналист-поджигатель",
    "Судья мемов",
    "Инфоцыган-стажёр",
    "Директор шаурмечной",
    "Казначей с мутной биографией",
    "Архитектор хаоса",
    "Министр кринжа",
]
WORK_ACTIONS = [
    ("открыл ларёк с энергетиками", 13, 8, 2),
    ("поймал городского жулика и забрал у него сдачу", 11, 6, 2),
    ("продал соседям гениальную идею за три монеты", 9, 9, 1),
    ("починил фонарь, который никто не просил чинить", 8, 10, 1),
    ("устроил подпольный турнир по мемам", 15, 5, 3),
    ("нашёл налоговую лазейку размером с автобус", 17, 4, 4),
    ("открыл районную доставку шаурмы и случайно стал предпринимателем", 14, 7, 3),
    ("провёл собрание жильцов и выжил", 10, 11, 2),
    ("продал NFT подъездной двери соседнему району", 16, 6, 3),
    ("поймал баг в городской экономике и назвал это реформой", 12, 12, 2),
    ("организовал фестиваль кринжа, но туристам понравилось", 18, 8, 4),
    ("собрал налог с тех, кто просто молча читает чат", 15, 7, 4),
]
EVENTS = [
    {
        "key": "golden_toilet",
        "title": "Золотой унитаз мэра",
        "text": "Мэр купил золотой унитаз для администрации. Город в шоке, но туристы внезапно начали делать селфи.",
        "options": ["Продать унитаз соседям", "Оставить как достопримечательность", "Начать расследование"],
    },
    {
        "key": "meme_plague",
        "title": "Мемная эпидемия",
        "text": "Город захватил один и тот же мем. Производительность упала, зато настроение подозрительно выросло.",
        "options": ["Запретить мем", "Открыть фабрику мемов", "Сделать мем гимном города"],
    },
    {
        "key": "black_market",
        "title": "Чёрный рынок пончиков",
        "text": "В подземке появился чёрный рынок пончиков. Казна может заработать, но полиция уже делает вид, что ничего не видит.",
        "options": ["Легализовать", "Разогнать", "Взять долю в казну"],
    },
    {
        "key": "neighbor_threat",
        "title": "Соседний чат flex-ит",
        "text": "Соседний город заявил, что у них жители умнее, экономика сильнее, а мемы острее. Терпеть это невозможно.",
        "options": ["Готовить рейд", "Предложить союз", "Запустить пропаганду"],
    },
    {
        "key": "ai_mayor",
        "title": "ИИ требует должность",
        "text": "Городской ИИ написал программу развития на 900 страниц и теперь требует стать заммэра. Очень подозрительно.",
        "options": ["Назначить", "Выключить из розетки", "Продать доступ инвесторам"],
    },
    {
        "key": "mayor_election",
        "title": "Внеплановые выборы",
        "text": "Жители требуют нового лидера. Старый лидер говорит, что его не было, но виноват всё равно он.",
        "options": ["Провести честные выборы", "Назначить самого громкого", "Продать должность в казну"],
    },
    {
        "key": "tax_revolt",
        "title": "Налоговый бунт",
        "text": "Жители внезапно поняли, что налоги существуют. Атмосфера в городе стала образовательной и опасной.",
        "options": ["Снизить налоги", "Удвоить и не объяснять", "Выдать всем мем-компенсацию"],
    },
    {
        "key": "secret_tunnel",
        "title": "Тайный тоннель",
        "text": "Под городом нашли тоннель в неизвестный чат. Оттуда пахнет возможностями и чужой казной.",
        "options": ["Исследовать", "Замуровать", "Сделать платный проход"],
    },
    {
        "key": "influencer_arrival",
        "title": "Приехал инфлюенсер",
        "text": "В город приехал блогер и обещает популярность. Но просит бартер, казну и уважение. Всё как обычно.",
        "options": ["Дать рекламу", "Выгнать", "Сделать его министром хайпа"],
    },
    {
        "key": "district_drama",
        "title": "Районная драма",
        "text": "Два жителя спорят, кто больше сделал для города. Остальные делают вид, что работают, но читают конфликт.",
        "options": ["Устроить суд", "Превратить спор в шоу", "Заставить обоих работать"],
    },
]


DRAMA_TEMPLATES = [
    {
        "title": "Скандал у администрации",
        "text": "{a} заявил, что {b} слишком подозрительно быстро богатеет. {c} уже требует суд, хотя сам пришёл просто посмотреть.",
        "options": ["Устроить публичный суд", "Сделать вид, что это реформа", "Назначить всех министрами"],
    },
    {
        "title": "Кража из районной казны",
        "text": "Из казны пропали монеты. Последним рядом видели {a}. {b} говорит, что это фотошоп, а {c} уже пишет разоблачение.",
        "options": ["Обыскать подвал", "Поверить на слово", "Собрать налог на расследование"],
    },
    {
        "title": "Мэрский кризис",
        "text": "Город проснулся и понял, что ему срочно нужен виноватый. Народ смотрит на {a}, {b} и {c}. Атмосфера демократичная, но нервная.",
        "options": ["Назначить виноватого", "Провести выборы", "Устроить мемный референдум"],
    },
    {
        "title": "Шаурмечный заговор",
        "text": "В городе обнаружена тайная схема с шаурмой. {a} молчит, {b} нервно смеётся, {c} требует долю в казну.",
        "options": ["Национализировать шаурму", "Открыть франшизу", "Закрыть глаза за 10 монет"],
    },
    {
        "title": "Подвальный инсайд",
        "text": "{a} шепнул, что {b} видел тайную таблицу расходов. {c} уже готовит расследование и делает серьёзное лицо.",
        "options": ["Проверить казну", "Назначить журналиста", "Спрятать таблицу глубже"],
    },
    {
        "title": "Бунт у мэрии",
        "text": "{a} требует новых выборов, {b} предлагает сначала построить банк, а {c} просто хочет трофей и уважение.",
        "options": ["Запустить дебаты", "Выдать всем лопаты", "Объявить чрезвычайный мем"],
    },
    {
        "title": "Рейдовые слухи",
        "text": "В городе ходят слухи, что {a} нашёл код чужого района. {b} уже точит вилы, {c} считает казну.",
        "options": ["Готовить рейд", "Отправить разведку", "Притвориться мирными"],
    },
]


RUMOR_TEMPLATES = [
    {
        "title": "Слух района",
        "text": "Говорят, {a} тайно копит монеты и уже примеряет мэрскую табличку. {b} делает вид, что ничего не знает.",
        "options": ["Поверить", "Не поверить", "Отправить в суд"],
    },
    {
        "title": "Подвальный шёпот",
        "text": "Кто-то слышал, что {a} видел тайный бюджет города. {b} требует расследование, но слишком громко.",
        "options": ["Проверить казну", "Назначить журналиста", "Закрыть тему"],
    },
    {
        "title": "Городской сплетник",
        "text": "В районе обсуждают, что {a} и {b} мутят союз без согласования с подъездом.",
        "options": ["Одобрить мутки", "Потребовать отчёт", "Сделать вид, что это дипломатия"],
    },
]


@dataclass(frozen=True)
class DuelResult:
    text: str
    winner: str | None
    loser: str | None
    stake: int
    challenger_score: int = 0
    target_score: int = 0


@dataclass(frozen=True)
class WorkResult:
    text: str
    coins: int
    xp: int
    treasury: int
    cooldown_left_minutes: int = 0


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def random_code(prefix: str = "") -> str:
    alphabet = string.ascii_uppercase + string.digits
    return prefix + "".join(secrets.choice(alphabet) for _ in range(8))


def make_city_name(chat_title: str | None = None) -> str:
    if chat_title and len(chat_title.strip()) >= 3:
        clean = chat_title.strip()[:32]
        if random.random() < 0.55:
            return clean
    return f"{random.choice(CITY_PREFIXES)} {random.choice(CITY_NOUNS)}-{random.randint(7, 99)}"


def make_ref_code(telegram_user_id: int) -> str:
    raw = f"{telegram_user_id}:{secrets.token_hex(4)}".encode()
    return hashlib.sha1(raw).hexdigest()[:10].upper()


def get_or_create_player(
    db: Session,
    telegram_user_id: int,
    username: str | None,
    first_name: str | None,
    referral_code: str | None = None,
) -> tuple[Player, bool, str | None]:
    player = db.scalar(select(Player).where(Player.telegram_user_id == telegram_user_id))
    if player:
        changed = False
        if username and player.username != username:
            player.username = username
            changed = True
        if first_name and player.first_name != first_name:
            player.first_name = first_name
            changed = True
        if changed:
            player.updated_at = utcnow()
        return player, False, None

    referrer: Player | None = None
    if referral_code:
        referrer = db.scalar(select(Player).where(Player.ref_code == referral_code))

    player = Player(
        telegram_user_id=telegram_user_id,
        username=username,
        first_name=first_name or "Игрок",
        role=random.choice(ROLES),
        ref_code=make_ref_code(telegram_user_id),
        referred_by_player_id=referrer.id if referrer else None,
        coins=10 if referrer else 0,
        xp=5 if referrer else 0,
    )
    db.add(player)
    db.flush()

    reward_text = None
    if referrer and referrer.telegram_user_id != telegram_user_id:
        referrer.coins += 25
        referrer.xp += 10
        reward_text = f"Реферал засчитан: @{referrer.username or referrer.first_name} получил +25 монет."

    return player, True, reward_text


def get_or_create_city(db: Session, chat_id: int, title: str | None) -> tuple[City, bool]:
    city = db.scalar(select(City).where(City.chat_id == chat_id))
    if city:
        if title and city.title != title:
            city.title = title
            city.updated_at = utcnow()
        return city, False

    city = City(
        chat_id=chat_id,
        title=title or "Безымянный чат",
        name=make_city_name(title),
        invite_code=random_code("C"),
        treasury=25,
        xp=0,
        threat=random.randint(3, 11),
    )
    db.add(city)
    db.flush()
    grant_early_city_trophy(db, city)
    log(db, city.id, None, "city_created", f"Город {city.name} основан.")
    add_city_history(city, f"Город {city.name} основан.", "🏙")
    return city, True


def grant_early_city_trophy(db: Session, city: City) -> bool:
    """Give a permanent launch trophy to the first public wave of cities."""
    total = db.scalar(select(func.count(City.id))) or 0
    if int(total) > EARLY_CITY_LIMIT:
        return False
    trophies = get_city_trophies(city)
    if EARLY_CITY_TROPHY in trophies:
        return False
    award_trophy(city, EARLY_CITY_TROPHY)
    city.xp += 20
    city.treasury += 25
    log(db, city.id, None, "early_city", f"Город получил трофей раннего запуска: {EARLY_CITY_TROPHY}.")
    return True


def create_launch_event(db: Session, city: City, force: bool = False) -> CityEvent | None:
    """First wow-event for a newly activated group."""
    if not force:
        already = db.scalar(
            select(CityEvent).where(CityEvent.city_id == city.id, CityEvent.event_key == "launch_first_event")
        )
        if already:
            return None
    active = get_active_event(db, city)
    if active and not force:
        return active
    if active and force:
        active.resolved_at = utcnow()
    event = CityEvent(
        city_id=city.id,
        event_key="launch_first_event",
        title="Первый скандал района",
        text="Город только появился, а кто-то уже трогал казну. Казна маленькая, но подозрения большие.",
        option_1="Устроить первый суд",
        option_2="Назначить временного виновного",
        option_3="Сделать вид, что это традиция",
        votes_json="{}",
    )
    db.add(event)
    city.last_event_at = utcnow()
    city.xp += 8
    log(db, city.id, None, "launch_event", "Запущен первый скандал района.")
    add_city_history(city, "Первый скандал района запущен после основания.", "🚨")
    db.flush()
    return event


def join_city(db: Session, city: City, player: Player, is_chat_owner: bool = False) -> tuple[Membership, bool]:
    membership = db.scalar(
        select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id)
    )
    if membership:
        if is_chat_owner:
            grant_founder_title(db, city, player, membership)
        return membership, False

    membership = Membership(city_id=city.id, player_id=player.id, influence=1, reputation=0)
    db.add(membership)
    city.xp += 3
    city.treasury += 2
    maybe_level_up(city)
    log(db, city.id, player.id, "join", f"{display_player(player)} вступил в город.")

    if is_chat_owner:
        grant_founder_title(db, city, player, membership)
    refresh_player_achievements(db, city, player)
    db.flush()
    return membership, True


def grant_founder_title(db: Session, city: City, player: Player, membership: Membership | None = None) -> Membership:
    """Grant the unique founder title only to the actual Telegram chat owner."""
    if membership is None:
        membership = db.scalar(
            select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id)
        )
        if membership is None:
            membership = Membership(city_id=city.id, player_id=player.id, influence=1, reputation=0)
            db.add(membership)
            db.flush()

    old_founders = db.scalars(
        select(Membership).where(Membership.city_id == city.id, Membership.special_title == FOUNDER_TITLE)
    ).all()
    for old in old_founders:
        if old.player_id != player.id:
            old.special_title = None

    first_claim = membership.special_title != FOUNDER_TITLE
    membership.special_title = FOUNDER_TITLE
    membership.influence = max(membership.influence, 12)
    if first_claim:
        membership.reputation += 15
        city.treasury += 15
        city.xp += 20
        log(db, city.id, player.id, "founder_claim", f"{display_player(player)} получил титул Основатель района.")
        grant_achievement(db, city, player, "founder")
    city.owner_telegram_user_id = player.telegram_user_id
    maybe_level_up(city)
    db.flush()
    return membership


def display_player(player: Player) -> str:
    if player.username:
        return f"@{player.username}"
    return player.first_name


def city_population(db: Session, city_id: int) -> int:
    return db.scalar(select(func.count(Membership.id)).where(Membership.city_id == city_id)) or 0


def city_power(db: Session, city_id: int) -> int:
    influence = db.scalar(select(func.coalesce(func.sum(Membership.influence), 0)).where(Membership.city_id == city_id)) or 0
    city = db.get(City, city_id)
    if not city:
        return 0
    return int(influence + city.level * 12 + city.treasury * 0.15 + city.xp * 0.05 + buildings_power_bonus(city))


def maybe_level_up(city: City) -> bool:
    leveled = False
    while city.xp >= city.level * 100:
        city.xp -= city.level * 100
        city.level += 1
        city.treasury += 25
        city.threat += 2
        leveled = True
    return leveled


def get_city_buildings(city: City) -> dict[str, int]:
    try:
        raw = json.loads(city.buildings_json or "{}")
    except json.JSONDecodeError:
        return {}
    return {str(key): int(value) for key, value in raw.items() if str(key) in BUILDINGS and int(value) > 0}


def set_city_buildings(city: City, buildings: dict[str, int]) -> None:
    city.buildings_json = json.dumps(buildings, ensure_ascii=False, sort_keys=True)


def buildings_power_bonus(city: City) -> int:
    buildings = get_city_buildings(city)
    return sum(level * (BUILDINGS[key]["xp_bonus"] // 4 + BUILDINGS[key]["treasury_bonus"] // 3) for key, level in buildings.items())


def city_rank(city: City) -> str:
    if city.level >= 8:
        return "Легендарный город"
    if city.level >= 6:
        return "Империя"
    if city.level >= 4:
        return "Республика"
    if city.level >= 3:
        return "Чатоград"
    if city.level >= 2:
        return "Район"
    return "Подъезд"


def building_payload(city: City) -> dict[str, Any]:
    owned = get_city_buildings(city)
    items = []
    for key, spec in BUILDINGS.items():
        level = owned.get(key, 0)
        cost = int(spec["cost"] * (1 + level * 0.75))
        items.append({
            "key": key,
            "name": spec["name"],
            "level": level,
            "cost": cost,
            "text": spec["text"],
        })
    return {"owned": owned, "items": items}



def player_level(xp: int) -> int:
    # Simple stable curve: level 1 starts at 0 XP, each next level costs a bit more.
    level = 1
    remaining = max(0, int(xp))
    cost = 75
    while remaining >= cost and level < 99:
        remaining -= cost
        level += 1
        cost = int(cost * 1.18) + 20
    return level


def player_level_progress(xp: int) -> dict[str, int]:
    level = 1
    remaining = max(0, int(xp))
    cost = 75
    while remaining >= cost and level < 99:
        remaining -= cost
        level += 1
        cost = int(cost * 1.18) + 20
    return {"level": level, "xp_in_level": remaining, "xp_for_next": cost}


def _same_utc_day(left: datetime | None, right: datetime | None = None) -> bool:
    if not left:
        return False
    right = right or utcnow()
    left = _aware(left)
    right = _aware(right)
    return bool(left and right and left.date() == right.date())


def daily_payload(player: Player) -> dict[str, Any]:
    now = utcnow()
    collected = _same_utc_day(player.last_daily_at, now)
    streak = int(player.daily_streak or 0)
    next_streak = streak if collected else (streak + 1 if _aware(player.last_daily_at) and (_aware(player.last_daily_at).date() == (now.date() - timedelta(days=1))) else 1)
    reward = 10 + min(next_streak, 7) * 5
    return {"collected": collected, "streak": streak, "next_streak": next_streak, "reward": reward}


def collect_daily_reward(db: Session, city: City, player: Player) -> tuple[bool, str, dict[str, Any]]:
    now = utcnow()
    if _same_utc_day(player.last_daily_at, now):
        return False, "Сегодня награда уже забрана. Казна не резиновая, хитрец.", daily_payload(player)

    last = _aware(player.last_daily_at)
    if last and last.date() == (now.date() - timedelta(days=1)):
        player.daily_streak = int(player.daily_streak or 0) + 1
    else:
        player.daily_streak = 1

    reward = 10 + min(player.daily_streak, 7) * 5 + city.level
    xp_gain = 8 + min(player.daily_streak, 7)
    player.coins += reward
    player.xp += xp_gain
    player.last_daily_at = now

    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    if membership:
        membership.influence += 1
        membership.reputation += 1

    city.treasury += max(2, reward // 5)
    city.xp += 6 + min(player.daily_streak, 7)
    trophy_line = ""
    if player.daily_streak % 7 == 0:
        trophy = award_trophy(city, "🎁 Недельный жетон района")
        trophy_line = f" Трофей города: {trophy}."
    maybe_level_up(city)
    log(db, city.id, player.id, "daily", f"{display_player(player)} забрал ежедневную награду: +{reward} монет, серия {player.daily_streak}.")
    refresh_player_achievements(db, city, player)
    db.flush()
    text = f"{display_player(player)} забрал ежедневную награду: +{reward} монет, +{xp_gain} XP. Серия: {player.daily_streak} дней.{trophy_line}"
    return True, text, daily_payload(player)


def get_city_shop(city: City) -> dict[str, int]:
    try:
        raw = json.loads(city.shop_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): int(value) for key, value in raw.items() if str(key) in SHOP_ITEMS and int(value) > 0}


def set_city_shop(city: City, items: dict[str, int]) -> None:
    city.shop_json = json.dumps(items, ensure_ascii=False, sort_keys=True)



def get_city_premium(city: City) -> dict[str, Any]:
    try:
        data = json.loads(city.premium_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    clean: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[str(key)] = value
        elif isinstance(value, list):
            clean[str(key)] = [str(item)[:80] for item in value[:20]]
    return clean


def set_city_premium(city: City, data: dict[str, Any]) -> None:
    city.premium_json = json.dumps(data, ensure_ascii=False, sort_keys=True)


def add_city_premium_counter(city: City, key: str, amount: int = 1) -> int:
    data = get_city_premium(city)
    current = int(data.get(key, 0) or 0) + amount
    data[key] = max(0, current)
    set_city_premium(city, data)
    return int(data[key])


def city_premium_payload(city: City) -> dict[str, Any]:
    data = get_city_premium(city)
    return {
        "style": data.get("style") or "обычный",
        "ai_newspaper_tokens": int(data.get("ai_newspaper_tokens", 0) or 0),
        "rename_tokens": int(data.get("rename_tokens", 0) or 0),
        "premium_events": int(data.get("premium_events", 0) or 0),
        "season_badge": data.get("season_badge") or "",
    }



def award_referral_milestones(db: Session, city: City) -> list[str]:
    total = city_referral_count(db, city.id)
    premium = get_city_premium(city)
    awarded = premium.get("referral_milestones") or []
    if not isinstance(awarded, list):
        awarded = []
    awarded_set = {int(item) for item in awarded if str(item).isdigit()}
    messages: list[str] = []
    for threshold, spec in sorted(REFERRAL_MILESTONES.items()):
        if total >= threshold and threshold not in awarded_set:
            trophy = award_trophy(city, str(spec["trophy"]))
            city.treasury += int(spec.get("treasury", 0))
            city.xp += int(spec.get("xp", 0))
            if spec.get("style"):
                premium["style"] = spec["style"]
            awarded.append(threshold)
            messages.append(f"{threshold} районов: {trophy}")
            log(db, city.id, None, "referral_milestone", f"Реферальный уровень {threshold}: {trophy}.")
    premium["referral_milestones"] = sorted({int(item) for item in awarded if str(item).isdigit()})
    set_city_premium(city, premium)
    maybe_level_up(city)
    db.flush()
    return messages


def referral_progress_payload(db: Session, city: City) -> dict[str, Any]:
    total = city_referral_count(db, city.id)
    premium = get_city_premium(city)
    awarded = premium.get("referral_milestones") or []
    if not isinstance(awarded, list):
        awarded = []
    return {
        "total": total,
        "awarded": [int(item) for item in awarded if str(item).isdigit()],
        "milestones": [
            {
                "threshold": threshold,
                "trophy": spec["trophy"],
                "done": total >= threshold,
            }
            for threshold, spec in sorted(REFERRAL_MILESTONES.items())
        ],
    }


def shop_payload(city: City) -> dict[str, Any]:
    owned = get_city_shop(city)
    items = []
    for key, spec in SHOP_ITEMS.items():
        count = owned.get(key, 0)
        cost = int(spec["cost"] * (1 + count * 0.45))
        items.append({"key": key, "name": spec["name"], "count": count, "cost": cost, "text": spec["text"]})
    return {"owned": owned, "items": items}


def buy_shop_item(db: Session, city: City, key: str) -> tuple[bool, str, dict[str, Any]]:
    if key not in SHOP_ITEMS:
        return False, "Такого товара нет. Магазинщик сделал вид, что не слышал.", shop_payload(city)
    owned = get_city_shop(city)
    count = owned.get(key, 0)
    spec = SHOP_ITEMS[key]
    cost = int(spec["cost"] * (1 + count * 0.45))
    if city.treasury < cost:
        return False, f"В казне не хватает монет. Нужно {cost}, есть {city.treasury}.", shop_payload(city)

    city.treasury -= cost
    city.treasury += int(spec.get("treasury_bonus", 0))
    city.xp += int(spec.get("xp_bonus", 0))
    city.threat = max(0, city.threat + int(spec.get("threat_delta", 0)))
    owned[key] = count + 1
    set_city_shop(city, owned)
    trophy = spec.get("trophy")
    trophy_line = ""
    if trophy:
        trophy_line = f" Трофей: {award_trophy(city, str(trophy))}."
    maybe_level_up(city)
    log(db, city.id, None, "shop", f"Куплено: {spec['name']} — {spec['text']}.")
    db.flush()
    return True, f"{spec['name']} куплено. {spec['text']}.{trophy_line}", shop_payload(city)


def season_payload(city: City) -> dict[str, Any]:
    start = _aware(city.season_started_at) or _aware(city.created_at) or utcnow()
    now = utcnow()
    passed = max(0, (now - start).days)
    left = max(0, SEASON_DAYS - passed)
    return {
        "number": int(city.season_number or 1),
        "started_at": start.isoformat(),
        "days_passed": passed,
        "days_left": left,
        "duration_days": SEASON_DAYS,
        "expired": passed >= SEASON_DAYS,
        "rank": city_rank(city),
    }


def maybe_roll_season(db: Session, city: City, force: bool = False) -> tuple[bool, str, dict[str, Any]]:
    payload = season_payload(city)
    if not payload["expired"] and not force:
        return False, "Сезон ещё идёт. Рано закрывать лавочку.", payload
    trophy = award_trophy(city, f"🏅 Сезон {city.season_number}: {city_rank(city)}")
    old_season = city.season_number
    city.season_number = int(city.season_number or 1) + 1
    city.season_started_at = utcnow()
    city.threat = max(3, city.threat // 2)
    city.xp = max(0, city.xp // 3)
    log(db, city.id, None, "season_roll", f"Сезон {old_season} закрыт. Трофей: {trophy}.")
    db.flush()
    return True, f"Сезон {old_season} закрыт. Город получил трофей: {trophy}. Новый сезон открыт.", season_payload(city)


def build_city_building(db: Session, city: City, key: str) -> tuple[bool, str, dict[str, Any]]:
    if key not in BUILDINGS:
        return False, "Такой постройки нет. Архитектор ушёл курить.", building_payload(city)
    buildings = get_city_buildings(city)
    level = buildings.get(key, 0)
    spec = BUILDINGS[key]
    cost = int(spec["cost"] * (1 + level * 0.75))
    if city.treasury < cost:
        return False, f"В казне не хватает монет. Нужно {cost}, есть {city.treasury}.", building_payload(city)

    city.treasury -= cost
    buildings[key] = level + 1
    set_city_buildings(city, buildings)
    city.treasury += int(spec["treasury_bonus"])
    city.xp += int(spec["xp_bonus"])
    maybe_level_up(city)
    log(db, city.id, None, "building", f"Построено: {spec['name']} ур. {buildings[key]} — {spec['text']}.")
    db.flush()
    return True, f"{spec['name']} ур. {buildings[key]} построена. {spec['text']}.", building_payload(city)


def membership_status(membership: Membership | None) -> str:
    if not membership:
        return "не в городе"
    jailed_until = _aware(membership.jailed_until)
    if jailed_until and utcnow() < jailed_until:
        minutes = int((jailed_until - utcnow()).total_seconds() // 60) + 1
        return f"в подвале ещё {minutes} мин."
    return "свободен"


def player_profile(db: Session, city: City, player: Player) -> dict[str, Any]:
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    level_info = player_level_progress(player.xp)
    return {
        "name": display_player(player),
        "role": player.role,
        "title": player_title(player, membership) if membership else "Гость",
        "coins": player.coins,
        "xp": player.xp,
        "level": level_info["level"],
        "xp_in_level": level_info["xp_in_level"],
        "xp_for_next": level_info["xp_for_next"],
        "daily_streak": int(player.daily_streak or 0),
        "daily_available": not _same_utc_day(player.last_daily_at),
        "faction": FACTIONS.get(membership.faction, {}).get("name") if membership and membership.faction else "нет",
        "inventory_count": sum(get_inventory(membership).values()) if membership else 0,
        "influence": membership.influence if membership else 0,
        "reputation": membership.reputation if membership else 0,
        "status": membership_status(membership),
        "convictions": membership.convictions if membership else 0,
        "achievements_count": len(get_achievements(membership)),
        "secret_role": SECRET_ROLES.get(membership.secret_role or "", {}).get("name") if membership else "нет",
        "mission": mission_payload(db, city, player, check=True) if membership else {"active": False},
        "joined": bool(membership),
    }


def create_court_event(db: Session, city: City, target: Player | None = None, force: bool = True) -> CityEvent | None:
    active = get_active_event(db, city)
    if active and not force:
        return active
    if active and force:
        active.resolved_at = utcnow()
        log(db, city.id, None, "event_replaced", f"Старое событие закрыто ради суда: {active.title}")

    players = _city_players(db, city, limit=12)
    if not players:
        return None
    target = target or random.choice(players)
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == target.id))
    if not membership:
        return None
    accusation = random.choice([
        "подозрительно быстро разбогател и слишком уверенно молчит",
        "слишком часто говорит слово ‘реформа’",
        "видел казну и не моргнул",
        "мутит что-то у районной шаурмечной",
        "выглядит как человек, который знает больше, чем говорит",
    ])
    event = CityEvent(
        city_id=city.id,
        event_key=f"court:{target.id}",
        title="Суд Чатограда",
        text=f"Подсудимый: {display_player(target)}. Обвинение: {accusation}.",
        option_1="Оправдать",
        option_2="Отправить в подвал",
        option_3="Выписать штраф в казну",
        votes_json="{}",
    )
    db.add(event)
    db.flush()
    city.last_event_at = utcnow()
    log(db, city.id, target.id, "court", f"Начался суд над {display_player(target)}.")
    return event


def work(db: Session, city: City, player: Player, cooldown_hours: int = 4) -> WorkResult:
    now = utcnow()
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    jailed = bool(membership and _aware(membership.jailed_until) and now < _aware(membership.jailed_until))

    last_work = _aware(player.last_work_at)
    if last_work:
        next_allowed = last_work + timedelta(hours=cooldown_hours)
        if now < next_allowed:
            left = int((next_allowed - now).total_seconds() // 60) + 1
            return WorkResult("Ты уже работал. Город не резиновый, даже коррупция по расписанию.", 0, 0, 0, left)

    action, base_coins, base_xp, base_treasury = random.choice(WORK_ACTIONS)
    bonus = random.randint(0, max(2, city.level * 2))
    coins = base_coins + bonus
    xp = base_xp + random.randint(0, 5)
    treasury = base_treasury + random.randint(0, 3)

    if membership and membership.faction == "workers":
        coins += 3
        xp += 2
    elif membership and membership.faction == "bankers":
        coins += 2
        treasury += 2
    elif membership and membership.faction == "press":
        xp += 3
    elif membership and membership.faction == "law":
        treasury += 1

    if jailed:
        coins = max(1, coins // 2)
        xp = max(1, xp // 2)
        treasury = max(0, treasury // 2)

    player.coins += coins
    player.xp += xp
    player.energy = max(0, player.energy - 1)
    player.last_work_at = now
    city.treasury += treasury
    city.xp += xp + treasury

    if membership:
        membership.influence += 1
        membership.reputation += 0 if jailed else random.randint(0, 2)

    leveled = maybe_level_up(city)
    prefix = "из подвала " if jailed else ""
    text = f"{display_player(player)} {prefix}{action}."
    if jailed:
        text += " Доход урезан: подвал — не коворкинг."
    if leveled:
        text += f" Город вырос до уровня {city.level}."
    log(db, city.id, player.id, "work", text)
    refresh_player_achievements(db, city, player)
    return WorkResult(text, coins, xp, treasury)


def create_daily_event(db: Session, city: City, force: bool = False) -> CityEvent | None:
    active = db.scalar(select(CityEvent).where(CityEvent.city_id == city.id, CityEvent.resolved_at.is_(None)).order_by(desc(CityEvent.created_at)))
    if active and not force:
        return active

    last_event = _aware(city.last_event_at)
    if last_event and not force and utcnow() < last_event + timedelta(hours=18):
        return None

    template = random.choice(EVENTS)
    event = CityEvent(
        city_id=city.id,
        event_key=template["key"],
        title=template["title"],
        text=template["text"],
        option_1=template["options"][0],
        option_2=template["options"][1],
        option_3=template["options"][2],
        votes_json="{}",
    )
    db.add(event)
    db.flush()
    city.last_event_at = utcnow()
    log(db, city.id, None, "event", f"Новое событие: {event.title}")
    return event


def get_active_event(db: Session, city: City) -> CityEvent | None:
    return db.scalar(
        select(CityEvent)
        .where(CityEvent.city_id == city.id, CityEvent.resolved_at.is_(None))
        .order_by(desc(CityEvent.created_at))
    )


def create_smart_city_event(db: Session, city: City) -> CityEvent | None:
    population = city_population(db, city.id)
    if population >= 3 and city.treasury >= 160 and random.random() < 0.35:
        return create_rumor_event(db, city, force=True)
    if population >= 4 and random.random() < 0.25:
        return create_drama_event(db, city, force=True)
    if city.threat >= 12 and random.random() < 0.20:
        return create_revolt_event(db, city)
    return create_daily_event(db, city, force=True)


def create_new_event_if_due(db: Session, city: City) -> CityEvent | None:
    if get_active_event(db, city):
        return None
    if not auto_event_due(city):
        return None
    return create_smart_city_event(db, city)


def vote_event(db: Session, city: City, player: Player, option: int) -> tuple[CityEvent | None, str]:
    if option not in (1, 2, 3):
        return None, "Голосовать можно только 1, 2 или 3. Демократия, но не настолько."

    event = db.scalar(select(CityEvent).where(CityEvent.city_id == city.id, CityEvent.resolved_at.is_(None)).order_by(desc(CityEvent.created_at)))
    if not event:
        return None, "Активного события нет. Запусти /event."

    votes = json.loads(event.votes_json or "{}")
    votes[str(player.id)] = option
    event.votes_json = json.dumps(votes, ensure_ascii=False)

    city.xp += 2
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    if membership:
        membership.reputation += 1
    log(db, city.id, player.id, "vote", f"{display_player(player)} проголосовал за вариант {option}.")
    return event, f"Голос принят: вариант {option}."


def resolve_event(db: Session, city: City) -> str:
    event = db.scalar(select(CityEvent).where(CityEvent.city_id == city.id, CityEvent.resolved_at.is_(None)).order_by(desc(CityEvent.created_at)))
    if not event:
        return "Активного события нет."

    votes = json.loads(event.votes_json or "{}")
    if not votes:
        return "Голосов нет. Даже NPC не пришли, больно смотреть."

    counts = {1: 0, 2: 0, 3: 0}
    for value in votes.values():
        if value in (1, 2, 3):
            counts[value] += 1
    winner = max(counts, key=counts.get)

    rewards = {
        1: (20, 15, -1),
        2: (10, 25, 1),
        3: (35, 5, 2),
    }
    treasury, xp, threat = rewards[winner]
    city.treasury = max(0, city.treasury + treasury)
    city.xp += xp
    city.threat = max(0, city.threat + threat)
    event.resolved_at = utcnow()
    maybe_level_up(city)

    options = {1: event.option_1, 2: event.option_2, 3: event.option_3}
    special_line = ""
    if event.event_key.startswith("mayor:"):
        candidate_ids = [part for part in event.event_key.split(":", 1)[1].split(",") if part]
        if 0 <= winner - 1 < len(candidate_ids):
            candidate = db.get(Player, int(candidate_ids[winner - 1]))
            if candidate:
                candidate.role = "Мэр Чатограда"
                membership = db.scalar(
                    select(Membership).where(Membership.city_id == city.id, Membership.player_id == candidate.id)
                )
                if membership:
                    membership.influence += 5
                    membership.reputation += 10
                city.treasury += 15
                city.xp += 20
                trophy = award_trophy(city, "👑 Корона спорной легитимности")
                special_line = f"\n👑 Новый мэр: {display_player(candidate)}. Трофей города: {trophy}."
                log(db, city.id, candidate.id, "mayor_elected", f"{display_player(candidate)} избран мэром города.")
                add_city_history(city, f"{display_player(candidate)} избран мэром города.", "👑")

    if event.event_key.startswith("court:"):
        try:
            target_id = int(event.event_key.split(":", 1)[1])
        except ValueError:
            target_id = 0
        target = db.get(Player, target_id) if target_id else None
        membership = None
        if target:
            membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == target.id))
        if target and membership:
            if winner == 1:
                membership.reputation += 5
                membership.influence += 1
                special_line = f"\n✅ {display_player(target)} оправдан. Репутация выросла, прокурор грустит."
                log(db, city.id, target.id, "court_acquit", f"{display_player(target)} оправдан судом.")
            elif winner == 2:
                membership.jailed_until = utcnow() + timedelta(hours=3)
                membership.convictions += 1
                membership.reputation -= 5
                membership.influence = max(0, membership.influence - 1)
                special_line = f"\n🔒 {display_player(target)} отправлен в подвал на 3 часа. Доход временно урезан."
                log(db, city.id, target.id, "court_jail", f"{display_player(target)} отправлен в подвал на 3 часа.")
            elif winner == 3:
                fine = min(target.coins, max(8, int(target.coins * 0.25)))
                target.coins = max(0, target.coins - fine)
                city.treasury += fine
                membership.convictions += 1
                membership.reputation -= 2
                special_line = f"\n💰 {display_player(target)} оштрафован на {fine} монет. Казна довольно хрюкнула."
                log(db, city.id, target.id, "court_fine", f"{display_player(target)} оштрафован на {fine} монет.")

    if event.event_key == "revolt":
        if winner == 1:
            affected = db.scalars(
                select(Membership).where(Membership.city_id == city.id, Membership.civic_title.like("%Мэр%"))
            ).all()
            for item in affected:
                item.civic_title = None
                item.reputation = max(-50, item.reputation - 8)
            city.threat += 3
            city.xp += 25
            trophy = award_trophy(city, "🔥 Печать переворота")
            special_line = f"\n🔥 Бунт победил. Старую власть снесло сквозняком. Трофей: {trophy}."
            add_city_history(city, "Бунт победил. Власть была свергнута.", "🔥")
        elif winner == 2:
            city.threat = max(0, city.threat - 2)
            city.treasury += 15
            special_line = "\n🛡 Порядок устоял. Мэрия делает вид, что контролировала ситуацию."
            add_city_history(city, "Бунт подавлен. Порядок устоял.", "🛡")
        else:
            city.treasury += 8
            city.xp += 18
            special_line = "\n🎉 Бунт превратили в районный праздник. Политика проиграла шаурме."
            add_city_history(city, "Бунт стал районным праздником.", "🎉")

    log(db, city.id, None, "resolve_event", f"Событие решено: {options[winner]}")
    return (
        f"Событие решено. Победил вариант {winner}: {options[winner]}\n"
        f"Казна: +{treasury}, опыт города: +{xp}, угроза: {threat:+d}."
        f"{special_line}"
    )



def get_city_trophies(city: City) -> list[str]:
    try:
        raw = json.loads(city.trophies_json or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()][:20]


def set_city_trophies(city: City, trophies: list[str]) -> None:
    city.trophies_json = json.dumps(trophies[:20], ensure_ascii=False)


def award_trophy(city: City, trophy: str | None = None) -> str:
    trophies = get_city_trophies(city)
    trophy = trophy or random.choice(TROPHY_POOL)
    if trophy in trophies:
        trophies.remove(trophy)
    trophies.insert(0, trophy)
    set_city_trophies(city, trophies)
    return trophy


def create_raid_challenge(db: Session, attacker: City, defender_code: str) -> tuple[War | None, str, City | None, bool]:
    defender = db.scalar(select(City).where(City.invite_code == defender_code.strip().upper()))
    if not defender:
        return None, "Город с таким кодом не найден. Видимо, спрятался за гаражами.", None, False
    if defender.id == attacker.id:
        return None, "Нельзя рейдить свой же город. Даже Чатоград такое осуждает.", defender, False

    active = db.scalar(
        select(War).where(
            War.status == "active",
            War.attacker_city_id == attacker.id,
            War.defender_city_id == defender.id,
        )
    )
    if active:
        return active, "Рейд уже висит. Ждём, пока второй город нажмёт «Принять».", defender, False

    war = War(attacker_city_id=attacker.id, defender_city_id=defender.id, status="active")
    db.add(war)
    db.flush()
    log(db, attacker.id, None, "raid_challenge", f"{attacker.name} вызвал {defender.name} на рейд.")
    log(db, defender.id, None, "raid_challenge", f"{attacker.name} вызвал {defender.name} на рейд.")
    return war, f"{attacker.name} вызвал {defender.name} на рейд.", defender, True


def active_incoming_raids(db: Session, defender: City, limit: int = 5) -> list[dict[str, Any]]:
    wars = db.scalars(
        select(War)
        .where(War.status == "active", War.defender_city_id == defender.id)
        .order_by(desc(War.created_at))
        .limit(limit)
    ).all()
    result: list[dict[str, Any]] = []
    for war in wars:
        attacker = db.get(City, war.attacker_city_id)
        if attacker:
            result.append({"id": war.id, "attacker": attacker.name, "attacker_power": city_power(db, attacker.id), "created_at": war.created_at})
    return result


def raid_score_breakdown(db: Session, city: City) -> dict[str, int]:
    """Readable raid score parts, cheap enough for buttons and tests."""
    base = city_power(db, city.id)
    population = city_population(db, city.id) * 4
    alliances = city_alliance_count(db, city.id) * 18
    trophies = len(get_city_trophies(city)) * 7
    threat = max(0, int(city.threat or 0)) * 2
    random_part = random.randint(10, 55)
    total = base + population + alliances + trophies + threat + random_part
    return {
        "base": int(base),
        "population": int(population),
        "alliances": int(alliances),
        "trophies": int(trophies),
        "threat": int(threat),
        "random": int(random_part),
        "total": int(total),
    }


def resolve_raid_challenge(db: Session, defender: City, war_id: int) -> tuple[War | None, str]:
    war = db.get(War, war_id)
    if not war or war.status != "active" or war.defender_city_id != defender.id:
        return None, "Рейд не найден или уже закончился. Кто-то опять опоздал на войну."

    attacker = db.get(City, war.attacker_city_id)
    if not attacker:
        war.status = "finished"
        war.finished_at = utcnow()
        return war, "Город-агрессор исчез. Победа бюрократией."

    attacker_parts = raid_score_breakdown(db, attacker)
    defender_parts = raid_score_breakdown(db, defender)
    attacker_score = attacker_parts["total"]
    defender_score = defender_parts["total"]
    war.attacker_score = attacker_score
    war.defender_score = defender_score
    war.status = "finished"
    war.finished_at = utcnow()

    if attacker_score >= defender_score:
        prize = max(12, int(defender.treasury * 0.18))
        defender.treasury = max(0, defender.treasury - prize)
        attacker.treasury += prize
        attacker.xp += 45
        defender.xp += 14
        trophy = award_trophy(attacker)
        shame = award_trophy(defender, random.choice(SHAME_TROPHIES))
        text = (
            f"{attacker.name} победил {defender.name}. Счёт {attacker_score}:{defender_score}. "
            f"Добыча: {prize} монет. Трофей победителя: {trophy}. "
            f"Проигравшим досталось: {shame}."
        )
    else:
        prize = max(10, int(attacker.treasury * 0.12))
        attacker.treasury = max(0, attacker.treasury - prize)
        defender.treasury += prize
        defender.xp += 45
        attacker.xp += 14
        trophy = award_trophy(defender)
        shame = award_trophy(attacker, random.choice(SHAME_TROPHIES))
        text = (
            f"{defender.name} отбился от {attacker.name}. Счёт {defender_score}:{attacker_score}. "
            f"Компенсация: {prize} монет. Трофей обороны: {trophy}. "
            f"Атакующим досталось: {shame}."
        )

    maybe_level_up(attacker)
    maybe_level_up(defender)
    log(db, attacker.id, None, "raid_finished", text)
    log(db, defender.id, None, "raid_finished", text)
    add_city_history(attacker, text, "⚔️")
    add_city_history(defender, text, "⚔️")
    db.flush()
    return war, text


def start_war(db: Session, attacker: City, defender_code: str) -> tuple[War | None, str]:
    """Compatibility helper: create a raid challenge and instantly resolve it."""
    war, text, defender, _created = create_raid_challenge(db, attacker, defender_code)
    if not war or not defender:
        return war, text
    resolved_war, resolved_text = resolve_raid_challenge(db, defender, war.id)
    return resolved_war, resolved_text


def appoint_city_official(db: Session, city: City, target: Player, title_key: str) -> tuple[bool, str]:
    normalized = title_key.strip().lower().replace("ё", "е")
    aliases = {"начальник": "участковый", "полиция": "участковый", "военный": "воевода", "стройка": "архитектор"}
    normalized = aliases.get(normalized, normalized)
    title = APPOINTABLE_TITLES.get(normalized)
    if not title:
        available = ", ".join(APPOINTABLE_TITLES.keys())
        return False, f"Такой должности нет. Доступно: {available}."

    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == target.id))
    if not membership:
        return False, "Сначала человек должен быть жителем города. Без прописки должность не выдаём."
    if membership.special_title == FOUNDER_TITLE:
        return False, "Основателя района нельзя понизить до должности. Это уже финальный босс."

    old_title = membership.civic_title
    membership.civic_title = title
    membership.influence += 4
    membership.reputation += 3
    city.xp += 10
    log(db, city.id, target.id, "appoint", f"{display_player(target)} назначен: {title}.")
    db.flush()
    if old_title and old_title != title:
        return True, f"{display_player(target)} снят с должности {old_title} и назначен: {title}."
    return True, f"{display_player(target)} назначен: {title}."


def clear_city_official(db: Session, city: City, target: Player) -> tuple[bool, str]:
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == target.id))
    if not membership or not membership.civic_title:
        return False, "У этого жителя нет должности. Снимать нечего, кроме напряжения."
    old = membership.civic_title
    membership.civic_title = None
    membership.reputation = max(-10, membership.reputation - 1)
    log(db, city.id, target.id, "dismiss", f"{display_player(target)} снят с должности {old}.")
    db.flush()
    return True, f"{display_player(target)} снят с должности {old}."


def find_city_player_by_username(db: Session, city: City, username: str) -> Player | None:
    clean = username.strip().lstrip("@").lower()
    if not clean:
        return None
    rows = db.execute(
        select(Player, Membership)
        .join(Membership, Membership.player_id == Player.id)
        .where(Membership.city_id == city.id)
    ).all()
    for player, _membership in rows:
        if player.username and player.username.lower() == clean:
            return player
    return None


def city_officials(db: Session, city: City) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Player, Membership)
        .join(Membership, Membership.player_id == Player.id)
        .where(Membership.city_id == city.id, Membership.civic_title.is_not(None))
        .order_by(desc(Membership.influence), desc(Membership.reputation))
    ).all()
    return [
        {
            "name": display_player(player),
            "title": membership.civic_title,
            "influence": membership.influence,
        }
        for player, membership in rows
    ]


def weekly_summary(db: Session, city: City) -> dict[str, Any]:
    since = utcnow() - timedelta(days=7)
    actions = db.scalar(
        select(func.count(ActionLog.id)).where(ActionLog.city_id == city.id, ActionLog.created_at >= since)
    ) or 0
    raids_won = db.scalar(
        select(func.count(ActionLog.id)).where(
            ActionLog.city_id == city.id,
            ActionLog.action == "raid_finished",
            ActionLog.created_at >= since,
        )
    ) or 0
    top = top_players(db, city, limit=5)
    richest = max(top, key=lambda item: item["coins"], default=None)
    suspect = None
    if top:
        rows = db.execute(
            select(Player, Membership)
            .join(Membership, Membership.player_id == Player.id)
            .where(Membership.city_id == city.id)
            .order_by(desc(Membership.convictions), desc(Player.coins))
            .limit(1)
        ).first()
        if rows:
            player, membership = rows
            suspect = {"name": display_player(player), "convictions": membership.convictions}
    return {
        "city": city_payload(db, city),
        "actions": int(actions),
        "raids_won": int(raids_won),
        "top": top,
        "richest": richest,
        "suspect": suspect,
        "trophies": get_city_trophies(city),
    }


def _alliance_pair(left_id: int, right_id: int) -> tuple[int, int]:
    return (left_id, right_id) if left_id < right_id else (right_id, left_id)


def register_city_referral(db: Session, invited_city: City, referrer_code: str | None) -> tuple[bool, str | None]:
    """Reward the city whose deep-link created a new group city.

    Telegram startgroup links pass a short payload into /start. We keep the
    reward one-time per invited city so people cannot farm by restarting bot.
    """
    code = (referrer_code or "").strip().upper().removeprefix("CITY_")
    if not code:
        return False, None
    referrer = db.scalar(select(City).where(City.invite_code == code))
    if not referrer:
        return False, "Реф-код города не найден. Сарафанка потеряла паспорт."
    if referrer.id == invited_city.id:
        return False, None
    existing = db.scalar(select(CityReferral).where(CityReferral.invited_city_id == invited_city.id))
    if existing:
        return False, None

    referral = CityReferral(
        referrer_city_id=referrer.id,
        invited_city_id=invited_city.id,
        invite_code=code,
        reward_given=1,
    )
    db.add(referral)
    referrer.treasury += 120
    referrer.xp += 80
    invited_city.treasury += 35
    invited_city.xp += 25
    trophy = award_trophy(referrer, "🌱 Основатель нового района")
    milestone_lines = award_referral_milestones(db, referrer)
    maybe_level_up(referrer)
    maybe_level_up(invited_city)
    log(db, referrer.id, None, "city_referral", f"По ссылке города добавили новый чат: {invited_city.name}. Награда: +120 в казну, трофей {trophy}.")
    log(db, invited_city.id, None, "city_referral_joined", f"Город пришёл по ссылке {referrer.name}. Бонус старта: +35 в казну.")
    db.flush()
    extra = f" Новые уровни: {'; '.join(milestone_lines)}." if milestone_lines else ""
    return True, f"Город пришёл по ссылке <b>{referrer.name}</b>. Бонус старта: +35 в казну. {referrer.name} получил трофей и +120 монет.{extra}"


def create_city_alliance(db: Session, city: City, target_code: str) -> tuple[bool, str, City | None]:
    code = (target_code or "").strip().upper().removeprefix("CITY_")
    target = db.scalar(select(City).where(City.invite_code == code))
    if not target:
        return False, "Город с таким кодом не найден.", None
    if target.id == city.id:
        return False, "Союз с самим собой — это уже одиночество с документами.", target
    left_id, right_id = _alliance_pair(city.id, target.id)
    existing = db.scalar(
        select(CityAlliance).where(
            CityAlliance.city_a_id == left_id,
            CityAlliance.city_b_id == right_id,
            CityAlliance.status == AllianceStatus.ACTIVE.value,
        )
    )
    if existing:
        return False, f"Союз с городом {target.name} уже действует.", target

    alliance = CityAlliance(city_a_id=left_id, city_b_id=right_id, status=AllianceStatus.ACTIVE.value)
    db.add(alliance)
    city.treasury += 35
    city.xp += 45
    target.treasury += 35
    target.xp += 45
    award_trophy(city, "🤝 Союзный договор")
    award_trophy(target, "🤝 Союзный договор")
    maybe_level_up(city)
    maybe_level_up(target)
    log(db, city.id, None, "alliance_created", f"Заключён союз с городом {target.name}.")
    log(db, target.id, None, "alliance_created", f"Заключён союз с городом {city.name}.")
    db.flush()
    return True, f"{city.name} и {target.name} заключили союз. Оба города получили +35 в казну, +45 XP и трофей.", target


def city_alliances(db: Session, city: City, limit: int = 10) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(CityAlliance)
        .where(
            CityAlliance.status == AllianceStatus.ACTIVE.value,
            (CityAlliance.city_a_id == city.id) | (CityAlliance.city_b_id == city.id),
        )
        .order_by(desc(CityAlliance.created_at))
        .limit(limit)
    ).all()
    result: list[dict[str, Any]] = []
    for alliance in rows:
        other_id = alliance.city_b_id if alliance.city_a_id == city.id else alliance.city_a_id
        other = db.get(City, other_id)
        if other:
            result.append({
                "id": alliance.id,
                "name": other.name,
                "title": other.title,
                "rank": city_rank(other),
                "level": other.level,
                "invite_code": other.invite_code,
                "created_at": alliance.created_at.isoformat(),
            })
    return result


def city_referral_count(db: Session, city_id: int) -> int:
    return db.scalar(select(func.count(CityReferral.id)).where(CityReferral.referrer_city_id == city_id)) or 0


def city_alliance_count(db: Session, city_id: int) -> int:
    return db.scalar(
        select(func.count(CityAlliance.id)).where(
            CityAlliance.status == AllianceStatus.ACTIVE.value,
            (CityAlliance.city_a_id == city_id) | (CityAlliance.city_b_id == city_id),
        )
    ) or 0


def admin_stats(db: Session) -> dict[str, Any]:
    since_day = utcnow() - timedelta(days=1)
    cities_total = db.scalar(select(func.count(City.id))) or 0
    players_total = db.scalar(select(func.count(Player.id))) or 0
    memberships_total = db.scalar(select(func.count(Membership.id))) or 0
    active_players_day = db.scalar(
        select(func.count(func.distinct(ActionLog.player_id))).where(ActionLog.player_id.is_not(None), ActionLog.created_at >= since_day)
    ) or 0
    actions_day = db.scalar(select(func.count(ActionLog.id)).where(ActionLog.created_at >= since_day)) or 0
    active_cities_day = db.scalar(select(func.count(func.distinct(ActionLog.city_id))).where(ActionLog.city_id.is_not(None), ActionLog.created_at >= since_day)) or 0
    new_cities_day = db.scalar(select(func.count(City.id)).where(City.created_at >= since_day)) or 0
    referrals_total = db.scalar(select(func.count(CityReferral.id))) or 0
    alliances_total = db.scalar(select(func.count(CityAlliance.id)).where(CityAlliance.status == AllianceStatus.ACTIVE.value)) or 0
    raids_active = db.scalar(select(func.count(War.id)).where(War.status == "active")) or 0
    raids_finished = db.scalar(select(func.count(War.id)).where(War.status == "finished")) or 0
    duels_active = db.scalar(select(func.count(Duel.id)).where(Duel.status == DuelStatus.ACTIVE.value)) or 0
    duels_finished = db.scalar(select(func.count(Duel.id)).where(Duel.status == DuelStatus.FINISHED.value)) or 0
    black_market_actions = db.scalar(select(func.count(ActionLog.id)).where(ActionLog.action == "black_market", ActionLog.created_at >= since_day)) or 0
    feedback_day = db.scalar(select(func.count(ActionLog.id)).where(ActionLog.action == "feedback", ActionLog.created_at >= since_day)) or 0
    stars_purchases_day = db.scalar(select(func.count(Purchase.id)).where(Purchase.status == PurchaseStatus.PAID.value, Purchase.created_at >= since_day)) or 0
    stars_total_day = db.scalar(select(func.coalesce(func.sum(Purchase.stars_amount), 0)).where(Purchase.status == PurchaseStatus.PAID.value, Purchase.created_at >= since_day)) or 0
    action_count = func.count(ActionLog.id)
    top_action_row = db.execute(
        select(ActionLog.action, action_count.label("n"))
        .where(ActionLog.created_at >= since_day)
        .group_by(ActionLog.action)
        .order_by(desc(action_count))
        .limit(1)
    ).first()
    top_city = top_cities(db, limit=1)
    return {
        "cities_total": int(cities_total),
        "players_total": int(players_total),
        "memberships_total": int(memberships_total),
        "active_players_day": int(active_players_day),
        "actions_day": int(actions_day),
        "active_cities_day": int(active_cities_day),
        "new_cities_day": int(new_cities_day),
        "referrals_total": int(referrals_total),
        "alliances_total": int(alliances_total),
        "raids_active": int(raids_active),
        "raids_finished": int(raids_finished),
        "duels_active": int(duels_active),
        "duels_finished": int(duels_finished),
        "black_market_actions": int(black_market_actions),
        "feedback_day": int(feedback_day),
        "stars_purchases_day": int(stars_purchases_day),
        "stars_total_day": int(stars_total_day or 0),
        "top_action": {"action": top_action_row[0], "count": int(top_action_row[1])} if top_action_row else None,
        "top_city": top_city[0] if top_city else None,
    }


def top_week_cities(db: Session, limit: int = 10) -> list[dict[str, Any]]:
    since = utcnow() - timedelta(days=7)
    action_count = func.count(ActionLog.id)
    rows = db.execute(
        select(City, action_count.label("actions"))
        .join(ActionLog, ActionLog.city_id == City.id)
        .where(ActionLog.created_at >= since)
        .group_by(City.id)
        .order_by(desc(action_count), desc(City.level), desc(City.treasury))
        .limit(limit)
    ).all()
    return [
        {
            "id": city.id,
            "name": city.name,
            "level": city.level,
            "rank": city_rank(city),
            "treasury": city.treasury,
            "actions": int(actions or 0),
            "population": city_population(db, city.id),
            "trophies_count": len(get_city_trophies(city)),
        }
        for city, actions in rows
    ]


def hall_of_fame_payload(db: Session) -> dict[str, Any]:
    first_cities = db.scalars(select(City).order_by(City.created_at).limit(10)).all()
    richest = db.scalars(select(City).order_by(desc(City.treasury), desc(City.level)).limit(10)).all()
    warlike_rows = db.execute(
        select(City, func.count(War.id).label("wars"))
        .join(War, (War.attacker_city_id == City.id) | (War.defender_city_id == City.id))
        .group_by(City.id)
        .order_by(desc(func.count(War.id)))
        .limit(10)
    ).all()
    ref_rows = db.execute(
        select(City, func.count(CityReferral.id).label("refs"))
        .join(CityReferral, CityReferral.referrer_city_id == City.id)
        .group_by(City.id)
        .order_by(desc(func.count(CityReferral.id)))
        .limit(10)
    ).all()
    return {
        "first": [{"name": c.name, "level": c.level, "rank": city_rank(c)} for c in first_cities],
        "richest": [{"name": c.name, "treasury": c.treasury, "level": c.level} for c in richest],
        "warlike": [{"name": c.name, "wars": int(n or 0), "level": c.level} for c, n in warlike_rows],
        "referrers": [{"name": c.name, "refs": int(n or 0), "level": c.level} for c, n in ref_rows],
    }


def submit_feedback(db: Session, city: City | None, player: Player | None, text: str) -> str:
    clean = " ".join((text or "").split())[:600]
    if not clean:
        return "📝 Пустой лист районная канцелярия не приняла."
    log(db, city.id if city else None, player.id if player else None, "feedback", clean)
    db.flush()
    return "📝 Записано. Районная канцелярия забрала бумагу."


def feedback_items(db: Session, limit: int = 10) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ActionLog)
        .where(ActionLog.action == "feedback")
        .order_by(desc(ActionLog.created_at))
        .limit(limit)
    ).all()
    result = []
    for item in rows:
        city = db.get(City, item.city_id) if item.city_id else None
        player = db.get(Player, item.player_id) if item.player_id else None
        result.append({
            "city": city.name if city else "личка",
            "player": display_player(player) if player else "неизвестно",
            "text": item.text,
            "created_at": item.created_at.isoformat(),
        })
    return result


def admin_chats_payload(db: Session, limit: int = 15) -> list[dict[str, Any]]:
    since = utcnow() - timedelta(days=1)
    activity_subq = (
        select(ActionLog.city_id, func.count(ActionLog.id).label("actions"))
        .where(ActionLog.created_at >= since, ActionLog.city_id.is_not(None))
        .group_by(ActionLog.city_id)
        .subquery()
    )
    rows = db.execute(
        select(City, func.coalesce(activity_subq.c.actions, 0))
        .outerjoin(activity_subq, activity_subq.c.city_id == City.id)
        .order_by(desc(func.coalesce(activity_subq.c.actions, 0)), desc(City.created_at))
        .limit(limit)
    ).all()
    return [
        {
            "id": city.id,
            "chat_id": city.chat_id,
            "name": city.name,
            "title": city.title,
            "level": city.level,
            "treasury": city.treasury,
            "actions_day": int(actions or 0),
            "population": city_population(db, city.id),
            "invite_code": city.invite_code,
        }
        for city, actions in rows
    ]


def admin_chat_payload(db: Session, code_or_id: str) -> dict[str, Any] | None:
    raw = (code_or_id or "").strip().upper().removeprefix("CITY_")
    city = None
    if raw.isdigit():
        city = db.get(City, int(raw))
    if not city and raw:
        city = db.scalar(select(City).where(City.invite_code == raw))
    if not city:
        return None
    return {
        "city": city_payload(db, city),
        "logs": recent_logs(db, city.id, limit=8),
        "feedback": [
            item for item in feedback_items(db, limit=20)
            if item["city"] == city.name
        ][:5],
    }


def top_cities(db: Session, limit: int = 10) -> list[dict[str, Any]]:
    population_subquery = (
        select(Membership.city_id, func.count(Membership.id).label("population"))
        .group_by(Membership.city_id)
        .subquery()
    )
    rows = db.execute(
        select(City, func.coalesce(population_subquery.c.population, 0))
        .outerjoin(population_subquery, population_subquery.c.city_id == City.id)
        .order_by(desc(City.level), desc(City.treasury), desc(City.xp))
        .limit(limit)
    ).all()
    return [
        {
            "id": city.id,
            "name": city.name,
            "title": city.title,
            "level": city.level,
            "treasury": city.treasury,
            "xp": city.xp,
            "population": int(population or 0),
            "rank": city_rank(city),
            "season": int(city.season_number or 1),
            "invite_code": city.invite_code,
            "trophies_count": len(get_city_trophies(city)),
            "alliances_count": city_alliance_count(db, city.id),
            "referrals_count": city_referral_count(db, city.id),
        }
        for city, population in rows
    ]


def player_title(player: Player, membership: Membership) -> str:
    jailed_until = _aware(membership.jailed_until)
    if jailed_until and utcnow() < jailed_until:
        return "🔒 В подвале"
    if membership.special_title == FOUNDER_TITLE:
        return "👑 Основатель района"
    if membership.civic_title:
        return membership.civic_title
    if player.role.startswith("Мэр"):
        return "👑 Мэр"
    if membership.influence >= 35:
        return "🏛 Батя района"
    if player.coins >= 250:
        return "💰 Местный олигарх"
    if membership.reputation >= 25:
        return "⭐ Народная легенда"
    if membership.influence >= 15:
        return "🧠 Серый кардинал"
    if player.xp >= 100:
        return "🔥 Трудоголик хаоса"
    if membership.reputation <= -5:
        return "🕳 Подозрительный тип"
    return "🏘 Житель"


def top_players(db: Session, city: City, limit: int = 10) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Player, Membership)
        .join(Membership, Membership.player_id == Player.id)
        .where(Membership.city_id == city.id)
        .order_by(desc(Membership.influence), desc(Player.xp), desc(Player.coins))
        .limit(limit)
    ).all()
    return [
        {
            "id": player.id,
            "telegram_user_id": player.telegram_user_id,
            "name": display_player(player),
            "role": player.role,
            "title": player_title(player, membership),
            "coins": player.coins,
            "xp": player.xp,
            "level": player_level(player.xp),
            "influence": membership.influence,
            "reputation": membership.reputation,
            "civic_title": membership.civic_title,
        }
        for player, membership in rows
    ]


def city_payload(db: Session, city: City) -> dict[str, Any]:
    buildings = get_city_buildings(city)
    building_names = [f"{BUILDINGS[key]['name']} ур.{level}" for key, level in buildings.items()]
    return {
        "id": city.id,
        "chat_id": city.chat_id,
        "title": city.title,
        "name": city.name,
        "rank": city_rank(city),
        "level": city.level,
        "xp": city.xp,
        "treasury": city.treasury,
        "threat": city.threat,
        "population": city_population(db, city.id),
        "power": city_power(db, city.id),
        "invite_code": city.invite_code,
        "buildings": building_names,
        "trophies": get_city_trophies(city),
        "alliances_count": city_alliance_count(db, city.id),
        "referrals_count": city_referral_count(db, city.id),
        "history_count": len(_safe_json_list(city.history_json)),
        "activity_mode": activity_mode_payload(city),
        "factions_count": sum(item["count"] for item in faction_counts(db, city)),
        "season": season_payload(city),
        "shop": get_city_shop(city),
        "premium": city_premium_payload(city),
        "created_at": city.created_at.isoformat(),
    }


def event_payload(event: CityEvent | None) -> dict[str, Any] | None:
    if not event:
        return None
    votes = json.loads(event.votes_json or "{}")
    counts = {"1": 0, "2": 0, "3": 0}
    for value in votes.values():
        counts[str(value)] = counts.get(str(value), 0) + 1
    return {
        "id": event.id,
        "title": event.title,
        "text": event.text,
        "options": [event.option_1, event.option_2, event.option_3],
        "votes": counts,
        "created_at": event.created_at.isoformat(),
    }


def log(db: Session, city_id: int | None, player_id: int | None, action: str, text: str) -> None:
    db.add(ActionLog(city_id=city_id, player_id=player_id, action=action, text=text))


def recent_logs(db: Session, city_id: int, limit: int = 20) -> list[dict[str, str]]:
    logs = db.scalars(select(ActionLog).where(ActionLog.city_id == city_id).order_by(desc(ActionLog.created_at)).limit(limit)).all()
    return [
        {"action": item.action, "text": item.text, "created_at": item.created_at.isoformat()}
        for item in logs
    ]


def _city_players(db: Session, city: City, limit: int = 20) -> list[Player]:
    rows = db.execute(
        select(Player, Membership)
        .join(Membership, Membership.player_id == Player.id)
        .where(Membership.city_id == city.id)
        .order_by(desc(Membership.influence), desc(Player.xp), desc(Player.coins))
        .limit(limit)
    ).all()
    return [player for player, _membership in rows]


def create_drama_event(db: Session, city: City, force: bool = True) -> CityEvent | None:
    active = get_active_event(db, city)
    if active and not force:
        return active
    if active and force:
        active.resolved_at = utcnow()
        log(db, city.id, None, "event_replaced", f"Старое событие закрыто ради новой драмы: {active.title}")

    players = _city_players(db, city, limit=10)
    if len(players) < 2:
        return None

    picked = random.sample(players, k=min(3, len(players)))
    while len(picked) < 3:
        picked.append(picked[-1])
    names = [display_player(player) for player in picked]
    template = random.choice(DRAMA_TEMPLATES)
    event = CityEvent(
        city_id=city.id,
        event_key="drama",
        title=template["title"],
        text=template["text"].format(a=names[0], b=names[1], c=names[2]),
        option_1=template["options"][0],
        option_2=template["options"][1],
        option_3=template["options"][2],
        votes_json="{}",
    )
    db.add(event)
    db.flush()
    city.last_event_at = utcnow()
    log(db, city.id, None, "drama", f"Запущена драма: {event.title}")
    return event


def create_mayor_election(db: Session, city: City) -> CityEvent | None:
    active = get_active_event(db, city)
    if active:
        if active.event_key.startswith("mayor:"):
            return active
        return None

    players = _city_players(db, city, limit=3)
    if len(players) < 2:
        return None

    while len(players) < 3:
        players.append(players[-1])
    event = CityEvent(
        city_id=city.id,
        event_key="mayor:" + ",".join(str(player.id) for player in players[:3]),
        title="Выборы мэра Чатограда",
        text=(
            "Город созрел до политики. Три кандидата обещают порядок, деньги и немного хаоса. "
            "Голосуйте, пока кандидаты не начали обещать бесплатный Wi‑Fi в подвале."
        ),
        option_1=f"Выбрать {display_player(players[0])}",
        option_2=f"Выбрать {display_player(players[1])}",
        option_3=f"Выбрать {display_player(players[2])}",
        votes_json="{}",
    )
    db.add(event)
    db.flush()
    city.last_event_at = utcnow()
    log(db, city.id, None, "election", "В городе начались выборы мэра.")
    return event


def _today_start() -> datetime:
    now = utcnow()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def quest_payload(db: Session, city: City) -> dict[str, Any]:
    since = _today_start()
    progress = db.scalar(
        select(func.count(ActionLog.id)).where(
            ActionLog.city_id == city.id,
            ActionLog.action == "quest",
            ActionLog.created_at >= since,
        )
    ) or 0
    population = city_population(db, city.id)
    goal = max(5, population * 2 + city.level)
    return {
        "title": "Общий квест дня",
        "text": "Соберите людей на районную работу: каждый житель может помочь один раз в день.",
        "progress": int(progress),
        "goal": int(goal),
        "reward": 30 + city.level * 5,
        "completed": int(progress) >= int(goal),
    }


def help_city_quest(db: Session, city: City, player: Player) -> tuple[dict[str, Any], str]:
    since = _today_start()
    already = db.scalar(
        select(ActionLog.id).where(
            ActionLog.city_id == city.id,
            ActionLog.player_id == player.id,
            ActionLog.action == "quest",
            ActionLog.created_at >= since,
        )
    )
    if already:
        return quest_payload(db, city), "Ты уже помогал общему квесту сегодня. Не геройствуй, у нас тут экономика, а не марафон."

    before_complete = quest_payload(db, city)["completed"]
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    if membership:
        membership.influence += 1
        membership.reputation += 2
    gain_xp = random.randint(7, 14)
    gain_treasury = random.randint(3, 8)
    city.xp += gain_xp
    city.treasury += gain_treasury
    player.xp += 4
    player.coins += 3
    log(db, city.id, player.id, "quest", f"{display_player(player)} помог общему квесту дня.")
    db.flush()

    payload = quest_payload(db, city)
    if payload["completed"] and not before_complete:
        city.treasury += payload["reward"]
        city.xp += 35
        maybe_level_up(city)
        log(db, city.id, None, "quest_complete", f"Город выполнил общий квест и получил +{payload['reward']} к казне.")
        db.flush()
        payload = quest_payload(db, city)
        return payload, f"Квест закрыт! Город получил +{payload['reward']} монет в казну и +35 опыта. Вот это уже не чат, а профсоюз хаоса."

    maybe_level_up(city)
    return payload, f"Ты помог квесту: +{gain_treasury} в казну, +{gain_xp} опыта городу, +3 монеты тебе."


def build_newspaper(db: Session, city: City) -> dict[str, Any]:
    top = top_players(db, city, limit=5)
    logs = recent_logs(db, city.id, limit=6)
    event = get_active_event(db, city)
    quest = quest_payload(db, city)
    hero = top[0] if top else None
    suspect = random.choice(top) if top else None
    return {
        "city": city_payload(db, city),
        "top": top,
        "logs": logs,
        "event": event_payload(event),
        "quest": quest,
        "hero": hero,
        "suspect": suspect,
    }


def city_action_cooldown(db: Session, city: City, action: str, minutes: int) -> tuple[bool, int]:
    """Return (allowed, minutes_left) for noisy city actions."""
    since = utcnow() - timedelta(minutes=minutes)
    row = db.scalar(
        select(ActionLog)
        .where(ActionLog.city_id == city.id, ActionLog.action == action, ActionLog.created_at >= since)
        .order_by(desc(ActionLog.created_at))
        .limit(1)
    )
    if not row:
        return True, 0
    created = _aware(row.created_at) or utcnow()
    left = int(((created + timedelta(minutes=minutes)) - utcnow()).total_seconds() // 60) + 1
    return False, max(1, left)


def is_city_founder(db: Session, city: City, player: Player) -> bool:
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    return bool(membership and membership.special_title == FOUNDER_TITLE and city.owner_telegram_user_id == player.telegram_user_id)


def black_market_payload(city: City) -> dict[str, Any]:
    return {"items": [{"key": key, "name": spec["name"], "cost": spec["cost"], "text": spec["text"]} for key, spec in BLACK_MARKET_ITEMS.items()]}


def buy_black_market_item(db: Session, city: City, player: Player, key: str) -> tuple[bool, str, dict[str, Any], CityEvent | None]:
    key = (key or "").strip().lower()
    spec = BLACK_MARKET_ITEMS.get(key)
    if not spec:
        return False, "Такого товара на чёрном рынке нет.", black_market_payload(city), None

    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    if not membership:
        return False, "Сначала вступи в город. Чёрный рынок чужаков не любит.", black_market_payload(city), None

    cost = int(spec["cost"])
    if player.coins < cost:
        return False, f"Нужно {cost} монет. У тебя {player.coins}.", black_market_payload(city), None

    player.coins -= cost
    city.xp += 5
    event: CityEvent | None = None

    if key == "fake_rep":
        membership.reputation += 8
        membership.influence += 1
        text = f"{display_player(player)} купил репутацию. Теперь район уважает его чуть подозрительнее."
    elif key == "judge_bribe":
        if membership.convictions > 0:
            membership.convictions -= 1
            membership.reputation += 2
            text = f"{display_player(player)} занёс конверт, и одна судимость исчезла из папки."
        else:
            membership.reputation += 1
            text = f"{display_player(player)} занёс конверт заранее. Судимости нет, но связи появились."
    elif key == "hide_coins":
        stash = max(5, cost // 3)
        city.treasury += stash
        membership.reputation -= 1
        text = f"{display_player(player)} спрятал монеты. Часть внезапно всплыла в казне: +{stash}."
    elif key == "rumor_bomb":
        event = create_rumor_event(db, city, force=True)
        membership.reputation -= 1
        text = f"{display_player(player)} запустил слух. Район получил новую тему для подозрений."
    else:
        text = f"{display_player(player)} купил: {spec['name']}."

    maybe_level_up(city)
    log(db, city.id, player.id, "black_market", text)
    db.flush()
    return True, text, black_market_payload(city), event


def create_rumor_event(db: Session, city: City, force: bool = True) -> CityEvent | None:
    active = get_active_event(db, city)
    if active and not force:
        return active
    if active and force:
        active.resolved_at = utcnow()
        log(db, city.id, None, "event_replaced", f"Старое событие закрыто ради слуха: {active.title}")

    players = _city_players(db, city, limit=10)
    if len(players) < 2:
        return None
    picked = random.sample(players, k=2)
    template = random.choice(RUMOR_TEMPLATES)
    event = CityEvent(
        city_id=city.id,
        event_key="rumor",
        title=template["title"],
        text=template["text"].format(a=display_player(picked[0]), b=display_player(picked[1])),
        option_1=template["options"][0],
        option_2=template["options"][1],
        option_3=template["options"][2],
        votes_json="{}",
    )
    db.add(event)
    db.flush()
    city.last_event_at = utcnow()
    log(db, city.id, None, "rumor", f"Запущен слух: {event.title}")
    db.flush()
    return event


def create_duel_challenge(db: Session, city: City, challenger: Player, target: Player, stake: int = 10) -> tuple[Duel | None, str]:
    stake = max(1, min(int(stake or 10), 500))
    if challenger.id == target.id:
        return None, "Сам с собой дуэль? Это уже внутренний конфликт, бот тут бессилен."
    if challenger.coins < stake:
        return None, f"У тебя нет {stake} монет на ставку."
    target_membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == target.id))
    challenger_membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == challenger.id))
    if not target_membership or not challenger_membership:
        return None, "Оба участника должны быть жителями города."
    active = db.scalar(
        select(Duel)
        .where(
            Duel.city_id == city.id,
            Duel.status == DuelStatus.ACTIVE.value,
            ((Duel.challenger_player_id == challenger.id) & (Duel.target_player_id == target.id)) |
            ((Duel.challenger_player_id == target.id) & (Duel.target_player_id == challenger.id)),
        )
        .order_by(desc(Duel.created_at))
    )
    if active:
        return active, "Дуэль между этими жителями уже висит. Сначала решите старую, гладиаторы."
    duel = Duel(city_id=city.id, challenger_player_id=challenger.id, target_player_id=target.id, stake=stake, status=DuelStatus.ACTIVE.value)
    db.add(duel)
    city.xp += 3
    grant_achievement(db, city, challenger, "duelist")
    log(db, city.id, challenger.id, "duel_created", f"{display_player(challenger)} вызвал {display_player(target)} на дуэль. Ставка: {stake}.")
    db.flush()
    return duel, f"{display_player(challenger)} вызвал {display_player(target)} на дуэль. Ставка: {stake} монет."


def resolve_duel(db: Session, city: City, duel_id: int, accepter: Player) -> tuple[Duel | None, DuelResult]:
    duel = db.get(Duel, duel_id)
    if not duel or duel.city_id != city.id or duel.status != DuelStatus.ACTIVE.value:
        return None, DuelResult("Дуэль не найдена или уже закончилась.", None, None, 0)
    if duel.target_player_id != accepter.id:
        return duel, DuelResult("Принять дуэль может только тот, кого вызвали. Не лезь под чужой меч, герой.", None, None, int(duel.stake))

    challenger = db.get(Player, duel.challenger_player_id)
    target = db.get(Player, duel.target_player_id)
    if not challenger or not target:
        duel.status = DuelStatus.DECLINED.value
        duel.resolved_at = utcnow()
        return duel, DuelResult("Один из дуэлянтов исчез. Победила бюрократия.", None, None, int(duel.stake))

    stake = int(duel.stake or 10)
    if challenger.coins < stake or target.coins < stake:
        duel.status = DuelStatus.DECLINED.value
        duel.resolved_at = utcnow()
        return duel, DuelResult("У кого-то не хватило монет на ставку. Дуэль распалась как стартап без бюджета.", None, None, stake)

    ch_mem = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == challenger.id))
    ta_mem = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == target.id))
    ch_score = challenger.xp + (ch_mem.influence if ch_mem else 0) * 7 + (ch_mem.reputation if ch_mem else 0) * 3 + random.randint(1, 80)
    ta_score = target.xp + (ta_mem.influence if ta_mem else 0) * 7 + (ta_mem.reputation if ta_mem else 0) * 3 + random.randint(1, 80)
    winner, loser, win_mem, lose_mem = (challenger, target, ch_mem, ta_mem) if ch_score >= ta_score else (target, challenger, ta_mem, ch_mem)

    challenger.coins -= stake
    target.coins -= stake
    winner.coins += stake * 2
    winner.xp += 12
    loser.xp += 4
    if win_mem:
        win_mem.reputation += 5
        win_mem.influence += 2
    if lose_mem:
        lose_mem.reputation = max(-30, lose_mem.reputation - 2)
    city.xp += 14
    maybe_level_up(city)

    duel.status = DuelStatus.FINISHED.value
    duel.winner_player_id = winner.id
    duel.resolved_at = utcnow()
    text = f"{display_player(winner)} победил {display_player(loser)} в дуэли и забрал банк {stake * 2} монет."
    log(db, city.id, winner.id, "duel_finished", text)
    grant_achievement(db, city, winner, "duelist")
    grant_achievement(db, city, loser, "duelist")
    db.flush()
    return duel, DuelResult(text, display_player(winner), display_player(loser), stake, int(ch_score), int(ta_score))


def founder_panel_payload(db: Session, city: City) -> dict[str, Any]:
    return {
        "city": city_payload(db, city),
        "officials": city_officials(db, city),
        "recent_logs": recent_logs(db, city.id, limit=5),
        "activity_mode": activity_mode_payload(city),
        "ai_leader": ai_leader_payload(city),
    }


def rename_city(db: Session, city: City, new_name: str) -> tuple[bool, str]:
    clean = " ".join((new_name or "").strip().split())[:40]
    if len(clean) < 3:
        return False, "Название слишком короткое. Район не может называться просто ‘А’."
    old = city.name
    city.name = clean
    city.xp += 5
    log(db, city.id, None, "rename_city", f"Город переименован: {old} -> {clean}.")
    db.flush()
    return True, f"Город переименован: {old} → {clean}."


def reset_city_progress(db: Session, city: City) -> tuple[bool, str]:
    """Soft reset for chat owner: keep citizens, owner and invite code, wipe game progress."""
    # Finish active events and raids connected with the city.
    for event in db.scalars(select(CityEvent).where(CityEvent.city_id == city.id, CityEvent.resolved_at.is_(None))).all():
        event.resolved_at = utcnow()
    for war in db.scalars(
        select(War).where(
            War.status == "active",
            (War.attacker_city_id == city.id) | (War.defender_city_id == city.id),
        )
    ).all():
        war.status = "finished"
        war.finished_at = utcnow()

    city.level = 1
    city.xp = 0
    city.treasury = 25
    city.threat = random.randint(3, 11)
    city.buildings_json = "{}"
    city.shop_json = "{}"
    city.history_json = "[]"
    city.season_number = 1
    city.season_started_at = utcnow()
    city.last_daily_summary_at = None
    city.last_event_at = None
    city.activity_mode = "normal"
    # Keep launch/early trophies so first-wave cities don't lose their badge.
    keep = [item for item in get_city_trophies(city) if item == EARLY_CITY_TROPHY]
    set_city_trophies(city, keep)

    memberships = db.scalars(select(Membership).where(Membership.city_id == city.id)).all()
    for membership in memberships:
        membership.influence = 12 if membership.special_title == FOUNDER_TITLE else 1
        membership.reputation = 15 if membership.special_title == FOUNDER_TITLE else 0
        membership.civic_title = None
        membership.faction = None
        membership.inventory_json = "{}"
        membership.achievements_json = "[]"
        membership.jailed_until = None
        membership.convictions = 0
        membership.last_steal_at = None
        membership.last_revolt_at = None
        membership.last_action_at = None

    add_city_history(city, "Город был мягко сброшен основателем. Старый хаос ушёл в архив мусорки.", "🧹")
    log(db, city.id, None, "reset_city", "Город сброшен основателем.")
    db.flush()
    return True, "Город сброшен. Жители остались, прогресс начался заново."


def ai_leader_payload(city: City) -> dict[str, Any]:
    settings = get_settings()
    enabled = bool(settings.ai_enabled)
    return {
        "enabled": enabled,
        "provider": settings.ai_provider,
        "model": settings.ai_model or "не выбран",
        "daily_limit": settings.ai_daily_limit_per_chat,
        "fallback_line": random.choice(AI_LEADER_FALLBACKS),
        "status": "включён" if enabled else "выключен",
    }


def city_launch_payload(db: Session, city: City) -> dict[str, Any]:
    return {
        "city": city_payload(db, city),
        "early_trophy": EARLY_CITY_TROPHY if EARLY_CITY_TROPHY in get_city_trophies(city) else None,
        "first_event_available": get_active_event(db, city) is None,
    }


# ---- v1.0: factions, revolts, thefts, items, history ----


def _safe_json_dict(raw: str | None) -> dict[str, int]:
    try:
        data = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in data.items():
        try:
            amount = int(value)
        except (TypeError, ValueError):
            continue
        if amount > 0:
            out[str(key)] = amount
    return out


def _safe_json_list(raw: str | None) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def get_inventory(membership: Membership | None) -> dict[str, int]:
    if not membership:
        return {}
    data = _safe_json_dict(membership.inventory_json)
    return {key: value for key, value in data.items() if key in ITEMS}


def set_inventory(membership: Membership, inventory: dict[str, int]) -> None:
    clean = {key: int(value) for key, value in inventory.items() if key in ITEMS and int(value) > 0}
    membership.inventory_json = json.dumps(clean, ensure_ascii=False, sort_keys=True)


def give_item(membership: Membership, key: str, amount: int = 1) -> bool:
    if key not in ITEMS:
        return False
    inventory = get_inventory(membership)
    inventory[key] = inventory.get(key, 0) + max(1, int(amount))
    set_inventory(membership, inventory)
    return True


def consume_item(membership: Membership, key: str) -> bool:
    inventory = get_inventory(membership)
    if inventory.get(key, 0) <= 0:
        return False
    inventory[key] -= 1
    set_inventory(membership, inventory)
    return True


def add_city_history(city: City, text: str, icon: str = "📜") -> None:
    history = _safe_json_list(city.history_json)
    entry = {"at": utcnow().isoformat(), "icon": icon, "text": str(text)[:180]}
    history.append(entry)
    city.history_json = json.dumps(history[-35:], ensure_ascii=False)


def city_history_payload(city: City, limit: int = 12) -> dict[str, Any]:
    history = _safe_json_list(city.history_json)
    return {"city": city.name, "items": list(reversed(history[-limit:]))}


def faction_counts(db: Session, city: City) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Membership.faction, func.count(Membership.id))
        .where(Membership.city_id == city.id, Membership.faction.is_not(None))
        .group_by(Membership.faction)
    ).all()
    counts = {str(key): int(value) for key, value in rows if key}
    return [
        {"key": key, "name": spec["name"], "bonus": spec["bonus"], "count": counts.get(key, 0)}
        for key, spec in FACTIONS.items()
    ]


def faction_payload(db: Session, city: City, player: Player | None = None) -> dict[str, Any]:
    membership = None
    if player:
        membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    return {
        "city": city.name,
        "current": membership.faction if membership else None,
        "factions": faction_counts(db, city),
    }


def join_faction(db: Session, city: City, player: Player, key: str) -> tuple[bool, str, dict[str, Any]]:
    key = (key or "").strip().lower()
    if key not in FACTIONS:
        return False, "Такой фракции нет. Подъездная геополитика не принимает самодеятельность.", faction_payload(db, city, player)
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    if not membership:
        return False, "Сначала вступи в город.", faction_payload(db, city, player)
    if membership.faction == key:
        return False, f"Ты уже во фракции {FACTIONS[key]['name']}.", faction_payload(db, city, player)
    old = membership.faction
    membership.faction = key
    membership.reputation += 2
    membership.influence += 1
    city.xp += 8
    maybe_level_up(city)
    text = f"{display_player(player)} вступил во фракцию {FACTIONS[key]['name']}."
    if old and old in FACTIONS:
        text = f"{display_player(player)} перешёл из {FACTIONS[old]['name']} во фракцию {FACTIONS[key]['name']}."
    log(db, city.id, player.id, "faction_join", text)
    add_city_history(city, text, "🧱")
    db.flush()
    return True, text, faction_payload(db, city, player)


def inventory_payload(db: Session, city: City, player: Player) -> dict[str, Any]:
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    inventory = get_inventory(membership)
    items = [
        {"key": key, "name": ITEMS[key]["name"], "text": ITEMS[key]["text"], "count": count}
        for key, count in inventory.items()
        if key in ITEMS and count > 0
    ]
    return {"items": items, "empty": not items, "coins": player.coins}


def buy_item(db: Session, city: City, player: Player, key: str) -> tuple[bool, str, dict[str, Any]]:
    prices = {"lockpick": 45, "immunity": 70, "compromat": 55, "smoke": 40, "fake_crown": 65}
    key = (key or "").strip().lower()
    if key not in ITEMS:
        return False, "Такого предмета нет.", inventory_payload(db, city, player)
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    if not membership:
        return False, "Сначала вступи в город.", inventory_payload(db, city, player)
    cost = prices.get(key, 50)
    if player.coins < cost:
        return False, f"Нужно {cost} монет. У тебя {player.coins}.", inventory_payload(db, city, player)
    player.coins -= cost
    give_item(membership, key)
    membership.reputation += 1 if key != "compromat" else -1
    city.xp += 4
    text = f"{display_player(player)} купил предмет: {ITEMS[key]['name']}."
    log(db, city.id, player.id, "item_buy", text)
    grant_achievement(db, city, player, "items")
    db.flush()
    return True, text, inventory_payload(db, city, player)


def use_item(db: Session, city: City, player: Player, key: str) -> tuple[bool, str, dict[str, Any]]:
    key = (key or "").strip().lower()
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    if not membership:
        return False, "Сначала вступи в город.", inventory_payload(db, city, player)
    if key not in ITEMS:
        return False, "Такого предмета нет.", inventory_payload(db, city, player)
    if not consume_item(membership, key):
        return False, "У тебя нет такого предмета.", inventory_payload(db, city, player)

    text = f"{display_player(player)} использовал {ITEMS[key]['name']}."
    if key == "lockpick":
        jailed = _aware(membership.jailed_until)
        if jailed and utcnow() < jailed:
            membership.jailed_until = None
            membership.reputation += 3
            text = f"{display_player(player)} открыл подвал ключом и вышел красиво."
        else:
            membership.reputation += 1
            text = f"{display_player(player)} покрутил ключом от подвала. Сейчас не пригодился, но вид солидный."
    elif key == "immunity":
        membership.reputation += 4
        membership.influence += 1
        text = f"{display_player(player)} активировал иммунитет суда. Район делает вид, что всё законно."
    elif key == "compromat":
        victims = [p for p in _city_players(db, city, limit=20) if p.id != player.id]
        if victims:
            victim = random.choice(victims)
            victim_mem = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == victim.id))
            if victim_mem:
                victim_mem.reputation = max(-50, victim_mem.reputation - 7)
            text = f"{display_player(player)} слил компромат на {display_player(victim)}. Репутация пошатнулась."
        else:
            text = f"{display_player(player)} хотел слить компромат, но в районе слишком пусто."
    elif key == "smoke":
        membership.reputation += 1
        membership.influence += 1
        text = f"{display_player(player)} задымил район. Следующий мутный движ будет выглядеть убедительнее."
    elif key == "fake_crown":
        membership.influence += 3
        membership.reputation -= 1
        membership.civic_title = "👑 Фальшивый принц"
        text = f"{display_player(player)} надел фальшивую корону. Никто не поверил, но влияние выросло."
    log(db, city.id, player.id, "item_use", text)
    add_city_history(city, text, "🎒")
    db.flush()
    return True, text, inventory_payload(db, city, player)


def attempt_escape(db: Session, city: City, player: Player) -> tuple[bool, str, dict[str, Any]]:
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    if not membership:
        return False, "Сначала вступи в город.", inventory_payload(db, city, player)
    jailed = _aware(membership.jailed_until)
    if not jailed or utcnow() >= jailed:
        return False, "Ты не в подвале. Бежать неоткуда, герой.", inventory_payload(db, city, player)
    chance = 35 + (8 if membership.faction == "rebels" else 0) + (10 if get_inventory(membership).get("lockpick", 0) else 0)
    if random.randint(1, 100) <= chance:
        if get_inventory(membership).get("lockpick", 0):
            consume_item(membership, "lockpick")
        membership.jailed_until = None
        membership.reputation += 5
        membership.civic_title = "🕳 Беглец района"
        text = f"{display_player(player)} сбежал из подвала и получил титул Беглец района."
        add_city_history(city, text, "🕳")
        grant_achievement(db, city, player, "escape")
        ok = True
    else:
        membership.jailed_until = jailed + timedelta(minutes=45)
        membership.reputation -= 2
        text = f"{display_player(player)} попытался сбежать, но застрял в легенде. Подвал продлён на 45 минут."
        ok = False
    log(db, city.id, player.id, "escape", text)
    db.flush()
    return ok, text, inventory_payload(db, city, player)


def steal_treasury(db: Session, city: City, player: Player) -> tuple[bool, str]:
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    if not membership:
        return False, "Сначала вступи в город. Казна чужаков не обслуживает."
    now = utcnow()
    last = _aware(membership.last_steal_at)
    if last and now < last + timedelta(hours=6):
        left = int(((last + timedelta(hours=6)) - now).total_seconds() // 60) + 1
        return False, f"Ограбление уже было. Следующая попытка через {left} мин."
    if city.treasury < 10:
        return False, "Казна слишком пустая. Даже вор посмотрел и ушёл."

    membership.last_steal_at = now
    buildings = get_city_buildings(city)
    police = buildings.get("police", 0)
    bank = buildings.get("bank", 0)
    inventory = get_inventory(membership)
    chance = 38 + membership.reputation // 4 + (12 if membership.faction == "mafia" else 0) + (10 if inventory.get("smoke", 0) else 0) - police * 7 - bank * 4
    chance = max(10, min(75, chance))
    amount = max(5, min(city.treasury // 3, random.randint(8, 25 + city.level * 3)))
    if random.randint(1, 100) <= chance:
        if inventory.get("smoke", 0):
            consume_item(membership, "smoke")
        city.treasury -= amount
        player.coins += amount
        membership.reputation -= 3
        membership.influence += 1
        text = f"{display_player(player)} вынес из казны {amount} монет и сделал вид, что это аудит."
        ok = True
    else:
        fine = min(player.coins, max(5, amount // 2))
        player.coins -= fine
        city.treasury += fine
        membership.reputation -= 6
        membership.convictions += 1
        membership.jailed_until = now + timedelta(hours=2)
        text = f"{display_player(player)} попался на попытке ограбить казну. Штраф {fine}, подвал на 2 часа."
        ok = False
    city.xp += 8
    maybe_level_up(city)
    log(db, city.id, player.id, "steal", text)
    grant_achievement(db, city, player, "thief")
    add_city_history(city, text, "💰")
    db.flush()
    return ok, text


def create_revolt_event(db: Session, city: City, player: Player | None = None, force: bool = True) -> tuple[CityEvent | None, str]:
    if player:
        membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
        if membership:
            last = _aware(membership.last_revolt_at)
            if last and utcnow() < last + timedelta(hours=8):
                left = int(((last + timedelta(hours=8)) - utcnow()).total_seconds() // 60) + 1
                return None, f"Ты уже мутил бунт. Следующий через {left} мин."
            membership.last_revolt_at = utcnow()
    active = get_active_event(db, city)
    if active and not force:
        return active, "В городе уже есть активное событие."
    if active and force:
        active.resolved_at = utcnow()
    players = _city_players(db, city, limit=10)
    mayor = None
    for p in players:
        m = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == p.id))
        if m and m.civic_title and "Мэр" in m.civic_title:
            mayor = p
            break
    target = display_player(mayor) if mayor else "действующая власть"
    starter = display_player(player) if player else "народ"
    event = CityEvent(
        city_id=city.id,
        event_key="revolt",
        title="Бунт у мэрии",
        text=f"{starter} раскачивает район. Цель: {target}. Народ требует решить, кто тут главный.",
        option_1="Свергнуть власть",
        option_2="Защитить порядок",
        option_3="Превратить в праздник",
        votes_json="{}",
    )
    db.add(event)
    city.threat += 2
    city.xp += 6
    log(db, city.id, player.id if player else None, "revolt", f"В городе начался бунт против власти.")
    if player:
        grant_achievement(db, city, player, "rebel")
    add_city_history(city, f"Начался бунт против власти. Инициатор: {starter}.", "🔥")
    db.flush()
    return event, "Бунт начался. Район выбирает судьбу власти."


def maybe_legendary_event(db: Session, city: City) -> str | None:
    # Cheap and rare: call only after significant manual actions.
    if random.random() > 0.025:
        return None
    text = random.choice(LEGENDARY_EVENTS)
    city.xp += 20
    city.treasury += random.randint(5, 25)
    trophy = award_trophy(city, "🌟 Легенда района")
    add_city_history(city, f"{text} Трофей: {trophy}", "🌟")
    log(db, city.id, None, "legendary", text)
    db.flush()
    return text


def _safe_json_str_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    result: list[str] = []
    for item in data:
        if isinstance(item, str) and item in ACHIEVEMENTS and item not in result:
            result.append(item)
    return result[:80]


def get_achievements(membership: Membership | None) -> list[str]:
    return _safe_json_str_list(membership.achievements_json if membership else "[]")


def set_achievements(membership: Membership, keys: list[str]) -> None:
    clean: list[str] = []
    for key in keys:
        if key in ACHIEVEMENTS and key not in clean:
            clean.append(key)
    membership.achievements_json = json.dumps(clean[:80], ensure_ascii=False)


def grant_achievement(db: Session, city: City, player: Player, key: str) -> bool:
    if key not in ACHIEVEMENTS:
        return False
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    if not membership:
        return False
    owned = get_achievements(membership)
    if key in owned:
        return False
    owned.insert(0, key)
    set_achievements(membership, owned)
    membership.reputation += 2
    membership.influence += 1
    city.xp += 5
    spec = ACHIEVEMENTS[key]
    text = f"{display_player(player)} получил достижение: {spec['name']}."
    log(db, city.id, player.id, "achievement", text)
    add_city_history(city, text, "🏆")
    return True


def refresh_player_achievements(db: Session, city: City, player: Player) -> list[str]:
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    if not membership:
        return []
    new_keys: list[str] = []
    checks = [
        ("first_steps", True),
        ("founder", membership.special_title == FOUNDER_TITLE),
        ("worker", player.xp >= 35),
        ("rich_100", player.coins >= 100),
        ("rep_20", membership.reputation >= 20),
        ("convict", membership.convictions >= 1),
        ("faction", bool(membership.faction)),
        ("items", bool(get_inventory(membership))),
        ("escape", membership.civic_title == "🕳 Беглец района"),
    ]
    for key, condition in checks:
        if condition and grant_achievement(db, city, player, key):
            new_keys.append(key)
    db.flush()
    return new_keys


def achievement_payload(db: Session, city: City, player: Player) -> dict[str, Any]:
    refresh_player_achievements(db, city, player)
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    owned = get_achievements(membership)
    return {
        "owned_count": len(owned),
        "total_count": len(ACHIEVEMENTS),
        "items": [
            {"key": key, "name": ACHIEVEMENTS[key]["name"], "text": ACHIEVEMENTS[key]["text"]}
            for key in owned if key in ACHIEVEMENTS
        ],
        "locked": [
            {"key": key, "name": spec["name"], "text": spec["text"]}
            for key, spec in ACHIEVEMENTS.items() if key not in owned
        ],
    }


def activity_mode_payload(city: City) -> dict[str, Any]:
    key = city.activity_mode if city.activity_mode in ACTIVITY_MODES else "normal"
    spec = ACTIVITY_MODES[key]
    return {"key": key, "name": spec["name"], "text": spec["text"], "hours": spec["hours"], "items": ACTIVITY_MODES}


def set_city_activity_mode(db: Session, city: City, mode: str) -> tuple[bool, str, dict[str, Any]]:
    mode = (mode or "").strip().lower()
    if mode not in ACTIVITY_MODES:
        return False, "Такого режима нет.", activity_mode_payload(city)
    city.activity_mode = mode
    log(db, city.id, None, "activity_mode", f"Режим активности изменён: {ACTIVITY_MODES[mode]['name']}.")
    db.flush()
    return True, f"Режим активности: {ACTIVITY_MODES[mode]['name']}.", activity_mode_payload(city)


def auto_event_due(city: City) -> bool:
    if city.status != CityStatus.ACTIVE.value:
        return False
    mode = city.activity_mode if city.activity_mode in ACTIVITY_MODES else "normal"
    hours = int(ACTIVITY_MODES[mode]["hours"])
    last_event = _aware(city.last_event_at)
    return not last_event or utcnow() >= last_event + timedelta(hours=hours)


def daily_summary_payload(db: Session, city: City) -> dict[str, Any]:
    since = utcnow() - timedelta(days=1)
    logs = db.scalars(
        select(ActionLog)
        .where(ActionLog.city_id == city.id, ActionLog.created_at >= since)
        .order_by(desc(ActionLog.created_at))
        .limit(10)
    ).all()
    top = top_players(db, city, limit=5)
    rich_row = db.execute(
        select(Player, Membership)
        .join(Membership, Membership.player_id == Player.id)
        .where(Membership.city_id == city.id)
        .order_by(desc(Player.coins))
        .limit(1)
    ).first()
    suspect_row = db.execute(
        select(Player, Membership)
        .join(Membership, Membership.player_id == Player.id)
        .where(Membership.city_id == city.id)
        .order_by(desc(Membership.convictions), desc(Membership.reputation))
        .limit(1)
    ).first()
    action_count = func.count(ActionLog.id)
    top_action_rows = db.execute(
        select(ActionLog.action, action_count.label("n"))
        .where(ActionLog.city_id == city.id, ActionLog.created_at >= since)
        .group_by(ActionLog.action)
        .order_by(desc(action_count))
        .limit(3)
    ).all()
    city.last_daily_summary_at = utcnow()
    return {
        "city": city_payload(db, city),
        "top": top,
        "richest": {"name": display_player(rich_row[0]), "coins": rich_row[0].coins} if rich_row else None,
        "suspect": {"name": display_player(suspect_row[0]), "convictions": suspect_row[1].convictions} if suspect_row else None,
        "logs": [{"action": item.action, "text": item.text} for item in logs],
        "actions": [{"action": row[0], "count": int(row[1])} for row in top_action_rows],
    }


def should_send_daily_summary(city: City) -> bool:
    mode = city.activity_mode if city.activity_mode in ACTIVITY_MODES else "normal"
    if mode == "quiet":
        return False
    last = _aware(city.last_daily_summary_at)
    hours = 24 if mode == "normal" else 12
    return not last or utcnow() >= last + timedelta(hours=hours)



# ---- v1.3: AI payloads, secret roles, missions, owner stats, Stars skeleton ----


def _membership_for(db: Session, city: City, player: Player) -> Membership | None:
    return db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))


def get_or_assign_secret_role(db: Session, city: City, player: Player) -> tuple[str | None, bool]:
    membership = _membership_for(db, city, player)
    if not membership:
        return None, False
    if membership.secret_role in SECRET_ROLES:
        return membership.secret_role, False
    key = random.choice(list(SECRET_ROLES.keys()))
    membership.secret_role = key
    membership.reputation += 1
    grant_achievement(db, city, player, "secret_role")
    log(db, city.id, player.id, "secret_role", f"{display_player(player)} получил тайную роль: {SECRET_ROLES[key]['name']}.")
    db.flush()
    return key, True


def secret_role_payload(db: Session, city: City, player: Player) -> dict[str, Any]:
    key, created = get_or_assign_secret_role(db, city, player)
    spec = SECRET_ROLES.get(key or "") or {"name": "нет", "text": "роль не назначена"}
    return {"key": key, "created": created, "name": spec["name"], "text": spec["text"]}


def _mission_action_count(db: Session, city: City, player: Player, action: str, since: datetime | None) -> int:
    query = select(func.count(ActionLog.id)).where(
        ActionLog.city_id == city.id,
        ActionLog.player_id == player.id,
        ActionLog.action == action,
    )
    if since:
        query = query.where(ActionLog.created_at >= since)
    return int(db.scalar(query) or 0)


def _choose_mission_for(membership: Membership) -> str:
    keys = list(MISSIONS.keys())
    if membership.secret_role == "informant" and "rumor" in keys:
        return "rumor"
    if membership.secret_role == "thief" and "black_market" in keys:
        return "black_market"
    if membership.secret_role == "provocateur" and "duel" in keys:
        return random.choice(["duel", "rumor"])
    return random.choice(keys)


def mission_payload(db: Session, city: City, player: Player, check: bool = True) -> dict[str, Any]:
    membership = _membership_for(db, city, player)
    if not membership:
        return {"active": False, "text": "Сначала вступи в город.", "completed": False}

    get_or_assign_secret_role(db, city, player)
    now = utcnow()
    started = _aware(membership.mission_started_at)
    completed = _aware(membership.mission_completed_at)
    expired = bool(started and now >= started + timedelta(hours=24))
    if not membership.mission_key or membership.mission_key not in MISSIONS or expired or (completed and _same_utc_day(completed, now)):
        if not (completed and _same_utc_day(completed, now)):
            membership.mission_key = _choose_mission_for(membership)
            membership.mission_started_at = now
            membership.mission_completed_at = None
            started = now
            completed = None

    key = membership.mission_key if membership.mission_key in MISSIONS else _choose_mission_for(membership)
    spec = MISSIONS[key]
    started = _aware(membership.mission_started_at) or now
    count = _mission_action_count(db, city, player, str(spec["action"]), started)
    is_done = bool(membership.mission_completed_at)
    reward_text = ""
    if check and not is_done and count >= int(spec["need"]):
        membership.mission_completed_at = now
        reward_coins = int(spec["coins"])
        reward_rep = int(spec["rep"])
        player.coins += reward_coins
        player.xp += 8
        membership.reputation += reward_rep
        membership.influence += 1
        city.xp += 6
        grant_achievement(db, city, player, "mission")
        reward_text = f"Миссия выполнена: +{reward_coins} монет, +{reward_rep} репутации."
        log(db, city.id, player.id, "mission_complete", f"{display_player(player)} выполнил миссию: {spec['name']}.")
        is_done = True
    db.flush()
    return {
        "active": True,
        "key": key,
        "name": spec["name"],
        "text": spec["text"],
        "need": int(spec["need"]),
        "progress": min(count, int(spec["need"])),
        "completed": is_done,
        "reward": {"coins": int(spec["coins"]), "rep": int(spec["rep"])},
        "reward_text": reward_text,
    }


def owner_stats_payload(db: Session, city: City) -> dict[str, Any]:
    since_day = utcnow() - timedelta(days=1)
    population = city_population(db, city.id)
    active_people = db.scalar(
        select(func.count(func.distinct(ActionLog.player_id))).where(
            ActionLog.city_id == city.id,
            ActionLog.player_id.is_not(None),
            ActionLog.created_at >= since_day,
        )
    ) or 0
    actions = db.scalar(select(func.count(ActionLog.id)).where(ActionLog.city_id == city.id, ActionLog.created_at >= since_day)) or 0
    top_action = db.execute(
        select(ActionLog.action, func.count(ActionLog.id).label("n"))
        .where(ActionLog.city_id == city.id, ActionLog.created_at >= since_day)
        .group_by(ActionLog.action)
        .order_by(desc("n"))
        .limit(1)
    ).first()
    top_player_row = db.execute(
        select(Player, Membership)
        .join(Membership, Membership.player_id == Player.id)
        .where(Membership.city_id == city.id)
        .order_by(desc(Membership.influence), desc(Membership.reputation))
        .limit(1)
    ).first()
    return {
        "city": city_payload(db, city),
        "population": population,
        "active_24h": int(active_people),
        "actions_24h": int(actions),
        "top_action": {"action": top_action[0], "count": int(top_action[1])} if top_action else None,
        "top_player": {"name": display_player(top_player_row[0]), "influence": top_player_row[1].influence, "rep": top_player_row[1].reputation} if top_player_row else None,
        "mode": activity_mode_payload(city),
        "ai": ai_leader_payload(city),
    }


def ai_usage_allowed(db: Session, city: City) -> tuple[bool, int, int]:
    settings = get_settings()
    limit = max(0, int(settings.ai_daily_limit_per_chat or 0))
    if not settings.ai_enabled or limit <= 0:
        return False, 0, limit
    since = utcnow() - timedelta(days=1)
    used = db.scalar(select(func.count(ActionLog.id)).where(ActionLog.city_id == city.id, ActionLog.action == "ai_used", ActionLog.created_at >= since)) or 0
    return int(used) < limit, int(used), limit


def register_ai_usage(db: Session, city: City, kind: str) -> None:
    log(db, city.id, None, "ai_used", f"AI-ведущий сгенерировал текст: {kind}.")
    db.flush()


def ai_context_payload(db: Session, city: City, kind: str = "газета") -> dict[str, Any]:
    top = top_players(db, city, limit=5)
    event = get_active_event(db, city)
    secret_hint = random.choice(AI_LEADER_FALLBACKS)
    return {
        "kind": kind,
        "city": city_payload(db, city),
        "activity_mode": city.activity_mode,
        "top": top,
        "event": event_payload(event) if event else None,
        "logs": recent_logs(db, city.id, limit=8),
        "secret_hint": secret_hint,
    }



def title_market_payload(db: Session, city: City, player: Player) -> dict[str, Any]:
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    current = player_title(player, membership) if membership else "Гость"
    return {
        "coins": player.coins,
        "current_title": current,
        "items": [
            {"key": key, "name": spec["name"], "cost": int(spec["cost"]), "rep": int(spec.get("rep", 0))}
            for key, spec in TITLE_MARKET.items()
        ],
    }


def buy_title(db: Session, city: City, player: Player, key: str) -> tuple[bool, str, dict[str, Any]]:
    if key not in TITLE_MARKET:
        return False, "Такого титула нет. Табличку украли.", title_market_payload(db, city, player)
    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    if not membership:
        return False, "Сначала стань жителем города.", title_market_payload(db, city, player)
    spec = TITLE_MARKET[key]
    cost = int(spec["cost"])
    if player.coins < cost:
        return False, f"Не хватает монет. Нужно {cost}, у тебя {player.coins}.", title_market_payload(db, city, player)
    player.coins -= cost
    membership.civic_title = str(spec["name"])[:64]
    membership.reputation += int(spec.get("rep", 0))
    log(db, city.id, player.id, "title_buy", f"{display_player(player)} купил титул: {spec['name']}.")
    add_city_history(city, f"{display_player(player)} купил титул: {spec['name']}.", "🏷")
    db.flush()
    return True, f"Титул куплен: {spec['name']}. Теперь можно ходить важным видом.", title_market_payload(db, city, player)


def stars_products_payload() -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": bool(settings.stars_enabled),
        "currency": getattr(settings, "stars_currency", "XTR"),
        "items": [
            {
                "key": key,
                "name": spec["name"],
                "stars": int(spec["stars"]),
                "text": spec["text"],
                "kind": spec.get("kind", "city"),
            }
            for key, spec in STARS_PRODUCTS.items()
        ],
        "note": "Косметика, статусы и городские события. Баланс района не продаётся.",
    }


def get_stars_product(product_key: str) -> dict[str, Any] | None:
    return STARS_PRODUCTS.get((product_key or "").strip())


def make_stars_payload(product_key: str, city: City, player: Player) -> str:
    nonce = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]
    return f"stars:{product_key}:{city.id}:{player.id}:{nonce}"


def parse_stars_payload(payload: str) -> dict[str, Any] | None:
    parts = (payload or "").split(":")
    if len(parts) != 5 or parts[0] != "stars":
        return None
    product_key = parts[1]
    if product_key not in STARS_PRODUCTS:
        return None
    try:
        city_id = int(parts[2])
        player_id = int(parts[3])
    except ValueError:
        return None
    return {"product_key": product_key, "city_id": city_id, "player_id": player_id, "nonce": parts[4]}


def record_stars_purchase(
    db: Session,
    city: City | None,
    player: Player | None,
    product_key: str,
    payload: str,
    stars_amount: int,
    status: str = PurchaseStatus.PENDING.value,
) -> Purchase:
    purchase = Purchase(
        city_id=city.id if city else None,
        player_id=player.id if player else None,
        product_key=product_key,
        stars_amount=int(stars_amount),
        status=status,
        payload=payload[:160],
    )
    db.add(purchase)
    db.flush()
    return purchase


def apply_stars_purchase(
    db: Session,
    city: City,
    player: Player,
    product_key: str,
    payload: str,
    telegram_payment_charge_id: str | None = None,
    provider_payment_charge_id: str | None = None,
) -> tuple[bool, str]:
    spec = get_stars_product(product_key)
    if not spec:
        return False, "Платёж пришёл, но товар не найден. Казначей уже ищет бумаги."

    if telegram_payment_charge_id:
        existing = db.scalar(select(Purchase).where(Purchase.telegram_payment_charge_id == telegram_payment_charge_id))
        if existing and existing.status == PurchaseStatus.PAID.value:
            return True, existing.applied_text or "Покупка уже применена."

    stars_amount = int(spec["stars"])
    text = ""
    premium = get_city_premium(city)

    membership = db.scalar(select(Membership).where(Membership.city_id == city.id, Membership.player_id == player.id))
    if not membership:
        membership = Membership(city_id=city.id, player_id=player.id)
        db.add(membership)
        db.flush()

    if product_key == "ai_newspaper":
        tokens = int(premium.get("ai_newspaper_tokens", 0) or 0) + 1
        premium["ai_newspaper_tokens"] = tokens
        text = f"🗞 {display_player(player)} купил AI-газету. Токенов AI-газеты у города: {tokens}."
    elif product_key == "rename_city":
        tokens = int(premium.get("rename_tokens", 0) or 0) + 1
        premium["rename_tokens"] = tokens
        text = f"🏷 {display_player(player)} купил токен переименования города. Токенов: {tokens}."
    elif product_key == "premium_event":
        premium["premium_events"] = int(premium.get("premium_events", 0) or 0) + 1
        city.xp += 25
        city.treasury += 10
        text = f"🎭 {display_player(player)} оплатил большое событие. Город получил +25 XP и +10 в казну."
    elif product_key == "city_style":
        style = random.choice(CITY_STYLE_POOL)
        premium["style"] = style
        trophy = award_trophy(city, f"🌆 Стиль: {style}")
        text = f"🌆 {display_player(player)} купил стиль города: {style}. Трофей: {trophy}."
    elif product_key == "premium_title":
        title = random.choice(PREMIUM_TITLE_POOL)
        membership.civic_title = title[:64]
        membership.reputation += 3
        text = f"👑 {display_player(player)} получил премиум-титул: {title}."
    elif product_key == "season_bundle":
        premium["season_badge"] = f"Сезонный набор {city.season_number}"
        premium["premium_events"] = int(premium.get("premium_events", 0) or 0) + 1
        premium["ai_newspaper_tokens"] = int(premium.get("ai_newspaper_tokens", 0) or 0) + 1
        trophy = award_trophy(city, f"🏆 Сезонный набор {city.season_number}")
        city.xp += 50
        text = f"🏆 {display_player(player)} купил сезонный набор. Город получил трофей {trophy}, +50 XP, AI-газету и премиум-событие."
    else:
        text = f"⭐ Покупка применена: {spec['name']}."

    set_city_premium(city, premium)
    maybe_level_up(city)
    purchase = Purchase(
        city_id=city.id,
        player_id=player.id,
        product_key=product_key,
        stars_amount=stars_amount,
        status=PurchaseStatus.PAID.value,
        payload=payload[:160],
        telegram_payment_charge_id=telegram_payment_charge_id,
        provider_payment_charge_id=provider_payment_charge_id,
        applied_text=text,
        paid_at=utcnow(),
    )
    db.add(purchase)
    log(db, city.id, player.id, "stars_purchase", text)
    add_city_history(city, text, "⭐")
    db.flush()
    return True, text



def validate_telegram_init_data(init_data: str) -> dict[str, Any] | None:
    """Validate Telegram Mini App initData using BOT_TOKEN, return parsed data if valid."""
    settings = get_settings()
    if not init_data or not settings.has_bot_token:
        return None

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        return None

    if "user" in pairs:
        try:
            pairs["user"] = json.loads(pairs["user"])
        except json.JSONDecodeError:
            return None
    return pairs
