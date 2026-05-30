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
TOKEN = "8888379212:AAGLWQjd_WUAiFGIT12P3nAwqdOe94nfjxA"
ADMIN_ID = 906815308 # Твой ID

# Реальные платежные ссылки WayForPay и DeStream
WAYFORPAY_PREMIUM_URL = "https://secure.wayforpay.com/sub/TikReels_Wizard_Premium"
WAYFORPAY_COFFEE_URL = "https://secure.wayforpay.com/tips/coffee_wizard"

DESTREAM_BASE_URL = "https://destream.net/live/finance/donate"

CHANNEL_URL = "https://t.me"

bot = Bot(token=TOKEN)
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
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(total_downloads) FROM users")
    total_downloads = cursor.fetchone()[0] or 0
    cursor.execute("SELECT lang_code, COUNT(*) FROM users GROUP BY lang_code ORDER BY COUNT(*) DESC")
    lang_rows = cursor.fetchall()
    conn.close()

    stats_text = (
        "📊 **АНАЛІТИКА TikReels Wizard** 📊\n\n"
        f"👥 Всього унікальних користувачів: `{total_users}`\n"
        f"📥 Завантажень зроблено всього: `{total_downloads}`\n\n"
        "🌍 **Статистика по країнах (мовах):**\n"
    )
    for row in lang_rows:
        lang, count = row
        country_name = get_country_text(lang)  # Наш магічний словник прапорців!
        stats_text += f"• {country_name}: {count} користувачів\n"
    return stats_text


