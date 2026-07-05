FROM python:3.11-slim

# Install Git and minimal fonts (no LibreOffice needed - PDF uses Playwright)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    fonts-noto-core \
    fonts-noto-extra \
    fonts-arabeyes \
    fontconfig \
    && fc-cache -f \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

# Install Playwright browsers inside app directory for Hugging Face permissions
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.cache/ms-playwright
RUN playwright install --with-deps chromium

# Copy all project files
COPY . .

# Create writable directories and fix permissions for HF non-root user
RUN mkdir -p /app/outputs /app/uploads /app/.cache && \
    chmod -R 777 /app/outputs /app/uploads /app/.cache

# Ensure fontconfig finds Arabic fonts
ENV FONTCONFIG_PATH=/etc/fonts

EXPOSE 7860

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/health')" || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--timeout", "120", "--workers", "1", "--threads", "4", "app:app"]
