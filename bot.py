import os
import re
import logging
import sqlite3
import asyncio
import time
from config import API_ID, API_HASH, BOT_TOKEN, LOG_CHANNEL, ADMINS

from pyrogram import Client, filters
from pyrogram.types import (
    Message, 
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from yt_dlp import YoutubeDL
from pathlib import Path
import requests
import humanize
import shutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Database setup
conn = sqlite3.connect('userdata.db')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users
             (user_id INTEGER PRIMARY KEY, thumbnail TEXT)''')
conn.commit()

app = Client("url_upload_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Global variables
SPLIT_SIZE = 2 * 1024 * 1024 * 1024 - 10485760  # 2GB minus 10MB buffer
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Emoji and animation configurations
EMOJI_PROGRESS = ["🟥", "🟧", "🟨", "🟩", "🟦", "🟪"]
SPINNER = ["🌀", "🌪️", "🌊", "🌌", "🌠", "✨"]
ANIMATION_DELAY = 0.5  # Delay between animation frames

# Optimized yt-dlp configuration for speed
YDL_OPTS = {
    'noplaylist': True,
    'quiet': True,
    'no_warnings': False,
    'force_generic_extractor': True,
    'cookiefile': 'cookies.txt',
    'nocheckcertificate': True,
    'concurrent_fragment_downloads': 8,  # Parallel downloads
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': '*/*',
    }
}

async def progress(current, total, message, start_time):
    if total in (0, None):
        return
    
    percentage = current * 100 / total
    speed = current / (time.time() - start_time)
    eta = (total - current) / speed if speed != 0 else 0
    
    # Animated progress bar
    progress_bar = "".join(
        EMOJI_PROGRESS[i] if i < int(percentage / 10) else "⬜"
        for i in range(10)
    )
    
    # Spinner animation
    spinner = SPINNER[int(time.time() / ANIMATION_DELAY) % len(SPINNER)]
    
    text = (
        f"{spinner} **Uploading...** {spinner}\n\n"
        f"📊 **Progress:** {progress_bar} {int(percentage)}%\n"
        f"📦 **Size:** {humanize.naturalsize(current)} / {humanize.naturalsize(total)}\n"
        f"🚀 **Speed:** {humanize.naturalsize(speed)}/s\n"
        f"⏳ **ETA:** {humanize.precisedelta(eta)}"
    )
    
    try:
        await message.edit_text(text)
    except Exception as e:
        logger.warning(f"Progress update failed: {str(e)}")

@app.on_message(filters.command(["start"]))
async def start(client, message):
    await message.reply_text(
        "🌟 **Hi! I'm Advanced URL Upload Bot** 🌟\n\n"
        "📥 Send me any HTTP/HTTPS link to upload content!\n\n"
        "✨ **Features:**\n"
        "- 🎥 Quality Selection\n"
        "- ⚡ High Speed Downloads\n"
        "- 📂 Log Channel Support\n"
        "- 🖼️ Thumbnail Management\n\n"
        "🔧 **Commands:**\n"
        "/setthumbnail - Set custom thumbnail\n"
        "/delthumbnail - Delete thumbnail\n"
        "/logchannel - Set log channel (admin)\n"
        "/stats - Bot statistics (admin)"
    )

# Thumbnail management commands remain the same

@app.on_callback_query(filters.regex(r"^format_"))
async def format_selection(client, callback_query: CallbackQuery):
    try:
        _, url, format_id = callback_query.data.split("|", 2)
        await callback_query.message.edit_text("🌀 Processing your quality selection...")
        await handle_download(callback_query.message, url, format_id)
    except Exception as e:
        await callback_query.message.edit_text(f"❌ Error: {str(e)}")
        logger.error(f"Format selection error: {str(e)}")

async def get_formats(url):
    try:
        with YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            for f in info.get('formats', []):
                if f.get('filesize'):
                    size = humanize.naturalsize(f['filesize'])
                    res = f.get('format_note') or f.get('height', 'N/A')
                    formats.append((
                        f['format_id'],
                        f"🎬 {res}p | 📦 {size} | ⚡ {f.get('ext', 'N/A')}"
                    ))
            return formats
    except Exception as e:
        logger.error(f"Format fetch error: {str(e)}")
        return []

async def handle_download(message, url, format_id=None):
    user_id = message.from_user.id
    msg = await message.reply_text("🚀 Starting download...")
    
    try:
        ydl_opts = YDL_OPTS.copy()
        if format_id:
            ydl_opts['format'] = format_id
        
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            filename = ydl.prepare_filename(info)
            await msg.edit_text(f"⬇️ Downloading: {os.path.basename(filename)}")
            ydl.download([url])
            
            file_path = filename
            if not os.path.exists(file_path):
                raise FileNotFoundError("Downloaded file not found")
            
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                raise ValueError("Downloaded file is empty")
            
            # Upload and logging logic remains similar
            try:
                if LOG_CHANNEL:
                    await client.send_message(
                        LOG_CHANNEL,
                        f"📥 **New Download**\n"
                        f"👤 **User:** {message.from_user.mention}\n"
                        f"🔗 **URL:** {url}\n"
                        f"📁 **File:** {os.path.basename(file_path)}\n"
                        f"📦 **Size:** {humanize.naturalsize(file_size)}"
                    )
                    await client.send_document(
                        LOG_CHANNEL,
                        document=file_path,
                        caption=f"📥 **Logged Content**"
                    )
            except Exception as log_error:
                logger.error(f"Log channel error: {str(log_error)}")
            
            # Rest of upload logic
            
    except Exception as e:
        await msg.edit_text(f"❌ Error: {str(e)}")
        logger.error(f"Download error: {str(e)}")

@app.on_message(filters.text & filters.private & ~filters.create(lambda _, __, m: m.text.startswith("/")))
async def handle_url(client, message: Message):
    url = message.text.strip()
    formats = await get_formats(url)
    
    if not formats:
        return await message.reply_text("❌ No supported formats found for this URL")
    
    keyboard = []
    for format_id, format_text in formats[:10]:  # Max 10 options
        keyboard.append([
            InlineKeyboardButton(
                format_text,
                callback_data=f"format_{url}|{format_id}"
            )
        ])
    
    await message.reply_text(
        "🎥 **Select Video Quality:**",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

@app.on_message(filters.command(["logchannel"]) & filters.user(ADMINS))
async def set_log_channel(client, message):
    try:
        if message.chat.type in ["channel", "supergroup"]:
            global LOG_CHANNEL
            LOG_CHANNEL = message.chat.id
            await message.reply_text(f"✅ Log channel set to: {message.chat.title}")
            # Verify bot permissions
            chat = await client.get_chat(LOG_CHANNEL)
            if not chat.permissions.can_send_messages:
                await message.reply_text("⚠️ Warning: Bot needs message permissions in the log channel!")
        else:
            await message.reply_text("❌ Please use this command in the target channel/supergroup")
    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}")

@app.on_message(filters.command(["stats"]) & filters.user(ADMINS))
async def bot_stats(client, message):
    stats = f"📊 **Bot Statistics**\n\n"\
            f"👥 **Total Users:** {get_user_count()}\n"\
            f"💾 **Database Size:** {humanize.naturalsize(get_db_size())}\n"\
            f"📁 **Downloads Folder:** {humanize.naturalsize(get_folder_size(DOWNLOAD_DIR))}"
    await message.reply_text(stats)

def get_user_count():
    c.execute("SELECT COUNT(*) FROM users")
    return c.fetchone()[0]

def get_db_size():
    return os.path.getsize('userdata.db')

def get_folder_size(path):
    total = 0
    for entry in os.scandir(path):
        if entry.is_file():
            total += entry.stat().st_size
        elif entry.is_dir():
            total += get_folder_size(entry.path)
    return total

if __name__ == "__main__":
    app.run()
