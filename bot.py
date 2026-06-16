"""
Telegram-бот для @botcodeskbot
Услуги, согласие на ПД, фиксация заявок
Запуск: python bot.py
"""

import asyncio
import sqlite3
import datetime
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ─── НАСТРОЙКИ ────────────────────────────────────────────────────────────────

TOKEN = os.getenv("BOT_TOKEN", "8142212744:AAHccNbw832FhtuBMN3t6CRjJIVX2Ydqcb8")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6367874675"))  # числовой ID
CHANNEL_URL = "https://t.me/IgorBroker"
MANAGER_URL  = "https://t.me/Igor_Broker_off"

# ─── КАТАЛОГ УСЛУГ ────────────────────────────────────────────────────────────

SERVICES = {
    "qa_free": {
        "name": "❓ Вопрос — Ответ",
        "price": 0,
        "description": "Один вопрос — один чёткий ответ. Бесплатно.",
    },
    "buy_with_igor": {
        "name": "🤝 Купить с IgorBroker",
        "price": 0,
        "description": "Согласовать дисконт ✅ = Бесплатно 💯\nКупите объект через меня — сопровождение в подарок.",
    },
    "consult_30": {
        "name": "💬 Консультация 30 мин",
        "price": 2900,
        "description": "Разберём вашу ситуацию, отвечу на ключевые вопросы и дам чёткий план действий.",
    },
    "strategy_60": {
        "name": "📊 Разбор стратегии 1 час",
        "price": 4900,
        "description": "Глубокий анализ вашей стратегии по недвижимости. Полный разбор с выводами и рекомендациями.",
    },
    "realty_select": {
        "name": "🏠 Подбор недвижимости",
        "price": 29900,
        "description": "Полное сопровождение: от анализа рынка до сделки. Только проверенные объекты.",
    },
    "express_select": {
    "name": "⚡ Экспресс-подбор",
    "price": 14900,
    "description": (
        "Подбор 5 вариантов из каталога под ваш запрос.\n\n"
        "✅ 5 объектов\n"
        "✅ Краткий комментарий по каждому варианту\n"
        "✅ Быстрый результат\n\n"
        "💳 Работа начинается после полной оплаты."
    ),
},
    
}

# ─── БАЗА ДАННЫХ ──────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect("broker.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS consents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            agreed_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            service_key TEXT,
            service_name TEXT,
            price INTEGER,
            comment TEXT,
            created_at TEXT,
            status TEXT DEFAULT 'new'
        )
    """)
    conn.commit()
    conn.close()

def save_consent(user: types.User):
    conn = sqlite3.connect("broker.db")
    conn.execute(
        "INSERT INTO consents (user_id, username, full_name, agreed_at) VALUES (?,?,?,?)",
        (user.id, user.username or "", user.full_name or "", datetime.datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def has_consent(user_id: int) -> bool:
    conn = sqlite3.connect("broker.db")
    row = conn.execute("SELECT id FROM consents WHERE user_id=? LIMIT 1", (user_id,)).fetchone()
    conn.close()
    return row is not None

def save_order(user: types.User, service_key: str, comment: str = ""):
    svc = SERVICES[service_key]
    conn = sqlite3.connect("broker.db")
    conn.execute(
        """INSERT INTO orders
           (user_id, username, full_name, service_key, service_name, price, comment, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            user.id, user.username or "", user.full_name or "",
            service_key, svc["name"], svc["price"],
            comment, datetime.datetime.now().isoformat()
        )
    )
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect("broker.db")
    consents = conn.execute("SELECT COUNT(*) FROM consents").fetchone()[0]
    orders   = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    new_ord  = conn.execute("SELECT COUNT(*) FROM orders WHERE status='new'").fetchone()[0]
    rows     = conn.execute(
        "SELECT full_name, username, service_name, price, created_at FROM orders ORDER BY id DESC LIMIT 10"
    ).fetchall()
    conn.close()
    return consents, orders, new_ord, rows

# ─── FSM ──────────────────────────────────────────────────────────────────────

class OrderFlow(StatesGroup):
    waiting_comment = State()

# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────

CONSENT_TEXT = """
📋 *Согласие на обработку персональных данных телеграм каналу IgorBroker*

Нажимая «Согласен», вы подтверждаете согласие на обработку ваших персональных данных (ФИО, Телефон, Телеграм ID,username) в целях консультации и оказания услуг в соответствии с ФЗ №152 «О персональных данных».

Данные не передаются третьим лицам и используются исключительно для связи с вами.
"""

def consent_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Согласен", callback_data="agree"),
        InlineKeyboardButton(text="❌ Не согласен", callback_data="disagree"),
    ]])

def catalog_kb():
    buttons = []
    for key, svc in SERVICES.items():
        price_str = "Бесплатно" if svc["price"] == 0 else f"{svc['price']:,} ₽".replace(",", " ")
        buttons.append([InlineKeyboardButton(
            text=f"{svc['name']}  —  {price_str}",
            callback_data=f"svc:{key}"
        )])
    buttons.append([InlineKeyboardButton(text="📢 Перейти в канал", url=CHANNEL_URL)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def service_kb(key: str):
    svc = SERVICES[key]
    price_str = "Бесплатно" if svc["price"] == 0 else f"{svc['price']:,} ₽".replace(",", " ")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Оставить заявку  ({price_str})", callback_data=f"order:{key}")],
        [InlineKeyboardButton(text="◀️ Назад к услугам", callback_data="catalog")],
    ])