# Секретний код аналітики та управління
@dp.message(F.text == "/xA4dcG")
async def cmd_admin(message: Message):
    if message.from_user.id == ADMIN_ID:
        stats = get_admin_stats()
        admin_menu = (
            f"{stats}\n"
            "⚙️ **КОМАНДИ АДМІНІСТРАТОРА:**\n"
            "📢 `Розсилка: ТЕКСТ` — надіслати рекламу всім\n"
            "👑 `/give_premium ID ДНІ` — видати Premium"
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


# Масова рекламна розсилка за 1 клік
@dp.message(F.text.startswith("Розсилка:"))
async def admin_broadcast(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    broadcast_text = message.text.replace("Розсилка:", "").strip()
    if not broadcast_text:
        await message.answer("❌ Текст розсилки порожній!")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()

    success_count = 0
    await message.answer("📢 Запускаю масову рекламну розсилку...")

    for user in users:
        try:
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
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"👤 Новий користувач запустив бота!\n"
                 f"Ім'я: {message.from_user.full_name}\n"
                 f"Юзернейм: @{message.from_user.username or 'немає'}\n"
                 f"Країна (мова): `{country_name}`"
        )
    except Exception as e:
        print(f"Помилка логування: {e}")

    await message.answer(
        "🇺🇦 Привіт! Я твій магічний завантажувач 🪄\n"
        "Надішли мені посилання на відео з ⚡️ **TikTok**, 🔮 **Instagram** або 🔥 **YouTube Shorts**, і я скачаю його без водяних знаків!\n\n"
        "🇬🇧 Hi! I am your magic downloader 🪄\n"
        "Send me a ⚡️ **TikTok**, 🔮 **Instagram** or 🔥 **YouTube Shorts** link, and I will download it without watermarks!",
        reply_markup=get_start_keyboard()
    )


# Клікабельна магічна інструкція для користувачів
@dp.callback_query(F.data == "show_help")
async def process_help(callback: CallbackQuery):
    await callback.message.edit_text(
        "🇺🇦 **МАГІЧНА ІНСТРУКЦІЯ / HELP:**\n\n"
        "💥 **Як скачати Відео або Звук (MP3):**\n"
        "1. Скопіюйте посилання на відео з TikTok, Instagram чи Shorts.\n"
        "2. Просто надішліть це посилання сюди в чат.\n"
        "3. Обов'язково підпишіться на наш офіційний канал [🪄 Магія TikReels | Завантажувач](https://t.me).\n"
        "4. Обери кнопку `🎬 Video` або `🎵 Audio`!\n\n"
        "📊 **Система лімітів:**\n"
        "На старті ти отримуєш **3 безкоштовні магії** ✨. Після їх вичерпання ти будеш отримувати **1 безкоштовне завантаження кожного нового дня**! Для повного безліміту тисни [☕️ Купити Premium](https://google.com) (тимчасове посилання).\n\n"
        "📸 **Фото-Каруселі TikTok:**\n"
        "Надішли посилання на фото-пост. Бот автоматично витягне всі картинки в HD та надішле альбомом!\n\n"
        "💬 **Зв'язок з розробником:**\n"
        "Якщо у тебе виникли питання — тисни кнопку `✍️ Support` прямо в головному меню!\n\n"
        "-----------------------------------------\n\n"
        "🇬🇧 **MAGIC MANUAL:**\n\n"
        "💥 **Video or Sound (MP3):**\n"
        "Send a video link. Subscribe to our channel [🪄 TikReels Wizard Club](https://t.me). Choose `🎬 Video` or `🎵 Audio`!\n\n"
        "📊 **Limit System:**\n"
        "Get **3 free downloads** at start ✨. Then you get **1 free download every new day**!",
        reply_markup=get_back_keyboard(),
        parse_mode="Markdown",
        disable_web_page_preview=True
    )


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

    ydl_opts = {
        'quiet': True,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
    }

    if mode == "video":
        ydl_opts['outtmpl'] = f"final_{user_id}.mp4"
    elif mode == "audio":
        ydl_opts['outtmpl'] = f"final_{user_id}.mp3"
        ydl_opts['format'] = 'bestaudio/best'
    elif mode == "auto":
        ydl_opts['outtmpl'] = f"media_{user_id}_%(pickle_index)s.%(ext)s"

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info.get('entries') or info.get('type') == 'playlist' or (
                    'requested_downloads' in info and info['requested_downloads'].get('ext') in ['jpg', 'png']):
                photos = [InputMediaPhoto(media=open(f, 'rb')) for f in os.listdir('.') if
                          f.startswith(f"media_{user_id}")]
                if photos:
                    await message_obj.reply_media_group(media=photos)
                    for f in os.listdir('.'):
                        if f.startswith(f"media_{user_id}"): os.remove(f)
                await status_msg.delete()
                reduce_attempt(user_id)
                return

        if mode == "video" and os.path.exists(f"final_{user_id}.mp4"):
            from aiogram.types import FSInputFile
            video_file = FSInputFile(f"final_{user_id}.mp4")
            await message_obj.reply_video(video=video_file, caption="Your video is ready! / Видео готово!")
        elif mode == "audio" and os.path.exists(f"final_{user_id}.mp3"):
            from aiogram.types import FSInputFile
            audio_file = FSInputFile(f"final_{user_id}.mp3")
            await message_obj.reply_audio(audio=audio_file, caption="Your audio is ready! / Аудио готово!")

        await status_msg.delete()
        reduce_attempt(user_id)
        await bot.send_message(chat_id=ADMIN_ID, text=f"📥 Успішно ({mode})!\nЮзер: {user_id}\nЛінк: {url}")

    except Exception as e:
        await status_msg.edit_text(
            "🇺🇦 Ой, магія дала збій... Перевір посилання або спробуй ще раз! ❌\n🇬🇧 Oops, magic failed... Check the link or try again! ❌")
        print(f"Помилка відправки: {e}")
    finally:
        if os.path.exists(f"final_{user_id}.mp4"): os.remove(f"final_{user_id}.mp4")
        if os.path.exists(f"final_{user_id}.mp3"): os.remove(f"final_{user_id}.mp3")
        if user_id in user_urls: del user_urls[user_id]


# ==================== АВТОМАТИЧНИЙ ПРИЙОМ ПЛАТЕЖІВ (WEBHOOKS) ====================
@app.post("/webhook/wayforpay")
async def wayforpay_webhook(request: Request):
    try:
        data = await request.json()
        status = data.get("transactionStatus")
        reason = data.get("reasonCode")
        order_id = data.get("orderReference")
        if status == "Approved" and reason == 1100:
            if "Premium" in order_id:
                user_id = int(order_id.split("_")[-1])
                set_premium_days(user_id, 30)
                await bot.send_message(chat_id=user_id,
                                       text="🇺🇦 👑 **Дякуємо за оплату!** Автоматично активовано Premium на 30 днів без лімітів!\n🇬🇧 👑 **Thank you!** Premium activated for 30 days!")
                await bot.send_message(chat_id=ADMIN_ID,
                                       text=f"💳 Авто-оплата WayForPay! Юзер `{user_id}` отримав Premium на місяць.")
        return Response(content='{"status":"accept"}', media_type="application/json")
    except:
        return Response(content='{"status":"error"}', media_type="application/json")


@app.post("/webhook/destream")
async def destream_webhook(request: Request):
    try:
        data = await request.json()
        if data.get("status") == "success" or data.get("action") == "donate":
            comment = data.get("comment", "")
            if "premium_" in comment:
                user_id = int(comment.replace("premium_", "").strip())
                set_premium_days(user_id, 30)
                await bot.send_message(chat_id=user_id,
                                       text="🇺🇦 👑 **Дякуємо!** Міжнародний платіж успішний. Premium активовано на 30 днів!\n🇬🇧 👑 **Success!** Premium activated for 30 days!")
                await bot.send_message(chat_id=ADMIN_ID,
                                       text=f"💳 Авто-оплата DeStream! Іноземець `{user_id}` купив Premium за $2.")
            elif "coffee_" in comment:
                user_id = int(comment.replace("coffee_", "").strip())
                await bot.send_message(chat_id=user_id,
                                       text="🇺🇦 ☕️ **Дякуємо за чашечку кави!** Твоя підтримка робить нашого Чарівника кращим!\n🇬🇧 ☕️ **Thank you for the coffee!** Your support is amazing!")
                await bot.send_message(chat_id=ADMIN_ID, text=f"☕️ Донат на каву від юзера `{user_id}` через DeStream!")
        return {"status": "ok"}
    except:
        return {"status": "error"}


@app.on_event("startup")
async def on_startup():
    init_db()
    asyncio.create_task(dp.start_polling(bot))
    print("Ультимативна автоматична грошова машина CodeOfFreedom запущена!")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=10000)
