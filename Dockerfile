FROM python:3.11-slim

# Install Git, LibreOffice, and minimal fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libreoffice \
    libreoffice-impress \
    fonts-noto-core \
    fonts-noto-extra \
    fonts-arabeyes \
    fontconfig \
    && fc-cache -f \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/soffice /usr/bin/soffice || true

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

# Install Playwright Chromium browser for PDF export
RUN playwright install --with-deps chromium

# Copy all project files
COPY . .

# Ensure fontconfig finds Arabic fonts
ENV FONTCONFIG_PATH=/etc/fonts

EXPOSE 7860
CMD ["python", "app.py"]