def after_order_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все услуги", callback_data="catalog")],
        [InlineKeyboardButton(text="💬 Написать напрямую", url=MANAGER_URL)],
        [InlineKeyboardButton(text="📢 Канал", url=CHANNEL_URL)],
    ])

# ─── HANDLERS ─────────────────────────────────────────────────────────────────

bot = Bot(token=TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    if has_consent(message.from_user.id):
        await message.answer(
            "👋 Привет! Выберите услугу:",
            reply_markup=catalog_kb()
        )
    else:
        await message.answer(CONSENT_TEXT, parse_mode="Markdown", reply_markup=consent_kb())

@dp.message(Command("catalog"))
async def cmd_catalog(message: types.Message):
    if not has_consent(message.from_user.id):
        await message.answer(CONSENT_TEXT, parse_mode="Markdown", reply_markup=consent_kb())
        return
    await message.answer("📋 Выберите услугу:", reply_markup=catalog_kb())

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    consents, orders, new_ord, rows = get_stats()
    text = (
        f"📊 *Статистика*\n\n"
        f"Согласий: {consents}\n"
        f"Заявок всего: {orders}\n"
        f"Новых заявок: {new_ord}\n\n"
        f"*Последние 10 заявок:*\n"
    )
    for r in rows:
        fname, uname, svc_name, price, dt = r
        price_str = "Бесплатно" if price == 0 else f"{price} ₽"
        uname_str = f"@{uname}" if uname else "—"
        text += f"\n• {fname} ({uname_str})\n  {svc_name} — {price_str}\n  {dt[:16]}\n"
    await message.answer(text, parse_mode="Markdown")

# ─── CALLBACKS ────────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "agree")
async def cb_agree(callback: types.CallbackQuery):
    save_consent(callback.from_user)
    await callback.message.edit_text(
        "✅ Согласие зафиксировано.\n\n📋 Выберите услугу:",
        reply_markup=catalog_kb()
    )

@dp.callback_query(F.data == "disagree")
async def cb_disagree(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "Без согласия на обработку данных принять заявку не получится.\n\n"
        "Если передумаете — нажмите /start"
    )

@dp.callback_query(F.data == "catalog")
async def cb_catalog(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("📋 Выберите услугу:", reply_markup=catalog_kb())

@dp.callback_query(F.data.startswith("svc:"))
async def cb_service(callback: types.CallbackQuery):
    key = callback.data.split(":", 1)[1]
    if key not in SERVICES:
        await callback.answer("Услуга не найдена")
        return
    svc = SERVICES[key]
    price_str = "Бесплатно" if svc["price"] == 0 else f"{svc['price']:,} ₽".replace(",", " ")
    text = (
        f"{svc['name']}\n\n"
        f"{svc['description']}\n\n"
        f"💰 Стоимость: *{price_str}*"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=service_kb(key))

@dp.callback_query(F.data.startswith("order:"))
async def cb_order(callback: types.CallbackQuery, state: FSMContext):
    key = callback.data.split(":", 1)[1]
    await state.update_data(service_key=key)
    await state.set_state(OrderFlow.waiting_comment)
    await callback.message.edit_text(
        "📝 Напишите коротко ваш запрос или вопрос (или отправьте «-» если вопросов нет):"
    )

@dp.message(OrderFlow.waiting_comment)
async def process_comment(message: types.Message, state: FSMContext):
    data = await state.get_data()
    key  = data.get("service_key", "")
    comment = message.text.strip()
    await state.clear()

    if key not in SERVICES:
        await message.answer("Что-то пошло не так, попробуйте /start")
        return

    save_order(message.from_user, key, comment)
    svc = SERVICES[key]
    price_str = "Бесплатно" if svc["price"] == 0 else f"{svc['price']:,} ₽".replace(",", " ")

    # уведомление пользователю
    await message.answer(
        f"✅ *Заявка принята!*\n\n"
        f"Услуга: {svc['name']}\n"
        f"Стоимость: {price_str}\n\n"
        f"Свяжусь с вами в ближайшее время 👌",
        parse_mode="Markdown",
        reply_markup=after_order_kb()
    )

    # уведомление админу
    uname = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    tg_link = f"tg://user?id={message.from_user.id}"
    try:
        await bot.send_message(
            ADMIN_ID,
            f"🔔 *Новая заявка!*\n\n"
            f"От: [{message.from_user.full_name}]({tg_link}) ({uname})\n"
            f"Услуга: {svc['name']}\n"
            f"Сумма: {price_str}\n"
            f"Комментарий: {comment}\n"
            f"Время: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.warning(f"Не удалось уведомить админа: {e}")

# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    init_db()
    logging.info("Бот запущен")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
