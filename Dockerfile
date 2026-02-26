# ---------------------------
# Base image
# ---------------------------
FROM python:3.11-slim

# ---------------------------
# Environment
# ---------------------------
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ---------------------------
# Working directory
# ---------------------------
WORKDIR /app

# ---------------------------
# System deps (si necesitas compilar algo en futuro)
# ---------------------------
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------
# Install Python deps
# ---------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ---------------------------
# Copy project
# ---------------------------
COPY . .

# ---------------------------
# Expose port
# ---------------------------
EXPOSE 8000

# ---------------------------
# Run app
# ---------------------------
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
