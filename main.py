import os
import asyncio
import sqlite3
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, \
    InputMediaPhoto
from fastapi import FastAPI, Request, Response
from yt_dlp import YoutubeDL

# ==================== НАЛАШТУВАННЯ СЕРВЕРА ТА БОТА ====================
BOT_TOKEN = "8888379212:AAGVdQsoXIeI9h5_2aXcjh18Kp0zrMqZTnc"  # Твій новий чистий токен від BotFather
ADMIN_ID = 906815308  # Твій ID адміна
DB_NAME = "database.db"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            lang_code TEXT,
            total_downloads INTEGER DEFAULT 0,
            premium_until TEXT DEFAULT NULL
        )
    """)
    conn.commit()
    conn.close()


def reduce_attempt(user_id: int):
    pass


def set_premium_days(user_id: int, days: int) -> str:
    from datetime import datetime, timedelta
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    end_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    cursor.execute("UPDATE users SET premium_until = ? WHERE user_id = ?", (end_date, user_id))
    conn.commit()
    conn.close()
    return end_date


# ==================== СЕКРЕТНА АДМІН-ПАНЕЛЬ (АНАЛІТИКА) ====================
def get_admin_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0] or 0
    cursor.execute("SELECT SUM(total_downloads) FROM users")
    total_downloads = cursor.fetchone()[0] or 0
    cursor.execute("SELECT lang_code, COUNT(*) FROM users GROUP BY lang_code ORDER BY COUNT(*) DESC")
    lang_rows = cursor.fetchall()
    cursor.execute("SELECT user_id FROM users ORDER BY user_id DESC LIMIT 5")
    recent_users = cursor.fetchall()
    recent_users_text = ""
    for u in recent_users:
        recent_users_text += f"• ID: `{u[0]}`\n"
    conn.close()

    lang_stats = ""
    for row in lang_rows:
        lang, count = row
        lang_stats += f"• 🌍 Мова [{lang}]: {count} користувачів\n"

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


@dp.message(F.text == "/xA4dcG")
async def cmd_admin(message: Message):
    if message.from_user.id == ADMIN_ID:
        stats = get_admin_stats()
        await message.answer(stats, parse_mode="Markdown")


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
        try:
            await bot.send_message(
                chat_id=target_id,
                text=f"🇺🇦 **Прийміть наші вибачення!** 🪄✨\n"
                     f"Розробник активував вам **{days} днів безкоштовного Premium-безліміту**! Дякуємо, що ви з нами! 🤝"
            )
        except:
            pass
    except:
        await message.answer("❌ Формат: `/give_premium ID ДНІ`")


@dp.message(lambda msg: (msg.text and msg.text.startswith("Розсилка:")) or (
        msg.caption and msg.caption.startswith("Розсилка:")))
async def admin_broadcast(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    is_photo = bool(message.photo)
    raw_text = message.caption if is_photo else message.text
    broadcast_text = raw_text.replace("Розсилка:", "").strip()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()

    await message.answer("📢 Запускаю масову рекламну розсилку...")
    success_count = 0
    photo_file_id = message.photo[-1].file_id if is_photo else None

    for user in users:
        try:
            if is_photo:
                await bot.send_photo(chat_id=user[0], photo=photo_file_id, caption=broadcast_text)
            else:
                await bot.send_message(chat_id=user[0], text=broadcast_text)
            success_count += 1
            await asyncio.sleep(0.05)
        except:
            continue
    await message.answer(f"📢 Розсилку завершено! Доставлено {success_count} користувачам.")


# ==================== ДВИЖОК СКАЧИВАНИЯ (FullHD БЕЗ ЗНАКОВ С FFmpeg) ====================
async def download_process(message_obj: Message, user_id: int, url: str, mode: str):
    status_msg = await message_obj.answer("🇺🇦 Магія починається... Запускаю ракету за файлами 🚀🔥")
    video_filename = f"final_{user_id}.mp4"
    audio_filename = f"final_{user_id}.mp3"

    ydl_opts = {
        'quiet': True,
        'format': 'bestvideo+bestaudio/best',
        'geo_bypass': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        }
    }
    if mode == "video":
        ydl_opts['outtmpl'] = video_filename
    elif mode == "audio":
        ydl_opts['outtmpl'] = audio_filename
        ydl_opts['format'] = 'bestaudio/best'

    try:
        with YoutubeDL(ydl_opts) as ydl:
            await asyncio.to_thread(ydl.extract_info, url, download=True)

        if mode == "video" and os.path.exists(video_filename):
            await message_obj.reply_video(video=FSInputFile(video_filename),
                                          caption="Your video is ready! / Відео готово! 🎬")
        elif mode == "audio" and os.path.exists(audio_filename):
            await message_obj.reply_audio(audio=FSInputFile(audio_filename),
                                          caption="Your audio is ready! / Аудіо готово! 🎵")
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text("❌ Ой, магія дала збій... Перевір посилання або спробуй ще раз!")
        print(f"Помилка завантаження: {e}")
    finally:
        if os.path.exists(video_filename): os.remove(video_filename)
        if os.path.exists(audio_filename): os.remove(audio_filename)


@dp.message(F.text.contains("tiktok.com") | F.text.contains("instagram.com") | F.text.contains("youtube.com"))
async def handle_links(message: Message):
    await download_process(message, message.from_user.id, message.text.strip(), "video")


@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    user_id = message.from_user.id
    user_lang = message.from_user.language_code or "en"
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username, lang_code) VALUES (?, ?, ?)",
                   (user_id, message.from_user.username, user_lang))
    conn.commit()
    conn.close()
    await message.answer("🇺🇦 **Вітаємо у TikReels Wizard!** Надішліть мені посилання!")
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=f"👤 **Новий користувач!**\nID: `{user_id}`\nМова: `{user_lang}`")
    except:
        pass


# ==================== ЧИСТІ СЕРВЕРНІ ВЕБХУКИ ДЛЯ RENDER ====================
@app.get("/")
async def root():
    return {"status": "alive"}

@app.post("/")
async def telegram_webhook(request: Request):
    try:
        json_str = await request.json()
        from aiogram.types import Update
        update = Update.model_validate(json_str, context={"bot": bot})
        await dp.feed_update(bot, update)
        return Response(content='{"status":"ok"}', media_type="application/json")
    except Exception as e:
        print(f"Помилка вебхука: {e}")
        return Response(content='{"status":"error"}', media_type="application/json")

@app.on_event("startup")
async def on_startup():
    init_db()
    # Бот сам при кожному старті зв'яжеться з Телеграмом і закриє всі конфлікти!
    await bot.set_webhook(url="https://onrender.com")
    print("Ультимативна машина CodeOfFreedom успішно запущена на Render через Вебхуки!")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
