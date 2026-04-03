FROM python:3.12-slim

# Install system deps for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libatspi2.0-0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libwayland-client0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e . 2>/dev/null || true

# Install Playwright Chromium
RUN pip install --no-cache-dir playwright \
    && playwright install chromium

# Copy application
COPY . .
RUN pip install --no-cache-dir -e .

# Data directory for SQLite
RUN mkdir -p /app/data
VOLUME /app/data

# Environment defaults
ENV AUTOTRADER_DB_PATH=/app/data/autotrader.db
ENV AUTOTRADER_HEADLESS=true
ENV AUTOTRADER_HOST=0.0.0.0
ENV AUTOTRADER_PORT=8000
ENV AUTOTRADER_DELAY=3.0

EXPOSE 8000

# Default command: start web UI
CMD ["autotrader", "web", "--host", "0.0.0.0", "--port", "8000"]
