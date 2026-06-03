import os
import asyncio
import sqlite3
import json
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Response
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto
from yt_dlp import YoutubeDL

# ==================== НАСТРОЙКИ ПРОЕКТА ====================
BOT_TOKEN = "8888379212:AAE2GnSTzbNlZ14B6d0Wd-ed5IzXwW0Xp28"
ADMIN_ID = 906815308 # Твой реальный ID

# Реальные платежные ссылки WayForPay и DeStream
WAYFORPAY_PREMIUM_URL = "https://raw.githubusercontent.com/Serj2a/-tikreels-wizard-bot/refs/heads/main/img%20(1).png"
WAYFORPAY_COFFEE_URL = "https://raw.githubusercontent.com/Serj2a/-tikreels-wizard-bot/735e2e0187739ff8452b702de9783e737dc26a91/tips_maket_big.png"

DESTREAM_BASE_URL = "https://destream.net/live/finance/donate"

# СРАЗУ ПОСЛЕ ЭТОГО ДОЛЖЕН ИДТИ СЛЕДУЮЩИЙ КОД (НАПРИМЕР, СОЗДАНИЕ БОТА ИЛИ БАЗЫ ДАННЫХ),
# НО НИКАКИХ ПОВТОРНЫХ "import os" ИЛИ "import asyncio" БЫТЬ НЕ ДОЛЖНО!


"CHANNEL_URL = https://t.me/tikreels_wizard_club"

bot = Bot(token=BOT_TOKEN)

dp = Dispatcher()
app = FastAPI()  # Веб-сервер для автоматического приема денег

user_urls = {}
DB_NAME = "users_limits.db"

# Умный словарь для красивой аналитики стран (Решаем проблему с "ru")
LANG_FLAGS = {
    "uk": "🇺🇦 Україна (uk)",
    "ua": "🇺🇦 Україна (ua)",
    "en": "🇬🇧 Міжнародний (en)",
    "ru": "📱 Східна Європа (ru)",
    "pl": "🇵🇱 Польща (pl)",
    "de": "🇩🇪 Німеччина (de)"
}

def get_country_text(lang_code):
    return LANG_FLAGS.get(lang_code.lower() if lang_code else "en", f"🌐 Інша ({lang_code})")

# ==================== СИСТЕМА БАЗЫ ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            free_attempts INTEGER,
            last_download_date TEXT,
            lang_code TEXT,
            reg_date TEXT,
            total_downloads INTEGER DEFAULT 0,
            premium_until TEXT DEFAULT NULL
        )
    ''')
    conn.commit()
    conn.close()

# Проверка Premium статуса в базе данных
def check_premium_status(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT premium_until FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row[0]:
        try:
            premium_date = datetime.strptime(row[0], "%Y-%m-%d")
            if premium_date >= datetime.now():
                return True
        except:
            return False
    return False


# Отримання або створення користувача у базі (Захист від обману + країни)
def get_or_create_user(user_id, lang_code="en"):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT free_attempts, last_download_date FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    current_date = datetime.now().strftime("%Y-%m-%d")
    clean_lang = lang_code.lower() if lang_code else "en"

    if row is None:
        # Новий користувач: 3 безкоштовні спроби на старті
        cursor.execute('''
            INSERT INTO users (user_id, free_attempts, last_download_date, lang_code, reg_date) 
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, 3, current_date, clean_lang, current_date))
        conn.commit()
        conn.close()
        return 3
    else:
        free_attempts, last_download_date = row
        # Бонус нового дня: нараховуємо +1 спробу, якщо Premium немає і настав новий день
        if last_download_date != current_date:
            if not check_premium_status(user_id):
                if free_attempts == 0:
                    free_attempts = 1
            cursor.execute("UPDATE users SET free_attempts = ?, last_download_date = ? WHERE user_id = ?",
                           (free_attempts, current_date, user_id))
            conn.commit()
        conn.close()
        return free_attempts


