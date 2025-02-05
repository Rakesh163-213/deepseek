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

# Enhanced yt-dlp configuration for adult sites
YDL_OPTS = {
    'noplaylist': True,
    'quiet': True,
    'no_warnings': False,
    'force_generic_extractor': True,
    'cookiefile': 'cookies.txt',
    'nocheckcertificate': True,
    'referer': 'https://www.google.com/',
    'concurrent_fragment_downloads': 8,
    'age_limit': 18,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Sec-Fetch-Mode': 'navigate',
        'DNT': '1'
    }
}

async def progress(current, total, message, start_time):
    if total in (0, None):
        return
    
    percentage = min(current * 100 / total, 100)
    speed = current / (time.time() - start_time)
    eta = (total - current) / speed if speed != 0 else 0
    
    progress_bar = "".join(
        "⬢" if i < int(percentage / 10) else "⬡" for i in range(10)
    )
    
    text = (
        f"<b>🚀 Progress:</b> {progress_bar} {int(percentage)}%\n"
        f"<b>📦 Size:</b> {humanize.naturalsize(current)} / {humanize.naturalsize(total)}\n"
        f"<b>⚡ Speed:</b> {humanize.naturalsize(speed)}/s\n"
        f"<b>⏳ ETA:</b> {humanize.precisedelta(eta)}"
    )
    
    try:
        await message.edit_text(text)
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
            await message.edit_text(f"⬇️ Downloading: {os.path.basename(filename)}")
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
                    formats.append((
                        f['format_id'],
                        f"🎬 {res}p | 📦 {size_str} | ⚡ {f.get('ext', 'N/A')}"
                    ))
            return formats
    except Exception as e:
        logger.error(f"Format fetch error: {str(e)}")
        return []

@app.on_callback_query(filters.regex(r"^format_"))
async def format_selection(client, callback_query: CallbackQuery):
    try:
        _, url = callback_query.data.split("|", 1)
        formats = await get_formats(url)
        
        keyboard = []
        for format_id, format_text in formats[:8]:
            keyboard.append([
                InlineKeyboardButton(
                    format_text,
                    callback_data=f"confirm_{url}|{format_id}"
                )
            ])
            
        await callback_query.message.edit_text(
            "🎥 Select Video Quality:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        await callback_query.message.edit_text(f"❌ Error: {str(e)}")

@app.on_callback_query(filters.regex(r"^confirm_"))
async def confirm_download(client, callback_query: CallbackQuery):
    try:
        _, url, format_id = callback_query.data.split("|", 2)
        await callback_query.message.edit_text("🌀 Starting download...")
        await handle_download(callback_query.message, url, format_id)
    except Exception as e:
        await callback_query.message.edit_text(f"❌ Error: {str(e)}")

async def handle_download(message, url, format_id=None):
    msg = await message.reply_text("🚀 Initializing download...")
    try:
        # Check for direct file link
        if re.search(r'\.(mp4|mkv|avi|mov|webm|m3u8|ts)(\?|$)', url, re.I):
            file_path = await direct_download(url, msg)
        else:
            if not format_id:
                formats = await get_formats(url)
                if not formats:
                    file_path = await ytdlp_download(url, msg)
                else:
                    return await show_format_selector(message, url)
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
        await msg.delete()

    except Exception as e:
        await msg.edit_text(f"❌ Error: {str(e)}")
        logger.error(f"Download error: {str(e)}")
        cleanup(file_path)

async def show_format_selector(message, url):
    formats = await get_formats(url)
    if not formats:
        return await message.reply_text("❌ No formats found, trying default download...")
    
    keyboard = []
    for format_id, format_text in formats[:8]:
        keyboard.append([
            InlineKeyboardButton(
                format_text,
                callback_data=f"confirm_{url}|{format_id}"
            )
        ])
    
    await message.reply_text(
        "🎥 Multiple formats available:",
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

async def upload_part(message, file_path, thumbnail, start_time):
    try:
        await message.reply_document(
            document=file_path,
            thumb=thumbnail,
            caption=f"📁 {os.path.basename(file_path)}",
            progress=progress,
            progress_args=(message, start_time)
        )
    finally:
        cleanup(file_path)

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
    c.execute("SELECT thumbnail FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    return result[0] if result else None

@app.on_message(filters.command(["start"]))
async def start(client, message):
    await message.reply_text(
        "🌟 **Advanced URL Upload Bot**\n\n"
        "Send any HTTP/HTTPS link to upload content!\n\n"
        "🔧 **Commands:**\n"
        "/setthumbnail - Set custom thumbnail\n"
        "/delthumbnail - Delete thumbnail\n"
        "/help - Show help guide"
    )

@app.on_message(filters.command(["setthumbnail"]))
async def set_thumbnail(client, message):
    user_id = message.from_user.id
    if message.reply_to_message and message.reply_to_message.photo:
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

@app.on_message(filters.text & filters.private & ~filters.command)
async def handle_url(client, message: Message):
    url = message.text.strip()
    if not re.match(r'^https?://', url, re.I):
        return await message.reply_text("❌ Invalid URL format")
    
    await handle_download(message, url)

if __name__ == "__main__":
    app.run()
