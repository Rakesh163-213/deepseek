import os
import re
import logging
import sqlite3
import asyncio
import time
from config import API_ID, API_HASH, BOT_TOKEN, ADMINS

from pyrogram import Client, filters
from pyrogram.types import (
    Message, 
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from yt_dlp import YoutubeDL
from pathlib import Path
import aiohttp
import humanize
import shutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Database setup
conn = sqlite3.connect('userdata.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users
             (user_id INTEGER PRIMARY KEY, thumbnail TEXT)''')
conn.commit()

app = Client("url_upload_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Global variables
SPLIT_SIZE = 2 * 1024 * 1024 * 1024 - 10485760  # 2GB minus 10MB buffer
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Animation configurations
PROGRESS_BLOCKS = ["🟥", "🟧", "🟨", "🟩"]
SPINNER = ["🌀", "🌪️", "🌊", "🌌", "🌠", "✨"]
ANIMATION_DELAY = 0.5

# Enhanced yt-dlp configuration
YDL_OPTS = {
    'noplaylist': True,
    'quiet': True,
    'no_warnings': False,
    'force_generic_extractor': True,
    'cookiefile': 'cookies.txt',
    'nocheckcertificate': True,
    'referer': 'https://www.google.com/',
    'concurrent_fragment_downloads': 8,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Sec-Fetch-Mode': 'navigate',
        'DNT': '1'
    }
}

async def safe_edit(message, text):
    """Safe message editing with enhanced error handling"""
    try:
        if message and not message.empty:
            await message.edit_text(text)
    except Exception as e:
        logger.warning(f"Safe edit failed: {str(e)}")

async def progress(current, total, message, start_time):
    if total in (0, None) or not message:
        return
    
    try:
        percentage = min(current * 100 / total, 100)
        speed = current / (time.time() - start_time)
        eta = (total - current) / speed if speed != 0 else 0
        
        # Animated progress bar
        bar_index = int(time.time() / ANIMATION_DELAY) % len(PROGRESS_BLOCKS)
        filled = int(percentage / 10)
        progress_bar = (PROGRESS_BLOCKS[bar_index] * filled) + "⬜" * (10 - filled)
        
        # Spinner animation
        spinner = SPINNER[int(time.time() / ANIMATION_DELAY) % len(SPINNER)]
        
        text = (
            f"{spinner} **Uploading...** {spinner}\n\n"
            f"📊 **Progress:** {progress_bar} {int(percentage)}%\n"
            f"📦 **Size:** {humanize.naturalsize(current)} / {humanize.naturalsize(total)}\n"
            f"🚀 **Speed:** {humanize.naturalsize(speed)}/s\n"
            f"⏳ **ETA:** {humanize.precisedelta(eta)}"
        )
        
        await safe_edit(message, text)
    except Exception as e:
        logger.warning(f"Progress update failed: {str(e)}")

async def direct_download(url, message):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                filename = os.path.basename(url.split("?")[0]) or "file"
                filepath = os.path.join(DOWNLOAD_DIR, filename)
                
                with open(filepath, 'wb') as f:
                    async for chunk in response.content.iter_chunked(1024*1024):
                        f.write(chunk)
                
                return filepath
    except Exception as e:
        raise Exception(f"Direct download failed: {str(e)}")

async def ytdlp_download(url, message, format_id=None):
    try:
        ydl_opts = YDL_OPTS.copy()
        if format_id:
            ydl_opts['format'] = format_id
            
        with YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, url, download=False)
            if 'entries' in info:
                info = info['entries'][0]
                
            filename = ydl.prepare_filename(info)
            await safe_edit(message, f"📥 Downloading: {os.path.basename(filename)}")
            await asyncio.to_thread(ydl.download, [url])
            return filename
    except Exception as e:
        raise Exception(f"YT-DLP error: {str(e)}")

async def get_formats(url):
    try:
        with YoutubeDL(YDL_OPTS) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, url, download=False)
            if 'entries' in info:
                info = info['entries'][0]
                
            formats = []
            for f in info.get('formats', []):
                if f.get('filesize') or f.get('filesize_approx'):
                    size = f.get('filesize') or f.get('filesize_approx')
                    size_str = humanize.naturalsize(size)
                    res = f.get('height') or f.get('format_note', 'N/A')
                    codec = (f.get('vcodec') or 'N/A').split('.')[0]
                    formats.append((
                        f['format_id'],
                        f"🎬 {res}p | 📦 {size_str} | ⚡ {codec}"
                    ))
            return sorted(formats, key=lambda x: x[1], reverse=True)[:8]
    except Exception as e:
        logger.error(f"Format fetch error: {str(e)}")
        return []

@app.on_callback_query(filters.regex(r"^format_"))
async def format_selection(client, callback_query: CallbackQuery):
    try:
        _, url = callback_query.data.split("|", 1)
        await safe_edit(callback_query.message, "🌀 Fetching available formats...")
        formats = await get_formats(url)
        
        if not formats:
            return await safe_edit(callback_query.message, "❌ No formats found, starting default download...")

        keyboard = [
            [InlineKeyboardButton(
                text=f"✨ {format_text} ✨",
                callback_data=f"confirm_{url}|{format_id}"
            )] for format_id, format_text in formats
        ]
        
        await safe_edit(callback_query.message,
            "🎥 **Select Video Quality:**",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        await safe_edit(callback_query.message, f"❌ Error: {str(e)}")

@app.on_callback_query(filters.regex(r"^confirm_"))
async def confirm_download(client, callback_query: CallbackQuery):
    try:
        _, url, format_id = callback_query.data.split("|", 2)
        await safe_edit(callback_query.message, "🚀 Starting download...")
        await handle_download(callback_query.message, url, format_id)
    except Exception as e:
        await safe_edit(callback_query.message, f"❌ Error: {str(e)}")

async def handle_download(message, url, format_id=None):
    msg = await message.reply("🔍 Analyzing URL...")
    try:
        # Always check for available formats first
        formats = await get_formats(url)
        
        if formats and not format_id:
            return await show_format_selector(message, url)
        
        if re.search(r'\.(mp4|mkv|avi|mov|webm|m3u8|ts)(\?|$)', url, re.I):
            file_path = await direct_download(url, msg)
        else:
            file_path = await ytdlp_download(url, msg, format_id)

        # File validation
        if not os.path.exists(file_path):
            raise FileNotFoundError("Download failed - file not found")
        
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise ValueError("Download failed - empty file")

        # Upload to user
        thumbnail = get_user_thumbnail(message.from_user.id)
        await upload_file(message, file_path, thumbnail)
        
        # Only delete message after successful upload
        await msg.delete()

    except Exception as e:
        await safe_edit(msg, f"❌ Error: {str(e)}")
        logger.error(f"Download error: {str(e)}")
        cleanup(file_path)
        # Delete error message after 30 seconds
        await asyncio.sleep(30)
        try:
            await msg.delete()
        except:
            pass

async def show_format_selector(message, url):
    formats = await get_formats(url)
    keyboard = [
        [InlineKeyboardButton(
            text=f"📺 {format_text}",
            callback_data=f"confirm_{url}|{format_id}"
        )] for format_id, format_text in formats
    ]
    
    await message.reply(
        "🎥 **Available Video Qualities:**",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def upload_file(message, file_path, thumbnail):
    file_size = os.path.getsize(file_path)
    start_time = time.time()
    
    if file_size > SPLIT_SIZE:
        files = split_file(file_path)
        for part in files:
            await upload_part(message, part, thumbnail, start_time)
    else:
        await upload_part(message, file_path, thumbnail, start_time)

async def upload_part(message, part_path, thumbnail, start_time):
    try:
        await message.reply_document(
            document=part_path,
            thumb=thumbnail,
            caption=f"📁 {os.path.basename(part_path)}",
            progress=progress,
            progress_args=(message, start_time)
        )
    finally:
        cleanup(part_path)

def split_file(file_path):
    split_files = []
    part_num = 1
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(SPLIT_SIZE)
            if not chunk:
                break
            part_file = f"{file_path}.part{part_num:03d}"
            with open(part_file, 'wb') as p:
                p.write(chunk)
            split_files.append(part_file)
            part_num += 1
    os.remove(file_path)
    return split_files

def cleanup(file_path):
    try:
        if file_path and os.path.exists(file_path):
            if os.path.isdir(file_path):
                shutil.rmtree(file_path)
            else:
                os.remove(file_path)
    except Exception as e:
        logger.error(f"Cleanup error: {str(e)}")

def get_user_thumbnail(user_id):
    try:
        c.execute("SELECT thumbnail FROM users WHERE user_id=?", (user_id,))
        result = c.fetchone()
        return result[0] if result else None
    except sqlite3.Error as e:
        logger.error(f"Database error: {str(e)}")
        return None

# Command handlers
@app.on_message(filters.command(["start"]))
async def start(client, message):
    await message.reply_text(
        "🌟 **Welcome to the Advanced URL Upload Bot!** 🌟\n\n"
        "Send me any HTTP/HTTPS link to upload content!\n\n"
        "🔧 **Commands:**\n"
        "/start - Show this message\n"
        "/setthumbnail - Set a custom thumbnail\n"
        "/delthumbnail - Delete your thumbnail\n"
        "/help - Show help guide"
    )

@app.on_message(filters.command(["help"]))
async def help(client, message):
    await message.reply_text(
        "📚 **Help Guide**\n\n"
        "1. Send any HTTP/HTTPS link to upload content.\n"
        "2. Use /setthumbnail to set a custom thumbnail.\n"
        "3. Use /delthumbnail to remove your thumbnail.\n"
        "4. For direct links, the bot will automatically download and upload.\n"
        "5. For supported sites, you'll get quality options to choose from."
    )

@app.on_message(filters.command(["setthumbnail"]))
async def set_thumbnail(client, message):
    if message.reply_to_message and message.reply_to_message.photo:
        user_id = message.from_user.id
        thumbnail_path = f"thumbnails/{user_id}.jpg"
        os.makedirs(os.path.dirname(thumbnail_path), exist_ok=True)
        await message.reply_to_message.download(thumbnail_path)
        c.execute("INSERT OR REPLACE INTO users VALUES (?, ?)", (user_id, thumbnail_path))
        conn.commit()
        await message.reply_text("✅ Thumbnail set successfully!")
    else:
        await message.reply_text("❌ Please reply to a photo to set as thumbnail")

@app.on_message(filters.command(["delthumbnail"]))
async def del_thumbnail(client, message):
    user_id = message.from_user.id
    c.execute("DELETE FROM users WHERE user_id=?", (user_id,))
    conn.commit()
    await message.reply_text("✅ Thumbnail deleted successfully!")


@app.on_message(filters.text & filters.private & ~filters.create(lambda _, __, m: m.text.startswith("/")))
async def handle_url(client, message: Message):
    url = message.text.strip()
    if not re.match(r'^https?://', url, re.I):
        return await message.reply_text("❌ Invalid URL format")
    
    await handle_download(message, url)

if __name__ == "__main__":
    app.run()
