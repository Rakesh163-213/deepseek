from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import yt_dlp
import os
import ffmpeg
import shutil
import time
from threading import Thread
from math import floor
from datetime import datetime

# Telegram bot credentials
API_ID = '20967612'
API_HASH = 'be9356a3644d1e6212e72d93530b434f'
BOT_TOKEN = '7535985391:AAEfjYY3Z79OvPgQCn3rKZ192jAED9dzeHQ'

app = Client("url_uploader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Global variables for tracking progress
progress_data = {}
download_speeds = {}

# Thumbnail management
THUMBNAIL_PATH = 'thumbnail.jpg'

# Command to set custom thumbnail
@app.on_message(filters.command("setthumbnail"))
async def set_thumbnail(client, message: Message):
    if message.reply_to_message and (message.reply_to_message.photo or message.reply_to_message.document):
        try:
            await message.reply_to_message.download(file_name=THUMBNAIL_PATH)
            await message.reply("✅ Custom thumbnail set successfully!", parse_mode=enums.ParseMode.MARKDOWN)
        except Exception as e:
            await message.reply(f"❌ Error setting thumbnail: {str(e)}")
    else:
        await message.reply("ℹ️ Please reply to a photo or document to set as thumbnail")

# Command to delete custom thumbnail
@app.on_message(filters.command("delthumbnail"))
async def delete_thumbnail(client, message: Message):
    if os.path.exists(THUMBNAIL_PATH):
        os.remove(THUMBNAIL_PATH)
        await message.reply("✅ Custom thumbnail deleted!")
    else:
        await message.reply("ℹ️ No custom thumbnail found!")

# Progress handler for downloads
async def download_progress_hook(d, message, start_time):
    global progress_data, download_speeds
    if d['status'] == 'downloading':
        chat_id = message.chat.id
        downloaded = d.get('downloaded_bytes', 0)
        total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
        speed = d.get('speed', 0)
        elapsed = time.time() - start_time
        
        # Calculate progress
        percent = (downloaded / total) * 100 if total else 0
        progress = "▓" * int(percent // 5) + "░" * (20 - int(percent // 5))
        
        # Calculate speed and ETA
        speed = f"{speed / 1024 / 1024:.2f} MB/s" if speed else "N/A"
        eta = (total - downloaded) / (d['speed'] + 1) if d.get('speed') else 0
        eta_str = str(datetime.utcfromtimestamp(eta).strftime('%H:%M:%S')) if eta else "N/A"
        
        # Update progress message every 5 seconds
        current_time = time.time()
        if chat_id not in progress_data or current_time - progress_data[chat_id]['last_update'] >= 5:
            try:
                await message.edit_text(
                    f"**Downloading:**\n"
                    f"`{progress}` {percent:.2f}%\n"
                    f"**Size:** {downloaded/1024/1024:.2f}MB / {total/1024/1024:.2f}MB\n"
                    f"**Speed:** {speed}\n"
                    f"**ETA:** {eta_str}"
                )
                progress_data[chat_id] = {'last_update': current_time}
            except:
                pass

# Enhanced download function with progress tracking
def download_media(url, format_id, message):
    chat_id = message.chat.id
    msg = None
    try:
        # Create downloads directory
        os.makedirs('downloads', exist_ok=True)
        
        # Get format information
        ydl_opts = {
            'format': format_id,
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'progress_hooks': [lambda d: download_progress_hook(d, msg, start_time)],
            'noplaylist': True,
            'quiet': True,
        }

        with yt_dlp.YoutubeDL(ydp_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            
        return file_path

    except Exception as e:
        app.send_message(chat_id, f"❌ Download failed: {str(e)}")
        return None

# Upload progress callback
async def upload_progress(current, total, message, start_time):
    percent = (current / total) * 100
    progress = "▓" * int(percent // 5) + "░" * (20 - int(percent // 5))
    elapsed = time.time() - start_time
    speed = current / elapsed / 1024 / 1024 if elapsed > 0 else 0
    eta = (total - current) / (speed * 1024 * 1024 + 1) if speed > 0 else 0
    
    try:
        await message.edit_text(
            f"**Uploading:**\n"
            f"`{progress}` {percent:.2f}%\n"
            f"**Sent:** {current/1024/1024:.2f}MB / {total/1024/1024:.2f}MB\n"
            f"**Speed:** {speed:.2f} MB/s\n"
            f"**ETA:** {datetime.utcfromtimestamp(eta).strftime('%H:%M:%S')}"
        )
    except:
        pass

# Main processing function
def process_media(url, format_id, message):
    chat_id = message.chat.id
    try:
        # Start download
        file_path = download_media(url, format_id, message)
        if not file_path:
            return

        # Split video if needed
        if os.path.getsize(file_path) > 2 * 1024 * 1024 * 1024:
            file_path = split_video(file_path)

        # Prepare thumbnail
        thumbnail = THUMBNAIL_PATH if os.path.exists(THUMBNAIL_PATH) else None

        # Start upload with progress
        start_time = time.time()
        msg = app.send_message(chat_id, "📤 Starting upload...")
        
        app.send_video(
            chat_id=chat_id,
            video=file_path,
            caption=os.path.basename(file_path),
            thumb=thumbnail,
            progress=lambda current, total: upload_progress(current, total, msg, start_time)
        )

        # Cleanup
        os.remove(file_path)
        app.delete_messages(chat_id, msg.id)

    except Exception as e:
        app.send_message(chat_id, f"❌ Error: {str(e)}")

# Video splitting function
def split_video(input_path):
    output_dir = 'downloads/split_videos'
    os.makedirs(output_dir, exist_ok=True)
    output_template = os.path.join(output_dir, 'part_%03d.mp4')
    
    (
        ffmpeg
        .input(input_path)
        .output(output_template, segment_time=1800, f='segment', reset_timestamps=1)
        .run(quiet=True)
    )
    
    os.remove(input_path)
    return os.path.join(output_dir, 'part_001.mp4')

# Format selection handler
@app.on_callback_query()
async def handle_format_selection(client, callback_query: CallbackQuery):
    await callback_query.answer()
    url = callback_query.message.reply_to_message.text
    format_id = callback_query.data
    
    # Delete format selection message
    await callback_query.message.delete()
    
    # Start processing in a new thread
    Thread(target=process_media, args=(url, format_id, callback_query.message)).start()

# URL handler with vertical quality buttons
@app.on_message(filters.text & filters.private)
async def handle_url(client, message: Message):
    url = message.text
    try:
        # Get available formats
        ydl_opts = {'quiet': True, 'noplaylist': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [info])
        
        # Create vertical buttons
        buttons = []
        for f in reversed(formats):
            if f.get('height'):
                text = f"{f['format_note']} ({f['ext']}) {f['filesize']/1024/1024:.1f}MB" if 'format_note' in f else f"{f['height']}p ({f['ext']}) {f['filesize']/1024/1024:.1f}MB"
                buttons.append([InlineKeyboardButton(text, callback_data=f['format_id'])])
        
        # Add audio options
        audio_formats = [f for f in formats if f['vcodec'] == 'none']
        for f in audio_formats:
            text = f"Audio ({f['ext']}) {f['filesize']/1024/1024:.1f}MB"
            buttons.append([InlineKeyboardButton(text, callback_data=f['format_id'])])
        
        # Send format selection
        await message.reply(
            "🎬 Select format:",
            reply_markup=InlineKeyboardMarkup(buttons),
            reply_to_message_id=message.id
        )

    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

# Start command
@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    await message.reply(
        "📥 Welcome to YouTube Downloader Bot!\n\n"
        "Send me a YouTube URL to get started.\n\n"
        "🛠 Commands:\n"
        "/setthumbnail - Set custom thumbnail\n"
        "/delthumbnail - Delete thumbnail\n"
        "/help - Show help information"
    )

# Help command
@app.on_message(filters.command("help"))
async def help_command(client, message: Message):
    await message.reply(
        "ℹ️ **Bot Help**\n\n"
        "1. Send any YouTube URL\n"
        "2. Choose desired format\n"
        "3. Wait for download & upload\n\n"
        "🖼 Thumbnail Support:\n"
        "- Reply to an image with /setthumbnail\n"
        "- Use /delthumbnail to remove\n\n"
        "⚡ Features:\n"
        "- 2GB+ file splitting\n"
        "- Progress tracking\n"
        "- Quality selection\n"
        "- Audio extraction"
    )

if __name__ == "__main__":
    print("Bot Started!")
    app.run()
