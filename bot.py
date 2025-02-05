from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import os
import ffmpeg
import shutil
from threading import Thread
import time


# Telegram bot credentials
API_ID = 'your_api_id'
API_HASH = 'your_api_hash'
BOT_TOKEN = 'your_bot_token'


app = Client("url_uploader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Command to set custom thumbnail
@app.on_message(filters.command("setthumbnail"))
async def set_thumbnail(client, message: Message):
    if message.reply_to_message and message.reply_to_message.photo:
        # Download the photo as thumbnail
        photo = await message.reply_to_message.download()
        # Save the photo to a thumbnail directory
        shutil.move(photo, 'thumbnail.jpg')
        await message.reply("Custom thumbnail set successfully!")


# Command to delete custom thumbnail
@app.on_message(filters.command("delthumbnail"))
async def delete_thumbnail(client, message: Message):
    if os.path.exists('thumbnail.jpg'):
        os.remove('thumbnail.jpg')
        await message.reply("Custom thumbnail deleted!")
    else:
        await message.reply("No custom thumbnail found!")


# Download and upload file function
def download_and_upload(url, chat_id, message):
    try:
        # Extract video info using yt-dlp
        ydl_opts = {
            'format': 'best',
            'noplaylist': True,
            'progress_hooks': [progress_hook],
            'outtmpl': 'downloads/%(title)s.%(ext)s'
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_path = f"downloads/{info['title']}.{info['ext']}"
        
        # If the video is larger than 2GB, split it
        if os.path.getsize(video_path) > 2 * 1024 * 1024 * 1024:
            video_path = split_video(video_path)
        
        # Send the video to Telegram
        thumbnail = 'thumbnail.jpg' if os.path.exists('thumbnail.jpg') else None
        app.send_video(chat_id, video_path, caption=info['title'], thumb=thumbnail)
        
        # Clean up the downloaded file
        os.remove(video_path)

    except Exception as e:
        app.send_message(chat_id, f"Error: {str(e)}")


# Progress hook for downloading
def progress_hook(d):
    if d['status'] == 'downloading':
        total_size = d.get('total_bytes', 0)
        downloaded = d.get('downloaded_bytes', 0)
        speed = d.get('download_speed', 0)
        percent = (downloaded / total_size) * 100 if total_size else 0

        # Send progress to user (you can also update a message or use inline keyboard)
        print(f"Progress: {percent:.2f}% Downloaded: {downloaded / 1024 / 1024:.2f} MB, Speed: {speed / 1024:.2f} KB/s")

    elif d['status'] == 'finished':
        print(f"Download finished: {d['filename']}")


# Split video if larger than 2GB
def split_video(input_file):
    output_dir = 'downloads/split_videos'
    os.makedirs(output_dir, exist_ok=True)
    
    # Use ffmpeg to split the video
    output_file = os.path.join(output_dir, "part_%03d.mp4")
    ffmpeg.input(input_file).output(output_file, f='segment', segment_time='1800', segment_format='mp4').run()

    # Clean up the original video
    os.remove(input_file)

    # Return the path of the first part to be uploaded
    return os.path.join(output_dir, "part_001.mp4")


# Handling URL submissions from users
@app.on_message(filters.text & filters.private)
async def handle_url(client, message: Message):
    url = message.text

    # Asking for quality selection
    await message.reply("Fetching video formats... Please wait.")

    ydl_opts = {
        'format': 'best',
        'noplaylist': True,
        'extract_flat': True,
        'outtmpl': 'downloads/%(title)s.%(ext)s'
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [info])

            buttons = []
            for f in formats:
                buttons.append(
                    InlineKeyboardButton(f"{f['format_id']} - {f['height'] if 'height' in f else 'N/A'}p", callback_data=f['format_id'])
                )

            markup = InlineKeyboardMarkup([buttons])
            await message.reply("Choose the quality of the video:", reply_markup=markup)

            # Download video in the selected quality
            # Once user selects, handle video download and upload
            Thread(target=download_and_upload, args=(url, message.chat.id, message)).start()

        except Exception as e:
            await message.reply(f"Error fetching video info: {str(e)}")


@app.on_callback_query()
async def handle_quality_selection(client, callback_query):
    # Handle the quality selection here and download accordingly
    format_id = callback_query.data
    await callback_query.answer(f"Selected quality: {format_id}")


# Run the bot
app.run()
