# Use an official lightweight base image
FROM ubuntu:latest

# Set non-interactive mode to avoid prompts
ENV DEBIAN_FRONTEND=noninteractive

# Update package list and install ffmpeg
RUN apt update && apt install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the start script into the container
COPY start.sh /app/start.sh

# Ensure the script is executable
RUN chmod +x /app/start.sh

# Set the command to execute when the container starts
CMD ["bash", "start.sh"]
