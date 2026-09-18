import asyncio
import logging
import secrets
import string

import aiosqlite
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

# ============ КОНФИГ ============
BOT_TOKEN = "8692185250:AAEUPdWJ089uktdKVihUpMHSJ61aIuEl2_w"
BRAND_NAME = "Reefy"
MANAGER_USERNAME = "@ReefyManager"
SUPPORT_USERNAME = "@ReefyManager"
COMMISSION_PERCENT = 1.0
ADMIN_IDS = [6311071254]
DB_PATH = "reefy.db"
MIN_TON_WITHDRAW = 2.0

logging.basicConfig(level=logging.INFO)

# ============ СОСТОЯНИЯ ============
class DealCreation(StatesGroup):
    choosing_role = State()
    choosing_payment = State()
    entering_amount = State()
    entering_description = State()

class Requisites(StatesGroup):
    entering_ton = State()
    choosing_region = State()
    entering_card = State()

# ============ УТИЛИТЫ ============
def generate_deal_code(length=10):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

def calc_commission(amount, percent=COMMISSION_PERCENT):
    commission = round(amount * percent / 100, 2)
    to_receive = round(amount - commission, 2)
    return commission, to_receive

# ============ БАЗА ДАННЫХ ============
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                username TEXT,
                lang TEXT DEFAULT 'ru',
                balance REAL DEFAULT 0,
                successful_deals INTEGER DEFAULT 0,
                ton_wallet TEXT,
                card_region TEXT,
                card_number TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_code TEXT UNIQUE,
                seller_id INTEGER,
                buyer_id INTEGER,
                amount REAL,
                currency TEXT,
                description TEXT,
                status TEXT DEFAULT 'pending',
                commission REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        """)
        await db.commit()

async def get_user(tg_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        return await cur.fetchone()

async def create_user(tg_id, username):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (tg_id, username) VALUES (?, ?)",
            (tg_id, username or ""),
        )
        await db.commit()

async def set_user_lang(tg_id, lang):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET lang = ? WHERE tg_id = ?", (lang, tg_id))
        await db.commit()

async def set_ton_wallet(tg_id, wallet):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET ton_wallet = ? WHERE tg_id = ?", (wallet, tg_id))
        await db.commit()

async def set_card(tg_id, region, number):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET card_region = ?, card_number = ? WHERE tg_id = ?",
            (region, number, tg_id),
        )
        await db.commit()

async def create_deal(code, seller_id, amount, currency, description, commission):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO deals (deal_code, seller_id, amount, currency, description, commission)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (code, seller_id, amount, currency, description, commission),
        )
        await db.commit()

async def get_deal_by_code(code):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM deals WHERE deal_code = ?", (code,))
        return await cur.fetchone()

async def set_deal_buyer(code, buyer_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE deals SET buyer_id = ? WHERE deal_code = ?", (buyer_id, code))
        await db.commit()

async def set_deal_status(code, status):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE deals SET status = ? WHERE deal_code = ?", (status, code))
        await db.commit()

async def add_balance(tg_id, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE tg_id = ?", (amount, tg_id))
        await db.commit()

async def inc_deals(tg_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET successful_deals = successful_deals + 1 WHERE tg_id = ?", (tg_id,)
        )
        await db.commit()

# ============ ТЕКСТЫ ============
TEXTS = {
    "ru": {
        "choose_lang": "🌐 Выберите язык / Choose language / اختر اللغة:",
        "welcome": (
            "👑 <b>{brand} MARKET · GARANT</b> 👑\n\n"
            "ℹ️ <b>Наши преимущества:</b>\n\n"
            "✅ Защита от мошенников\n"
            "✅ Автоматическое удержание средств\n"
            "✅ Прозрачная статистика\n"
            "✅ Поддержка 24/7\n"
            "✅ История сделок\n\n"
            "📨 <b>Техническая поддержка:</b> {support}\n\n"
            "🛡 {brand} Market — безопасные сделки 24/7"
        ),
        "btn_create_deal": "🛒 Создать сделку",
        "btn_my_balance": "💼 Мой баланс",
        "btn_requisites": "📨 Реквизиты",
        "btn_support": "🆘 Поддержка",
        "btn_back_menu": "◀️ Вернуться в меню",
        "btn_seller": "👤 Я продавец",
        "btn_ton_wallet": "💎 На GRAM-кошелёк",
        "btn_card_sbp": "💳 Перевод на карту/СБП",
        "btn_stars": "⭐ Звёзды",
        "btn_paid": "✅ Я оплатил",
        "btn_item_sent": "📦 Товар передан менеджеру",
        "btn_add_ton": "💎 Добавить/изменить GRAM-кошелёк",
        "btn_add_card": "💳 Добавить карту/номер телефона",
        "choose_role": (
            "👥 <b>Кем вы создаёте сделку?</b>\n\n"
            "Выберите свою роль — и по ссылке второй участник войдёт в противоположной роли."
        ),
        "choose_payment": "💱 <b>Выберите метод получения оплаты:</b>",
        "enter_amount": "💼 <b>Создание сделки</b>\n\nВведите сумму в формате: <code>100.5</code>",
        "enter_description": (
            "📚 Укажите, что вы предлагаете в этой сделке.\n"
            "Пример: <i>10 Кепок и Пепе...</i>"
        ),
        "req_not_added": "❌ <b>Реквизиты не добавлены</b>",
        "deal_created": (
            "✅ <b>Сделка успешно создана!</b>\n\n"
            "💱 Сумма: <b>{amount} {currency}</b>\n"
            "📚 Описание: <b>{description}</b>\n\n"
            "🔗 <b>Ссылка для покупателя:</b>\n{link}\n\n"
            "<i>Скопируйте ссылку и отправьте покупателю</i>"
        ),
        "payment_confirmed_seller": (
            "🎉 <b>ПЛАТЕЖ ПОДТВЕРЖДЕН!</b>\n\n"
            "✅ Покупатель @{buyer} подтвердил оплату\n"
            "📦 Сделка: <b>#{code}</b>\n"
            "⭐ Товар: {description}\n"
            "💱 Сумма: <b>{amount} {currency}</b>\n\n"
            "📊 <b>Финансовые условия:</b>\n"
            "• Комиссия системы: {percent}% ({commission} {currency})\n"
            "• К зачислению на баланс: <b>{to_receive} {currency}</b>\n\n"
            "⚠️ <b>ТРЕБУЕТСЯ ВАШЕ ДЕЙСТВИЕ:</b>\n"
            "1. Передайте товар менеджеру {manager}\n"
            "2. После передачи нажмите кнопку ниже\n"
            "3. Менеджер подтвердит получение\n"
            "4. Сумма <b>{to_receive} {currency}</b> будет зачислена на ваш баланс\n\n"
            "🚫 <b>Не передавайте товар покупателю напрямую!</b>"
        ),
        "deal_completed_seller": (
            "✅ <b>ВАША СДЕЛКА ЗАВЕРШЕНА.</b>\n\n"
            "Средства успешно начислены на ваш баланс, "
            "зайдите в раздел «💼 Мой баланс»"
        ),
        "balance": (
            "💼 <b>ВАШ БАЛАНС</b>\n\n"
            "👤 Пользователь: @{username}\n\n"
            "Доступные средства:\n"
            "💱 <b>{balance}</b>\n\n"
            "🏦 <b>Информация о выводе средств:</b>\n"
            "🪙 TON-кошелёк: {ton}\n"
            "🏦 Карта / СБП: {card}\n\n"
            "📁 <b>Информация:</b>\n"
            "• Комиссия системы: {percent}%\n"
            "• Вывод доступен на карту, номер или TON-кошелёк\n\n"
            "💼 Успешных сделок: <b>{deals}</b>"
        ),
        "req_menu": (
            "📨 <b>Управление реквизитами</b>\n\n"
            "Используйте кнопки ниже чтобы добавить/изменить реквизиты 🔽"
        ),
        "enter_ton": (
            "🔓 <b>Добавьте ваш TON-кошелёк:</b>\n\n"
            "Пожалуйста, отправьте адрес вашего кошелька\n\n"
            "Важно:\n• Минимальная сумма вывода: {min_ton} TON"
        ),
        "ton_added": "✅ <b>Адрес успешно добавлен</b>",
        "choose_region": (
            "🌍 <b>Выберите регион вашей карты / телефона:</b>\n\n"
            "Поддерживаются карты и номера России, Казахстана, Украины и Беларуси."
        ),
        "enter_card": "💳 Отправьте номер карты или телефона:",
        "card_added": "✅ <b>Реквизиты успешно добавлены</b>",
        "not_added": "🚫 не добавлен",
        "not_added_req": "🚫 Реквизиты не добавлены",
        "empty": "0.00 (Пусто)",
        "join_deal": (
            "📦 <b>Сделка #{code}</b>\n\n"
            "👤 Продавец: @{seller}\n"
            "⭐ Товар: {description}\n"
            "💱 Сумма: <b>{amount} {currency}</b>\n\n"
            "Нажмите «Я оплатил» после перевода."
        ),
        "buyer_paid": "✅ Вы подтвердили оплату. Ожидайте передачи товара менеджеру.",
        "item_sent_ok": "✅ Отлично! Ожидайте подтверждения от покупателя.",
        "deal_not_found": "❌ Сделка не найдена.",
        "admin_only": "⛔ Команда только для администратора.",
        "invalid_amount": "❌ Введите корректное число, например: 100.5",
        "no_active_deals": "Нет активных сделок в статусе paid",
        "no_buyer": "Нет покупателя",
        "deal_already_done": "Сделка уже обработана",
        "error": "Ошибка",
        "admin_deal_done": "✅ Сделка #{code} завершена, {amount} начислено продавцу",
        "admin_set_deals_usage": "Использование: /set_my_deals <число>",
        "admin_set_deals_ok": "✅ Установлено {n} успешных сделок",
    },

    "en": {
        "choose_lang": "🌐 Выберите язык / Choose language / اختر اللغة:",
        "welcome": (
            "👑 <b>{brand} MARKET · GARANT</b> 👑\n\n"
            "ℹ️ <b>Our advantages:</b>\n\n"
            "✅ Protection from scammers\n"
            "✅ Automatic funds holding\n"
            "✅ Transparent statistics\n"
            "✅ 24/7 Support\n"
            "✅ Deal history\n\n"
            "📨 <b>Technical support:</b> {support}\n\n"
            "🛡 {brand} Market — safe deals 24/7"
        ),
        "btn_create_deal": "🛒 Create deal",
        "btn_my_balance": "💼 My balance",
        "btn_requisites": "📨 Requisites",
        "btn_support": "🆘 Support",
        "btn_back_menu": "◀️ Back to menu",
        "btn_seller": "👤 I'm a seller",
        "btn_ton_wallet": "💎 To GRAM wallet",
        "btn_card_sbp": "💳 Card / SBP transfer",
        "btn_stars": "⭐ Stars",
        "btn_paid": "✅ I paid",
        "btn_item_sent": "📦 Item sent to manager",
        "btn_add_ton": "💎 Add/change GRAM wallet",
        "btn_add_card": "💳 Add card/phone number",
        "choose_role": (
            "👥 <b>Who are you in this deal?</b>\n\n"
            "Choose your role — the second participant will join with the opposite role via link."
        ),
        "choose_payment": "💱 <b>Choose payout method:</b>",
        "enter_amount": "💼 <b>Creating deal</b>\n\nEnter the amount, format: <code>100.5</code>",
        "enter_description": (
            "📚 Specify what you offer in this deal.\n"
            "Example: <i>10 Caps and Pepe...</i>"
        ),
        "req_not_added": "❌ <b>Requisites not added</b>",
        "deal_created": (
            "✅ <b>Deal successfully created!</b>\n\n"
            "💱 Amount: <b>{amount} {currency}</b>\n"
            "📚 Description: <b>{description}</b>\n\n"
            "🔗 <b>Link for buyer:</b>\n{link}\n\n"
            "<i>Copy the link and send it to the buyer</i>"
        ),
        "payment_confirmed_seller": (
            "🎉 <b>PAYMENT CONFIRMED!</b>\n\n"
            "✅ Buyer @{buyer} confirmed payment\n"
            "📦 Deal: <b>#{code}</b>\n"
            "⭐ Item: {description}\n"
            "💱 Amount: <b>{amount} {currency}</b>\n\n"
            "📊 <b>Financial terms:</b>\n"
            "• System commission: {percent}% ({commission} {currency})\n"
            "• To be credited: <b>{to_receive} {currency}</b>\n\n"
            "⚠️ <b>YOUR ACTION IS REQUIRED:</b>\n"
            "1. Send the item to manager {manager}\n"
            "2. After sending, press the button below\n"
            "3. Manager will confirm receipt\n"
            "4. Amount <b>{to_receive} {currency}</b> will be credited to your balance\n\n"
            "🚫 <b>Do not send the item to the buyer directly!</b>"
        ),
        "deal_completed_seller": (
            "✅ <b>YOUR DEAL IS COMPLETED.</b>\n\n"
            "Funds have been credited to your balance, "
            "go to «💼 My balance»"
        ),
        "balance": (
            "💼 <b>YOUR BALANCE</b>\n\n"
            "👤 User: @{username}\n\n"
            "Available funds:\n"
            "💱 <b>{balance}</b>\n\n"
            "🏦 <b>Withdrawal info:</b>\n"
            "🪙 TON wallet: {ton}\n"
            "🏦 Card / SBP: {card}\n\n"
            "📁 <b>Info:</b>\n"
            "• System commission: {percent}%\n"
            "• Withdrawal available to card, number or TON wallet\n\n"
            "💼 Successful deals: <b>{deals}</b>"
        ),
        "req_menu": (
            "📨 <b>Requisites management</b>\n\n"
            "Use the buttons below to add/change requisites 🔽"
        ),
        "enter_ton": (
            "🔓 <b>Add your TON wallet:</b>\n\n"
            "Please send your wallet address\n\n"
            "Important:\n• Minimum withdrawal: {min_ton} TON"
        ),
        "ton_added": "✅ <b>Address successfully added</b>",
        "choose_region": (
            "🌍 <b>Choose your card/phone region:</b>\n\n"
            "Cards and numbers from Russia, Kazakhstan, Ukraine and Belarus are supported."
        ),
        "enter_card": "💳 Send your card or phone number:",
        "card_added": "✅ <b>Requisites successfully added</b>",
        "not_added": "🚫 not added",
        "not_added_req": "🚫 Requisites not added",
        "empty": "0.00 (Empty)",
        "join_deal": (
            "📦 <b>Deal #{code}</b>\n\n"
            "👤 Seller: @{seller}\n"
            "⭐ Item: {description}\n"
            "💱 Amount: <b>{amount} {currency}</b>\n\n"
            "Press «I paid» after the transfer."
        ),
        "buyer_paid": "✅ You confirmed payment. Wait for the item to be sent to the manager.",
        "item_sent_ok": "✅ Great! Wait for buyer confirmation.",
        "deal_not_found": "❌ Deal not found.",
        "admin_only": "⛔ Admin-only command.",
        "invalid_amount": "❌ Enter a valid number, e.g. 100.5",
        "no_active_deals": "No active deals in paid status",
        "no_buyer": "No buyer",
        "deal_already_done": "Deal already processed",
        "error": "Error",
        "admin_deal_done": "✅ Deal #{code} completed, {amount} credited to seller",
        "admin_set_deals_usage": "Usage: /set_my_deals <number>",
        "admin_set_deals_ok": "✅ Set {n} successful deals",
    },

    "zh": {
        "choose_lang": "🌐 Выберите язык / Choose language / اختر اللغة:",
        "welcome": (
            "👑 <b>{brand} MARKET · GARANT</b> 👑\n\n"
            "ℹ️ <b>我们的优势：</b>\n\n"
            "✅ 防诈骗保护\n"
            "✅ 自动资金托管\n"
            "✅ 透明统计\n"
            "✅ 24/7 客服支持\n"
            "✅ 交易记录\n\n"
            "📨 <b>技术支持：</b> {support}\n\n"
            "🛡 {brand} Market — 24/7 安全交易"
        ),
        "btn_create_deal": "🛒 创建交易",
        "btn_my_balance": "💼 我的余额",
        "btn_requisites": "📨 收款信息",
        "btn_support": "🆘 客服支持",
        "btn_back_menu": "◀️ 返回菜单",
        "btn_seller": "👤 我是卖家",
        "btn_ton_wallet": "💎 到 GRAM 钱包",
        "btn_card_sbp": "💳 银行卡 / SBP 转账",
        "btn_stars": "⭐ 星星",
        "btn_paid": "✅ 我已付款",
        "btn_item_sent": "📦 物品已交给管理员",
        "btn_add_ton": "💎 添加/修改 GRAM 钱包",
        "btn_add_card": "💳 添加银行卡/手机号",
        "choose_role": (
            "👥 <b>您在本交易中的角色？</b>\n\n"
            "请选择您的角色 — 第二个参与者将通过链接以相反角色加入。"
        ),
        "choose_payment": "💱 <b>请选择收款方式：</b>",
        "enter_amount": "💼 <b>创建交易</b>\n\n请输入金额，格式：<code>100.5</code>",
        "enter_description": (
            "📚 请说明您在本交易中提供的物品。\n"
            "示例：<i>10 个帽子 和 Pepe...</i>"
        ),
        "req_not_added": "❌ <b>收款信息未添加</b>",
        "deal_created": (
            "✅ <b>交易创建成功！</b>\n\n"
            "💱 金额：<b>{amount} {currency}</b>\n"
            "📚 描述：<b>{description}</b>\n\n"
            "🔗 <b>买家链接：</b>\n{link}\n\n"
            "<i>复制链接并发送给买家</i>"
        ),
        "payment_confirmed_seller": (
            "🎉 <b>付款已确认！</b>\n\n"
            "✅ 买家 @{buyer} 已确认付款\n"
            "📦 交易：<b>#{code}</b>\n"
            "⭐ 物品：{description}\n"
            "💱 金额：<b>{amount} {currency}</b>\n\n"
            "📊 <b>费用详情：</b>\n"
            "• 系统佣金：{percent}% ({commission} {currency})\n"
            "• 到账金额：<b>{to_receive} {currency}</b>\n\n"
            "⚠️ <b>需要您的操作：</b>\n"
            "1. 将物品交给管理员 {manager}\n"
            "2. 交给后点击下方按钮\n"
            "3. 管理员确认收到\n"
            "4. 金额 <b>{to_receive} {currency}</b> 将记入您的余额\n\n"
            "🚫 <b>请勿直接将物品交给买家！</b>"
        ),
        "deal_completed_seller": (
            "✅ <b>您的交易已完成。</b>\n\n"
            "资金已成功记入您的余额，"
            "请前往 «💼 我的余额»"
        ),
        "balance": (
            "💼 <b>您的余额</b>\n\n"
            "👤 用户：@{username}\n\n"
            "可用资金：\n"
            "💱 <b>{balance}</b>\n\n"
            "🏦 <b>提现信息：</b>\n"
            "🪙 TON 钱包：{ton}\n"
            "🏦 银行卡 / SBP：{card}\n\n"
            "📁 <b>信息：</b>\n"
            "• 系统佣金：{percent}%\n"
            "• 可提现至银行卡、手机号或 TON 钱包\n\n"
            "💼 成功交易数：<b>{deals}</b>"
        ),
        "req_menu": (
            "📨 <b>收款信息管理</b>\n\n"
            "使用下方按钮添加/修改收款信息 🔽"
        ),
        "enter_ton": (
            "🔓 <b>添加您的 TON 钱包：</b>\n\n"
            "请发送您的钱包地址\n\n"
            "重要：\n• 最低提现金额：{min_ton} TON"
        ),
        "ton_added": "✅ <b>地址添加成功</b>",
        "choose_region": (
            "🌍 <b>请选择您银行卡/手机号的地区：</b>\n\n"
            "支持俄罗斯、哈萨克斯坦、乌克兰和白俄罗斯的银行卡和手机号。"
        ),
        "enter_card": "💳 请发送银行卡号或手机号：",
        "card_added": "✅ <b>收款信息添加成功</b>",
        "not_added": "🚫 未添加",
        "not_added_req": "🚫 收款信息未添加",
        "empty": "0.00（空）",
        "join_deal": (
            "📦 <b>交易 #{code}</b>\n\n"
            "👤 卖家：@{seller}\n"
            "⭐ 物品：{description}\n"
            "💱 金额：<b>{amount} {currency}</b>\n\n"
            "转账后请点击 «我已付款»。"
        ),
        "buyer_paid": "✅ 您已确认付款。请等待物品交给管理员。",
        "item_sent_ok": "✅ 很好！请等待买家确认。",
        "deal_not_found": "❌ 未找到交易。",
        "admin_only": "⛔ 仅管理员命令。",
        "invalid_amount": "❌ 请输入有效数字，例如：100.5",
        "no_active_deals": "没有处于已付款状态的交易",
        "no_buyer": "没有买家",
        "deal_already_done": "交易已处理",
        "error": "错误",
        "admin_deal_done": "✅ 交易 #{code} 已完成，{amount} 已记入卖家余额",
        "admin_set_deals_usage": "用法：/set_my_deals <数字>",
        "admin_set_deals_ok": "✅ 已设置 {n} 次成功交易",
    },
}

def t(lang, key):
    return TEXTS.get(lang, TEXTS["ru"]).get(key, TEXTS["ru"].get(key, key))

def get_lang(user):
    return user["lang"] if user and user["lang"] else "ru"

# ============ КЛАВИАТУРЫ ============
def lang_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
        InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
        InlineKeyboardButton(text="🇨🇳 中文", callback_data="lang:zh"),
    ]])

def main_menu_kb(lang="ru"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_create_deal"), callback_data="create_deal")],
        [
            InlineKeyboardButton(text=t(lang, "btn_my_balance"), callback_data="balance"),
            InlineKeyboardButton(text=t(lang, "btn_requisites"), callback_data="requisites"),
        ],
        [InlineKeyboardButton(
            text=t(lang, "btn_support"),
            url=f"https://t.me/{MANAGER_USERNAME.lstrip('@')}"
        )],
    ])

def back_menu_kb(lang="ru"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_back_menu"), callback_data="main_menu")]
    ])

def role_kb(lang="ru"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_seller"), callback_data="role:seller")],
        [InlineKeyboardButton(text=t(lang, "btn_back_menu"), callback_data="main_menu")],
    ])

def payment_kb(lang="ru"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_ton_wallet"), callback_data="pay:TON")],
        [InlineKeyboardButton(text=t(lang, "btn_card_sbp"), callback_data="pay:Карта/СБП")],
        [InlineKeyboardButton(text=t(lang, "btn_stars"), callback_data="pay:Звёзды")],
        [InlineKeyboardButton(text=t(lang, "btn_back_menu"), callback_data="main_menu")],
    ])

def item_sent_kb(lang="ru"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_item_sent"), callback_data="item_sent")],
        [InlineKeyboardButton(text=t(lang, "btn_back_menu"), callback_data="main_menu")],
    ])

def buyer_pay_kb(code, lang="ru"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_paid"), callback_data=f"paid:{code}")]
    ])

def req_menu_kb(lang="ru"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_add_ton"), callback_data="req:ton")],
        [InlineKeyboardButton(text=t(lang, "btn_add_card"), callback_data="req:card")],
        [InlineKeyboardButton(text=t(lang, "btn_back_menu"), callback_data="main_menu")],
    ])

def region_kb(lang="ru"):
    flags = {
        "ru": ("🇷🇺 Россия", "🇰🇿 Казахстан", "🇺🇦 Украина", "🇧🇾 Беларусь"),
        "en": ("🇷🇺 Russia", "🇰🇿 Kazakhstan", "🇺🇦 Ukraine", "🇧🇾 Belarus"),
        "zh": ("🇷🇺 俄罗斯", "🇰🇿 哈萨克斯坦", "🇺🇦 乌克兰", "🇧🇾 白俄罗斯"),
    }
    r = flags.get(lang, flags["ru"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=r[0], callback_data="region:RU")],
        [InlineKeyboardButton(text=r[1], callback_data="region:KZ")],
        [InlineKeyboardButton(text=r[2], callback_data="region:UA")],
        [InlineKeyboardButton(text=r[3], callback_data="region:BY")],
        [InlineKeyboardButton(text=t(lang, "btn_back_menu"), callback_data="main_menu")],
    ])

# ============ РОУТЕРЫ ============
start_router = Router()
menu_router = Router()
deal_router = Router()
balance_router = Router()
req_router = Router()
admin_router = Router()

# ---------- /start ----------
@start_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await create_user(message.from_user.id, message.from_user.username)

    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1]:
        await handle_buyer_entry(message, args[1])
        return

    await message.answer(TEXTS["ru"]["choose_lang"], reply_markup=lang_kb())

@start_router.callback_query(F.data.startswith("lang:"))
async def set_lang(cb: CallbackQuery, state: FSMContext):
    lang = cb.data.split(":")[1]
    await set_user_lang(cb.from_user.id, lang)
    await state.clear()
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.message.answer(
        t(lang, "welcome").format(brand=BRAND_NAME, support=SUPPORT_USERNAME),
        reply_markup=main_menu_kb(lang),
    )
    await cb.answer()

# ---------- Главное меню ----------
@menu_router.callback_query(F.data == "main_menu")
async def back_to_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(cb.from_user.id)
    lang = get_lang(user)
    await cb.message.edit_text(
        t(lang, "welcome").format(brand=BRAND_NAME, support=SUPPORT_USERNAME),
        reply_markup=main_menu_kb(lang),
    )
    await cb.answer()

# ---------- Создание сделки ----------
@deal_router.callback_query(F.data == "create_deal")
async def create_deal_start(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(cb.from_user.id)
    lang = get_lang(user)
    await cb.message.edit_text(t(lang, "choose_role"), reply_markup=role_kb(lang))
    await cb.answer()

@deal_router.callback_query(F.data == "role:seller")
async def choose_seller(cb: CallbackQuery, state: FSMContext):
    user = await get_user(cb.from_user.id)
    lang = get_lang(user)
    await state.update_data(role="seller", lang=lang)
    await cb.message.edit_text(t(lang, "choose_payment"), reply_markup=payment_kb(lang))
    await cb.answer()

@deal_router.callback_query(F.data.startswith("pay:"))
async def choose_payment(cb: CallbackQuery, state: FSMContext):
    currency = cb.data.split(":", 1)[1]
    user = await get_user(cb.from_user.id)
    lang = get_lang(user)
    await state.update_data(currency=currency, lang=lang)

    if currency == "TON" and not user["ton_wallet"]:
        await cb.message.edit_text(t(lang, "req_not_added"), reply_markup=back_menu_kb(lang))
        await cb.answer()
        return
    if currency == "Карта/СБП" and not user["card_number"]:
        await cb.message.edit_text(t(lang, "req_not_added"), reply_markup=back_menu_kb(lang))
        await cb.answer()
        return

    await state.set_state(DealCreation.entering_amount)
    await cb.message.edit_text(t(lang, "enter_amount"), reply_markup=back_menu_kb(lang))
    await cb.answer()

@deal_router.message(DealCreation.entering_amount)
async def enter_amount(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ru")
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer(t(lang, "invalid_amount"), reply_markup=back_menu_kb(lang))
        return

    await state.update_data(amount=amount)
    await state.set_state(DealCreation.entering_description)
    await message.answer(t(lang, "enter_description"), reply_markup=back_menu_kb(lang))

@deal_router.message(DealCreation.entering_description)
async def enter_description(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    amount = data["amount"]
    currency = data["currency"]
    lang = data.get("lang", "ru")
    description = message.text.strip()

    code = generate_deal_code()
    commission, to_receive = calc_commission(amount)
    await create_deal(code, message.from_user.id, amount, currency, description, commission)
    await state.clear()

    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={code}"

    await message.answer(
        t(lang, "deal_created").format(
            amount=amount, currency=currency, description=description, link=link
        ),
        reply_markup=back_menu_kb(lang),
        disable_web_page_preview=True,
    )

# ---------- Вход покупателя ----------
async def handle_buyer_entry(message: Message, code: str):
    deal = await get_deal_by_code(code)
    if not deal:
        await message.answer(TEXTS["ru"]["deal_not_found"])
        return
    await set_deal_buyer(code, message.from_user.id)
    seller = await get_user(deal["seller_id"])
    seller_username = seller["username"] if seller else "unknown"
    buyer = await get_user(message.from_user.id)
    lang = get_lang(buyer)
    await message.answer(
        t(lang, "join_deal").format(
            code=deal["deal_code"],
            seller=seller_username,
            description=deal["description"],
            amount=deal["amount"],
            currency=deal["currency"],
        ),
        reply_markup=buyer_pay_kb(code, lang),
    )

@deal_router.callback_query(F.data.startswith("paid:"))
async def buyer_paid(cb: CallbackQuery, bot: Bot):
    code = cb.data.split(":", 1)[1]
    deal = await get_deal_by_code(code)
    if not deal:
        await cb.answer(TEXTS["ru"]["deal_not_found"], show_alert=True)
        return
    if deal["status"] != "pending":
        await cb.answer(TEXTS["ru"]["deal_already_done"], show_alert=True)
        return

    await set_deal_status(code, "paid")
    buyer = await get_user(cb.from_user.id)
    lang = get_lang(buyer)
    await cb.message.edit_text(t(lang, "buyer_paid"))
    await cb.answer()

    commission, to_receive = calc_commission(deal["amount"])
    buyer_username = cb.from_user.username or str(cb.from_user.id)

    seller = await get_user(deal["seller_id"])
    seller_lang = get_lang(seller) if seller else "ru"

    try:
        await bot.send_message(
            deal["seller_id"],
            t(seller_lang, "payment_confirmed_seller").format(
                buyer=buyer_username,
                code=code,
                description=deal["description"],
                amount=deal["amount"],
                currency=deal["currency"],
                percent=COMMISSION_PERCENT,
                commission=commission,
                to_receive=to_receive,
                manager=MANAGER_USERNAME,
            ),
            reply_markup=item_sent_kb(seller_lang),
        )
    except Exception as e:
        logging.error(f"Не смог отправить продавцу: {e}")

@deal_router.callback_query(F.data == "item_sent")
async def item_sent(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    lang = get_lang(user)
    await cb.message.edit_text(t(lang, "item_sent_ok"), reply_markup=back_menu_kb(lang))
    await cb.answer()

# ---------- Баланс ----------
@balance_router.callback_query(F.data == "balance")
async def show_balance(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    if not user:
        await cb.answer(TEXTS["ru"]["error"], show_alert=True)
        return
    lang = get_lang(user)

    balance_str = f"{user['balance']:.2f}" if user["balance"] else t(lang, "empty")
    ton = user["ton_wallet"] if user["ton_wallet"] else t(lang, "not_added")
    card = (
        f"{user['card_region']} · {user['card_number']}"
        if user["card_number"] else t(lang, "not_added_req")
    )

    text = t(lang, "balance").format(
        username=user["username"] or str(user["tg_id"]),
        balance=balance_str,
        ton=ton,
        card=card,
        percent=COMMISSION_PERCENT,
        deals=user["successful_deals"],
    )
    await cb.message.edit_text(text, reply_markup=back_menu_kb(lang))
    await cb.answer()

# ---------- Реквизиты ----------
@req_router.callback_query(F.data == "requisites")
async def req_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(cb.from_user.id)
    lang = get_lang(user)
    await cb.message.edit_text(t(lang, "req_menu"), reply_markup=req_menu_kb(lang))
    await cb.answer()

@req_router.callback_query(F.data == "req:ton")
async def req_ton(cb: CallbackQuery, state: FSMContext):
    user = await get_user(cb.from_user.id)
    lang = get_lang(user)
    await state.update_data(lang=lang)
    await state.set_state(Requisites.entering_ton)
    await cb.message.edit_text(
        t(lang, "enter_ton").format(min_ton=MIN_TON_WITHDRAW),
        reply_markup=back_menu_kb(lang),
    )
    await cb.answer()

@req_router.message(Requisites.entering_ton)
async def save_ton(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ru")
    await set_ton_wallet(message.from_user.id, message.text.strip())
    await state.clear()
    await message.answer(t(lang, "ton_added"), reply_markup=back_menu_kb(lang))

@req_router.callback_query(F.data == "req:card")
async def req_card(cb: CallbackQuery, state: FSMContext):
    user = await get_user(cb.from_user.id)
    lang = get_lang(user)
    await state.update_data(lang=lang)
    await state.set_state(Requisites.choosing_region)
    await cb.message.edit_text(t(lang, "choose_region"), reply_markup=region_kb(lang))
    await cb.answer()

@req_router.callback_query(F.data.startswith("region:"))
async def choose_region(cb: CallbackQuery, state: FSMContext):
    region = cb.data.split(":")[1]
    data = await state.get_data()
    lang = data.get("lang", "ru")
    await state.update_data(region=region)
    await state.set_state(Requisites.entering_card)
    await cb.message.edit_text(t(lang, "enter_card"), reply_markup=back_menu_kb(lang))
    await cb.answer()

@req_router.message(Requisites.entering_card)
async def save_card(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ru")
    await set_card(message.from_user.id, data["region"], message.text.strip())
    await state.clear()
    await message.answer(t(lang, "card_added"), reply_markup=back_menu_kb(lang))

# ---------- Скрытые команды (только админ) ----------
@admin_router.message(Command("rteam"))
async def cmd_rteam(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer(TEXTS["ru"]["admin_only"])
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM deals WHERE status = 'paid' ORDER BY id DESC LIMIT 1"
        )
        deal = await cur.fetchone()
    if not deal:
        await message.answer(TEXTS["ru"]["no_active_deals"])
        return
    if not deal["buyer_id"]:
        await message.answer(TEXTS["ru"]["no_buyer"])
        return

    await set_deal_status(deal["deal_code"], "completed")
    commission, to_receive = calc_commission(deal["amount"])
    await add_balance(deal["seller_id"], to_receive)
    await inc_deals(deal["seller_id"])

    seller = await get_user(deal["seller_id"])
    seller_lang = get_lang(seller) if seller else "ru"
    try:
        await message.bot.send_message(
            deal["seller_id"],
            t(seller_lang, "deal_completed_seller"),
        )
    except Exception as e:
        logging.error(e)

    await message.answer(
        t("ru", "admin_deal_done").format(code=deal["deal_code"], amount=to_receive)
    )

@admin_router.message(Command("set_my_deals"))
async def cmd_set_my_deals(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer(TEXTS["ru"]["admin_only"])
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer(t("ru", "admin_set_deals_usage"))
        return
    n = int(args[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET successful_deals = ? WHERE tg_id = ?",
            (n, message.from_user.id),
        )
        await db.commit()
    await message.answer(t("ru", "admin_set_deals_ok").format(n=n))

# ============ ЗАПУСК ============
async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(start_router)
    dp.include_router(menu_router)
    dp.include_router(deal_router)
    dp.include_router(balance_router)
    dp.include_router(req_router)
    dp.include_router(admin_router)

    print(f"🚀 {BRAND_NAME} bot started...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
