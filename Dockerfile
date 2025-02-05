# Use an official lightweight base image
FROM ubuntu:latest

# Set non-interactive mode to avoid prompts
ENV DEBIAN_FRONTEND=noninteractive

# Update package list and install dependencies
RUN apt update && apt install -y ffmpeg python3 python3-pip python3-venv && rm -rf /var/lib/apt/lists/*

# Create a virtual environment and install Gunicorn inside it
RUN python3 -m venv /venv && /venv/bin/pip install gunicorn

# Set the working directory
WORKDIR /app

# Copy the start script into the container
COPY start.sh /app/start.sh

# Ensure the script is executable
RUN chmod +x /app/start.sh

# Use the virtual environment when running the script
CMD ["/bin/bash", "-c", "source /venv/bin/activate && bash start.sh"]