# Списання спроби після успішного скачування
def reduce_attempt(user_id):
    if check_premium_status(user_id):
        return  # Преміум-користувачам ліміти не списуємо!
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT free_attempts FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row[0] > 0:
        new_attempts = row[0] - 1
        cursor.execute("UPDATE users SET free_attempts = ? WHERE user_id = ?", (new_attempts, user_id))
    cursor.execute("UPDATE users SET total_downloads = total_downloads + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# Активація Premium (Для автоматичної системи та ручних компенсацій)
def set_premium_days(user_id, days):
    end_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET premium_until = ? WHERE user_id = ?", (end_date, user_id))
    conn.commit()
    conn.close()
    return end_date


# ==================== СЕКРЕТНА АДМІН-ПАНЕЛЬ (АНАЛІТИКА) ====================
def get_admin_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1. Рахуємо унікальних користувачів
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    # 2. Рахуємо загальну кількість завантажень
    cursor.execute("SELECT SUM(total_downloads) FROM users")
    total_downloads = cursor.fetchone()[0] or 0

    # 3. Витягуємо статистику по країнах
    cursor.execute("SELECT lang_code, COUNT(*) FROM users GROUP BY lang_code ORDER BY COUNT(*) DESC")
    lang_rows = cursor.fetchall()

    # 4. Витягуємо тільки чисті ID останніх 5 користувачів (Захист від помилки no such column)
    cursor.execute("SELECT user_id FROM users ORDER BY user_id DESC LIMIT 5")

    recent_users = cursor.fetchall()
    recent_users_text = ""
    for u in recent_users:
        recent_users_text += f"• ID: {u[0]}\n"


    # Закриваємо з'єднання з базою після всіх запитів
    conn.close()

    # 5. Формуємо красиву статистику по країнах
    lang_stats = ""
    for row in lang_rows:
        lang, count = row
        lang_stats += f"• 🌍 Мова [{lang}]: {count} користувачів\n"

    # 6. Збираємо фінальний текст аналітики
    stats_text = (
        "📊 **АНАЛІТИКА TikReels Wizard** 📊\n\n"
        f"👥 Всього унікальних користувачів: `{total_users}`\n"
        f"📥 Завантажень зроблено всього: `{total_downloads}`\n\n"
        f"🌍 **Статистика по країнах (мовах):**\n{lang_stats}\n"
        "👤 **ОСТАННІ ЮЗЕРИ (Клікни на ID для копіювання):**\n"
        f"{recent_users_text}\n"
        "⚙️ **КОМАНДИ АДМІНІСТРАТОРА:**\n"
        "📢 Розсилка: ТЕКСТ — надіслати рекламу всем\n"
        "👑 /give_premium ID ДНІ — видати Premium"
    )
    return stats_text


# Секретний код аналітики та управління
@dp.message(F.text == "/xA4dcG")
async def cmd_admin(message: Message):
    if message.from_user.id == ADMIN_ID:
        stats = get_admin_stats()
        admin_menu = (
            f"{stats}\n"
            "⚙️ **КОМАНДИ АДМІНІСТРАТОРА:**\n"
            "📢 Розсилка: ТЕКСТ — надіслати рекламу всім\n"
            "👑 /give_premium ID ДНІ — видати Premium"
        )
        await message.answer(admin_menu, parse_mode="Markdown")


# Функція ручної видачі Premium (Компенсація лояльності)
@dp.message(F.text.startswith("/give_premium"))
async def admin_give_premium(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.split()
        target_id = int(parts[1])
        days = int(parts[2])

        end_date = set_premium_days(target_id, days)
        await message.answer(f"✅ Користувачу `{target_id}` успішно активовано Premium на {days} днів (до {end_date})!")

        # Автоматично сповіщаємо користувача про приємний бонус!
        try:
            await bot.send_message(
                chat_id=target_id,
                text=f"🇺🇦 **Прийміть наші вибачення!** 🪄✨\n"
                     f"Через технічні неполадки наш сервіс тимчасово не працював. "
                     f"Розробник активував вам **{days} днів безкоштовного Premium-безліміту** в якості компенсації! Дякуємо, що ви з нами! 🤝\n\n"
                     f"🇬🇧 **Our apologies!** 🪄✨\n"
                     f"The developer activated **{days} days of free Premium** for you as a compensation! Thank you for staying with us! 🤝"
            )
        except Exception as e:
            print(f"Не вдалося надіслати сповіщення користувачу: {e}")
    except Exception as e:
        await message.answer("❌ Помилка команди. Формат: `/give_premium ID ДНІ`")


# Масова рекламна розсилка за 1 клік (Всеядна: Текст або Фото з банером)
@dp.message(lambda msg: (msg.text and msg.text.startswith("Розсилка:")) or (
        msg.caption and msg.caption.startswith("Розсилка:")))
async def admin_broadcast(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    # Визначаємо, де лежить рекламний текст (у звичайному повідомленні чи під фото)
    is_photo = bool(message.photo)
    raw_text = message.caption if is_photo else message.text
    broadcast_text = raw_text.replace("Розсилка:", "").strip()

    if not broadcast_text and not is_photo:
        await message.answer("❌ Текст розсилки порожній!")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()

    success_count = 0
    await message.answer("📢 Запускаю масову рекламну розсилку (Текст + Банер)...")

    # Якщо адмін надіслав фото, беремо найкращу якість (найвищий індекс)
    photo_file_id = message.photo[-1].file_id if is_photo else None

    for user in users:
        try:
            if is_photo:
                # Розсилаємо фото з красивим описом під ним
                await bot.send_photo(chat_id=user[0], photo=photo_file_id, caption=broadcast_text)
            else:
                # Розсилаємо звичайний текст
                await bot.send_message(chat_id=user[0], text=broadcast_text)

            success_count += 1
            await asyncio.sleep(0.05)  # Захист від блокувань Telegram API
        except:
            continue

    await message.answer(f"📢 Розсилку завершено! Успішно доставлено {success_count} користувачам.")


# ==================== ГЕНЕРАЦІЯ МУЛЬТИВАЛЮТНИХ КНОПОК ОПЛАТИ ====================
# Розумні кнопки оплати, які автоматично зашивають ID користувача в хвостики посилань
def get_paywall_keyboard(user_id):
    # Формуємо хвостики для DeStream (Долари) — сума $2, маркер premium/coffee та унікальний ID
    destream_premium = f"{DESTREAM_BASE_URL}?amount=2&currency=USD&comment=premium_{user_id}"
    destream_coffee = f"{DESTREAM_BASE_URL}?comment=coffee_{user_id}"

    buttons = [
        # Ряд 1: Кнопки для України (Гривня через WayForPay)
        [
            InlineKeyboardButton(text="💎🇺🇦 Premium (UAH)", url=WAYFORPAY_PREMIUM_URL),
            InlineKeyboardButton(text="☕️🇺🇦 Купити каву (UAH)", url=WAYFORPAY_COFFEE_URL)
        ],
        # Ряд 2: Кнопки для закордону (Долар/Євро через DeStream)
        [
            InlineKeyboardButton(text="💎🌐 Premium ($2)", url=destream_premium),
            InlineKeyboardButton(text="☕️🌐 Buy a Coffee (USD)", url=destream_coffee)
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_start_keyboard():
    buttons = [
        [
            InlineKeyboardButton(text="☕️ Coffee", callback_data="show_paywall_menu"),
            InlineKeyboardButton(text="❓ Help", callback_data="show_help"),
            InlineKeyboardButton(text="✍️ Support", callback_data="contact_support")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_back_keyboard():
    buttons = [[InlineKeyboardButton(text="🔙 Назад / Back", callback_data="back_to_start")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_format_keyboard():
    buttons = [
        [
            InlineKeyboardButton(text="🎬 Video (MP4)", callback_data="download_mp4"),
            InlineKeyboardButton(text="🎵 Audio (MP3)", callback_data="download_mp3")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_subscribe_keyboard():
    buttons = [
        [InlineKeyboardButton(text="📢 Підписатися / Subscribe", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Я підписався / I subscribed", callback_data="check_subscription")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==================== ГОЛОВНІ КОМАНДИ КОРИСТУВАЧІВ ====================

@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    user_lang = message.from_user.language_code or "en"
    get_or_create_user(message.from_user.id, lang_code=user_lang)
    country_name = get_country_text(user_lang)
    try:
        user_id = message.from_user.id
        user_lang = message.from_user.language_code or "en"
        country_text = get_country_text(user_lang)
        
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"👑 **Новий юзер у системі!**\n👤 ID: `{user_id}`\n🌍 Країна: {country_text}"
        )
    except Exception as e:
        print(f"Помилка надсилання адміну: {e}")

         
        # Рядок 358 (має рівно 4 пробіли зліва, чітко під лінієчку!):
    await message.answer(
        "🧙‍♂️ **Привіт! Я твій ультимативний магічний завантажувач!**\n\n"
        "Надішліть мені посилання на відео з **TikTok**, **Instagram Reels** або **YouTube Shorts**, і я завантажу його в FullHD якості без водяних знаків!\n\n"
        "📢 Наш офіційний клуб: @tikreels_wizard_club",
        reply_markup=get_start_keyboard()
    )

# ==================== КЛІЄНТСЬКА МАГІЧНА ІНСТРУКЦІЯ ДЛЯ КОРИСТУВАЧІВ ====================
@dp.callback_query(F.data == "show_help")
async def process_help(callback: CallbackQuery):
    await callback.message.edit_text(
        "🔮 **МАГІЧНА ІНСТРУКЦІЯ / MANUAL:**\n\n"
        "🇺🇦 **ДЛЯ УКРАЇНИ:**\n"
        "1. Надішліть посилання з TikTok, Instagram або Shorts 🎬\n"
        "2. Отримайте соковите FullHD відео без водяних знаків!\n"
        "🎁 **Ліміти:** Перші 3 відео — БЕЗКОШТОВНО! Далі — 1 безкоштовне відео на день.\n"
        "💎 **Premium тарифи:**\n"
        "• Безліміт на 1 день — всього 10 грн!\n"
        "• Повний безліміт на 1 місяць — 80 грн! 👑\n\n"
        "🇬🇧 **INTERNATIONAL:**\n"
        "1. Send a link from TikTok, Instagram, or YouTube Shorts 🎬\n"
        "2. Get crystal clear FullHD video with NO watermarks!\n"
        "🎁 **Limits:** First 3 videos are FREE! Then — 1 free video every day.\n"
        "💎 **Premium:** Full unlimited access for just $2/month! (Total steal!)\n\n"
        "📢 Наш офіційний клуб: @tikreels_wizard_club",
        reply_markup=get_start_keyboard()
    )


# ==================== СИСТЕМА ПЕРЕХОПЛЕННЯ ТА СКАЧУВАННЯ ВІДЕО ====================
@dp.message(F.text.contains("tiktok.com") | F.text.contains("instagram.com") | F.text.contains("youtube.com"))
async def handle_video_link(message: Message):
    url = message.text.strip()
    user_id = message.from_user.id
    
    # Запускаем твой родной, встроенный асинхронный движок скачивания!
    asyncio.create_task(download_process(message, user_id, url, mode="video"))





@dp.callback_query(F.data == "back_to_start")
async def process_back_to_start(callback: CallbackQuery):
    await callback.message.edit_text(
        "🇺🇦 Надішли мені посилання на ⚡️ **TikTok**, 🔮 **Instagram** або 🔥 **YouTube Shorts**!\n\n"
        "🇬🇧 Send me a ⚡️ **TikTok**, 🔮 **Instagram** or 🔥 **YouTube Shorts** link!",
        reply_markup=get_start_keyboard()
    )


# Показ вітрини оплати (Пейволл) при натисканні на кнопку Coffee з головного меню
@dp.callback_query(F.data == "show_paywall_menu")
async def process_show_paywall(callback: CallbackQuery):
    user_id = callback.from_user.id
    await callback.message.edit_text(
        "🇺🇦 **Оберіть свій варіант підтримки проєкту:** 💳✨\n"
        "Отримуйте Premium-безліміт або пригостіть автора кавою!\n\n"
        "🇬🇧 **Choose your support option:** 💳✨\n"
        "Get Premium unlimited or buy the author a coffee!",
        reply_markup=get_paywall_keyboard(user_id)
    )


# ==================== ЛОГІКА ТЕХПІДТРИМКИ (ЗВ'ЯЗОК З АДМІНОМ) ====================
@dp.callback_query(F.data == "contact_support")
async def process_support(callback: CallbackQuery):
    await callback.message.edit_text(
        "🇺🇦 **ЗВ'ЯЗОК З ПІДТРИМКОЮ:**\n"
        "Напиши своє питання або повідомлення про помилку **наступним повідомленням** прямо сюди в чат. "
        "Розробник або адмін відповість тобі найближчим часом! ✍️\n\n"
        "🇬🇧 **CONTACT SUPPORT:**\n"
        "Write your question or bug report in the **next message** right here in the chat. "
        "The developer will reply to you shortly! ✍️",
        reply_markup=get_back_keyboard()
    )
    # Режим очікування тексту для техпідтримки
    user_urls[callback.from_user.id] = "waiting_for_support_text"


# Перехоплення тексту та надсилання адміну
@dp.message(lambda msg: user_urls.get(msg.from_user.id) == "waiting_for_support_text")
async def forward_to_admin(message: Message):
    user_id = message.from_user.id
    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📬 **НОВЕ ПОВІДОМЛЕННЯ В ТЕХПІДТРИМКУ!**\n"
                 f"👤 Від: {message.from_user.full_name}\n"
                 f"🆔 ID користувача: `{user_id}`\n"
                 f"📝 Текст: {message.text}\n\n"
                 f"ℹ️ *Щоб відповісти йому, використовуй команду:* `/reply {user_id} ТВІЙ_ТЕКСТ`"
        )
        await message.answer(
            "🇺🇦 Повідомлення успішно надіслано адміну! 🚀\n🇬🇧 Message successfully sent to admin! 🚀")
    except:
        await message.answer("❌ Помилка надсилання. Спробуйте пізніше.")
    finally:
        if user_id in user_urls: del user_urls[user_id]


# Команда відповіді користувачу з адмінки
@dp.message(F.text.startswith("/reply"))
async def admin_reply(message: Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split(maxsplit=2)
        target_id = int(parts[1])
        reply_text = parts[2]

        await bot.send_message(
            chat_id=target_id,
            text=f"💬 **ВІДПОВІДЬ ВІД ТЕХПІДТРИМКИ / REPLY FROM SUPPORT:**\n\n{reply_text}"
        )
        await message.answer(f"✅ Відповідь користувачу `{target_id}` успішно доставлена!")
    except:
        await message.answer("❌ Помилка. Формат: `/reply ID ТЕКСТ`")


# ==================== УНІВЕРСАЛЬНИЙ ДВИГУН СКАНУВАННЯ (TIKTOK, INSTAGRAM, YOUTUBE SHORTS) ====================
@dp.message(lambda msg: any(x in msg.text for x in ["tiktok.com", "instagram.com", "://youtube.com", "youtu.be"]))
async def ask_subscription(message: Message):
    user_id = message.from_user.id
    user_urls[user_id] = message.text

    # 👑 ПЕРЕВІРКА ПРЕМІУМУ: якщо є Premium, відразу даємо вибір форматів без лімітів та перевірок підписки!
    if check_premium_status(user_id):
        await message.answer(
            "🇺🇦 👑 **Вітаємо Premium-користувача!** Обери формат для завантаження:\n"
            "🇬🇧 👑 **Welcome Premium User!** Choose format to download:",
            reply_markup=get_format_keyboard()
        )
        return

    # Якщо преміуму немає — перевіряємо стандартні ліміти бази даних
    user_lang = message.from_user.language_code or "en"
    attempts = get_or_create_user(user_id, lang_code=user_lang)
    if attempts <= 0:
        await message.answer(
            "🇺🇦 **Твій денний ліміт магії вичерпано!** 🔒✨\n"
            "Сьогодні ти вже використав свої безкоштовні спроби.\n\n"
            "🎁 **Добра новина:** Завтра баланс автоматично оновиться, і ти отримаєш **1 безкоштовне завантаження**!\n\n"
            "🔥 **Не хочеш чекати до завтра?**\n"
            "Отримай повний Безліміт (Premium) прямо зараз всього за ціну однієї чашки кави!",
            reply_markup=get_paywall_keyboard(user_id)
        )
        return

    # Якщо спроби є — вимагаємо обов'язкову підписку на канал
    await message.answer(
        "🇺🇦 🔒 Магія заблокована! Щоб користуватися всіма фішками без лімітів, підпишись на наш канал та натисни кнопку нижче:\n\n"
        "🇬🇧 🔒 Magic locked! To use all features without limits, subscribe to our channel and click the button below:",
        reply_markup=get_subscribe_keyboard()
    )


# Обробка кнопки "Я підписався"
@dp.callback_query(F.data == "check_subscription")
async def process_check_subscription(callback: CallbackQuery):
    user_id = callback.from_user.id
    url = user_urls.get(user_id)

    if not url:
        await callback.answer("🇺🇦 Надішліть посилання заново!\n🇬🇧 Please send the link again!", show_alert=True)
        return

    if "/photo/" in url or "video" not in url and "/p/" in url:
        await callback.message.delete()
        await download_process(callback.message, user_id, url, mode="auto")
    else:
        await callback.message.edit_text(
            "🇺🇦 🔓 Доступ відкрито! Обери формат, який ти хочеш завантажити:\n\n"
            "🇬🇧 🔓 Access granted! Choose the format you want to download:",
            reply_markup=get_format_keyboard()
        )


@dp.callback_query(F.data == "download_mp4")
async def process_mp4(callback: CallbackQuery):
    user_id = callback.from_user.id
    url = user_urls.get(user_id)
    await callback.message.delete()
    await download_process(callback.message, user_id, url, mode="video")


@dp.callback_query(F.data == "download_mp3")
async def process_mp3(callback: CallbackQuery):
    user_id = callback.from_user.id
    url = user_urls.get(user_id)
    await callback.message.delete()
    await download_process(callback.message, user_id, url, mode="audio")

async def download_process(message_obj: Message, user_id: int, url: str, mode: str):
    status_msg = await message_obj.answer(
        "🇺🇦 Магія починається... Запускаю ракету за файлами 🚀🔥\n"
        "🇬🇧 Magic begins... Launching rocket for files 🚀🔥"
    )

    video_filename = f"final_{user_id}.mp4"
    audio_filename = f"final_{user_id}.mp3"

    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'no_warnings': True,
        'quiet': True,
        'geo_bypass': True,
        'http_headers': {},
        'postprocessor_args': {
            'ffmpeg': ['-crf', '18', '-preset', 'fast']
        }
    }

    if mode == "video":
        ydl_opts['outtmpl'] = video_filename
    elif mode == "audio":
        ydl_opts['outtmpl'] = audio_filename
        ydl_opts['format'] = 'bestaudio/best'
    elif mode == "auto":
        ydl_opts['outtmpl'] = f"media_{user_id}_%(pickle_index)s.%(ext)s"



    if mode == "video":
        ydl_opts['outtmpl'] = video_filename
    elif mode == "audio":
        ydl_opts['outtmpl'] = audio_filename
        ydl_opts['format'] = 'bestaudio/best'
    elif mode == "auto":
        ydl_opts['outtmpl'] = f"media_{user_id}_%(pickle_index)s.%(ext)s"



    if mode == "video":
        ydl_opts['outtmpl'] = video_filename
    elif mode == "audio":
        ydl_opts['outtmpl'] = audio_filename
        ydl_opts['format'] = 'bestaudio/best'
    elif mode == "auto":
        ydl_opts['outtmpl'] = f"media_{user_id}_%(pickle_index)s.%(ext)s"

    try:
        with YoutubeDL(ydl_opts) as ydl:
            # 1. Сначала движок СКАЧИВАЕТ видео и создает переменную info
            info = ydl.extract_info(url, download=True)

            # 2. А вот здесь наш залізобетонный фикс с нулем [0], который уничтожает ошибку списков!
            while isinstance(info, list) and len(info) > 0:
                info = info[0]

        # 3. Полная защита от любых списков на сервере
        is_playlist = False
        if info and getattr(info, 'get', lambda *a: None)('entries') or getattr(info, 'get', lambda *a: None)(
                'type') == 'playlist':
            is_playlist = True

        if is_playlist:
            photos = [InputMediaPhoto(media=open(f, 'rb')) for f in os.listdir('.') if f.startswith(f"media_{user_id}")]
            if photos:
                await message_obj.reply_media_group(media=photos)
                for f in os.listdir('.'):
                    if f.startswith(f"media_{user_id}"):
                        os.remove(f)
            await status_msg.delete()
            reduce_attempt(user_id)
            return

        # 4. Надежная локальная отправка готовых файлов напрямую в чат (Захист от message not found)
        if mode == "video" and os.path.exists(video_filename):
            from aiogram.types import FSInputFile
            video_file = FSInputFile(video_filename)
            await bot.send_video(chat_id=user_id, video=video_file, caption="Your video is ready! / Видео готово!")
        elif mode == "audio" and os.path.exists(audio_filename):
            from aiogram.types import FSInputFile
            audio_file = FSInputFile(audio_filename)
            await bot.send_audio(chat_id=user_id, audio=audio_file, caption="Your audio is ready! / Аудио готово!")

        await status_msg.delete()
        reduce_attempt(user_id)
        await bot.send_message(chat_id=ADMIN_ID, text=f"📥 Успішно!\nЮзер: {user_id}...")


    except Exception as e:
        await status_msg.edit_text(
            "🇺🇦 Ой, магія дала збій... Перевір посилання або спробуй ще раз! ❌\n🇬🇧 Oops, magic failed... Check the link or try again! ❌")
        print(f"Помилка відправки: {e}")
    finally:
        if os.path.exists(video_filename): os.remove(video_filename)
        if os.path.exists(audio_filename): os.remove(audio_filename)
        if user_id in user_urls: del user_urls[user_id]


# ==================== ЗАПУСК БОТА ДЛЯ ТЕСТУ НА ПК ====================
async def main():
    init_db()
    print("Ультимативна автоматична грошова машина CodeOfFreedom запущена ЛОКАЛЬНО НА ПК!")
    await dp.start_polling(bot)


# ==================== УЛЬТИМАТИВНА СЕРВЕРНА ПОДОШВА ДЛЯ RENDER ====================
from fastapi import FastAPI, Request, Response
app = FastAPI()

@app.get("/")
async def root():
    return {"status": "alive"}

@app.on_event("startup")
async def on_startup():
    init_db()
    # Удаляем любые старые зависшие вебхуки на серверах Telegram, чтобы освободить линию!
    await bot.delete_webhook(drop_pending_updates=True)
    # Запускаем вечный фоновый процесс опроса, который Render никогда не сможет выключить!
    asyncio.create_task(dp.start_polling(bot, skip_updates=True))
    print("Ультимативная машина CodeOfFreedom успешно запущена на Render через вечный Polling!")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)




