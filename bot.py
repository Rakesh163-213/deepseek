import os
import yt_dlp
import aiohttp
import time
import asyncio
from pyrogram import Client, filters
from humanize import naturalsize

# Replace with your API credentials
api_id = 20967612
api_hash = "be9356a3644d1e6212e72d93530b434f"
bot_token = "7535985391:AAEfjYY3Z79OvPgQCn3rKZ192jAED9dzeHQ"

app = Client("my_uploader", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

# Increase the chunk size to 1MB (1024 * 1024 bytes)
CHUNK_SIZE = 1024 * 1024  # 1MB

async def download_file(url, filename, msg):
    os.makedirs("downloads", exist_ok=True)  # Ensure downloads directory exists

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                await msg.edit(f"❌ Failed to download (HTTP {response.status})")
                return
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            start_time = time.time()
            
            try:
                with open(filename, 'wb') as f:
                    async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                        if not chunk:
                            await msg.edit("❌ Received an empty data chunk. Retrying...")
                            return
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        elapsed = time.time() - start_time
                        if elapsed >= 1 or downloaded == total_size:
                            speed = downloaded / elapsed if elapsed > 0 else 0
                            await update_download_progress(msg, downloaded, total_size, speed)
                            start_time = time.time()
            except Exception as e:
                await msg.edit(f"❌ Error writing file: {str(e)}")

async def update_download_progress(msg, downloaded, total, speed):
    if msg:
        progress = f"📥 Downloading:\n"
        progress += f"┌ {naturalsize(downloaded)} / {naturalsize(total)}\n"
        progress += f"├ {downloaded/total*100:.1f}% Complete\n"
        progress += f"└ Speed: {naturalsize(speed)}/s"
        await msg.edit(progress)

async def upload_with_progress(client, msg, filename):
    file_size = os.path.getsize(filename)
    uploaded = 0
    start_time = time.time()

    async def progress(current, total, msg):
        nonlocal uploaded, start_time
        uploaded = current
        elapsed = time.time() - start_time
        speed = current / elapsed if elapsed > 0 else 0
        
        progress_text = f"📤 Uploading:\n"
        progress_text += f"┌ {naturalsize(current)} / {naturalsize(total)}\n"
        progress_text += f"├ {current/total*100:.1f}% Complete\n"
        progress_text += f"└ Speed: {naturalsize(speed)}/s"
        
        if msg:
            await msg.edit(progress_text)
        start_time = time.time()

    await client.send_document(
        chat_id=msg.chat.id,
        document=filename,
        force_document=True,
        progress=progress,  
        progress_args=(msg,)  
    )

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply("Send me a URL to upload the file (up to 2GB)!")

@app.on_message(filters.text & ~filters.command("start"))
async def handle_url(client, message):
    url = message.text
    msg = None
    local_path = None
    
    try:
        # Extract file info
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            file_size = info_dict.get('filesize', 0) or 0
            if file_size > 2 * 1024 * 1024 * 1024:
                await message.reply("❌ File size exceeds 2GB limit.")
                return
            
            filename = info_dict.get('title', 'file').replace(' ', '_')
            if 'ext' in info_dict:
                filename += f".{info_dict['ext']}"
            else:
                filename += ".mp4"  # Default to mp4 if extension is not available
            filename = f"downloads/{filename}"

        # Start download
        msg = await message.reply("🚀 Starting download...")
        await download_file(url, filename, msg)

        # Verify final file size
        actual_size = os.path.getsize(filename)
        if actual_size > 2 * 1024 * 1024 * 1024:
            await message.reply("❌ Downloaded file exceeds 2GB limit.")
            os.remove(filename)
            return

        # Start upload
        await msg.edit("🚀 Starting upload...")
        await upload_with_progress(client, msg, filename)

        # Cleanup
        os.remove(filename)
        await msg.delete()

    except Exception as e:
        error_msg = f"❌ Error: {str(e)}"
        if msg:
            await msg.edit(error_msg)
        else:
            await message.reply(error_msg)
        if local_path and os.path.exists(local_path):
            os.remove(local_path)

app.run()
