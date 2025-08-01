# Use an official Python 3.11 base image
FROM python:3.11-slim

# Set environment variables to prevent .pyc files and enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory
WORKDIR /app

# Install system dependencies (optional but helpful for audio-related modules)
RUN apt-get update && apt-get install -y \
    gcc \
    libffi-dev \
    libnss3 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the project files into the container
COPY . .

# Run your bot
CMD ["python", "main.py"]
