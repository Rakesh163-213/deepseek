import os
import re
import logging
import sqlite3
import asyncio
import time
from config import API_ID, API_HASH, BOT_TOKEN, LOG_CHANNEL, ADMINS

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
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

async def progress(current, total, message, start_time):
    if total in (0, None):
        return  # Avoid division by zero errors
    
    percentage = current * 100 / total
    speed = current / (time.time() - start_time)
    eta = (total - current) / speed if speed != 0 else 0
    
    progress_bar = "[{0}{1}]".format(
        '■' * int(percentage / 5),
        '□' * (20 - int(percentage / 5))
    )
    
    text = (
        f"Progress: {progress_bar}\n"
        f"Size: {humanize.naturalsize(current)} / {humanize.naturalsize(total)}\n"
        f"Speed: {humanize.naturalsize(speed)}/s\n"
        f"ETA: {humanize.precisedelta(eta)}"
    )
    
    try:
        await message.edit_text(text)
    except Exception as e:
        logger.warning(f"Progress update failed: {str(e)}")

@app.on_message(filters.command(["start"]))
async def start(client, message):
    await message.reply_text(
        "**Hi! I'm URL Upload Bot**\n"
        "Send me any HTTP/HTTPS link to upload content!\n\n"
        "**Commands:**\n"
        "/setthumbnail - Set custom thumbnail\n"
        "/delthumbnail - Delete thumbnail\n"
        "/logchannel - Set log channel (admin only)"
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
        await message.reply_text("Thumbnail set successfully!")
    else:
        await message.reply_text("Please reply to a photo to set as thumbnail")

@app.on_message(filters.command(["delthumbnail"]))
async def del_thumbnail(client, message):
    user_id = message.from_user.id
    c.execute("DELETE FROM users WHERE user_id=?", (user_id,))
    conn.commit()
    await message.reply_text("Thumbnail deleted successfully!")

def get_user_thumbnail(user_id):
    c.execute("SELECT thumbnail FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    return result[0] if result else None

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
    return split_files

async def download_content(url, message):
    ydl_opts = {
        'outtmpl': f'{DOWNLOAD_DIR}/%(title)s.%(ext)s',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': False,
        'force_generic_extractor': True,
        'cookiefile': 'cookies.txt',
        'referer': url,
        'nocheckcertificate': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': '*/*',
        }
    }
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            filename = ydl.prepare_filename(info)
            await message.edit_text(f"Downloading: {os.path.basename(filename)}")
            ydl.download([url])
            return filename
    except Exception as e:
        raise Exception(f"Download failed: {str(e)}")

@app.on_message(filters.text & filters.private & ~filters.create(lambda _, __, m: m.text.startswith("/")))
async def handle_url(client, message: Message):
    user_id = message.from_user.id
    url = message.text.strip()
    msg = await message.reply_text("Processing your request...")
    
    try:
        # Validate URL
        if not re.match(r'^https?://', url, re.IGNORECASE):
            raise ValueError("Invalid URL format")
        
        # Download content
        file_path = await download_content(url, msg)
        
        # Validate downloaded file
        if not os.path.exists(file_path):
            raise FileNotFoundError("Downloaded file not found")
        
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise ValueError("Downloaded file is empty")
        
        # Split file if needed
        files_to_upload = [file_path]
        if file_size > SPLIT_SIZE:
            files_to_upload = split_file(file_path)
        
        # Upload files
        thumbnail = get_user_thumbnail(user_id)
        for file in files_to_upload:
            await client.send_document(
                chat_id=message.chat.id,
                document=file,
                thumb=thumbnail,
                caption=f"`{Path(file).name}`",
                progress=progress,
                progress_args=(msg, time.time())
            )
            os.remove(file)
        
        # Log to channel
        if LOG_CHANNEL:
            await client.forward_messages(
                chat_id=LOG_CHANNEL,
                from_chat_id=message.chat.id,
                message_ids=message.message_id
            )
            await client.send_document(
                chat_id=LOG_CHANNEL,
                document=file_path,
                caption=f"User: {message.from_user.mention}\nURL: {url}"
            )
        
        await msg.delete()
        
    except Exception as e:
        await msg.edit_text(f"❌ Error: {str(e)}")
        logger.error(f"Error processing {url}: {str(e)}")
        try:
            shutil.rmtree(DOWNLOAD_DIR)
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        except Exception as clean_err:
            logger.error(f"Cleanup error: {str(clean_err)}")

@app.on_message(filters.command(["logchannel"]) & filters.user(ADMINS))
async def set_log_channel(client, message):
    global LOG_CHANNEL
    if message.chat.type == "channel":
        LOG_CHANNEL = message.chat.id
        await message.reply_text(f"Log channel set to {message.chat.id}")
    else:
        await message.reply_text("Please use this command in the channel you want to set as log channel")

if __name__ == "__main__":
    app.run()
