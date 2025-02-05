# Use an official lightweight base image
FROM ubuntu:latest

# Set non-interactive mode to avoid prompts
ENV DEBIAN_FRONTEND=noninteractive

# Update package list and install ffmpeg, Python, and pip
RUN apt update && apt install -y ffmpeg python3 python3-pip && rm -rf /var/lib/apt/lists/*

# Install Gunicorn
RUN pip3 install gunicorn

# Set the working directory
WORKDIR /app

# Copy the start script into the container
COPY start.sh /app/start.sh

# Ensure the script is executable
RUN chmod +x /app/start.sh

# Set the command to execute when the container starts
CMD ["bash", "start.sh"]
