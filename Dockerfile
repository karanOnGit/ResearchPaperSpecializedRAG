# Production Dockerfile for Research Knowledge Engine (RAG OKF)
FROM python:3.11-slim-bookworm

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    HOST=0.0.0.0

WORKDIR /app

# Install OS-level dependencies required for building C/C++ extensions & PDF/XML processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Ensure storage directories exist
RUN mkdir -p data/uploads data/okf_exports data/vector_db

EXPOSE 8000

# Healthcheck to verify the server is healthy
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Start Uvicorn ASGI server
CMD ["python3", "-m", "uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
