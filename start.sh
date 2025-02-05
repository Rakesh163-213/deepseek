#!/bin/bash

# Start Flask app using gunicorn on port 8000
gunicorn app:app &

# Start the bot
python3 bot.py
