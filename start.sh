#!/bin/bash

# Start bot.py in the background
python3 bot.py &

# Start the app using gunicorn
gunicorn app:app
