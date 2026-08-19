FROM python:3.12-slim-bookworm
 
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Playwright / Scrapy
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    # HuggingFace cache trong volume
    HF_HOME=/app/.cache/huggingface \
    TRANSFORMERS_CACHE=/app/.cache/huggingface
 
WORKDIR /app
 
# System deps: Playwright Chromium + build tools cho một số wheel
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        build-essential \
        libpq-dev \
        # Playwright runtime
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
        libdrm2 libdbus-1-3 libxkbcommon0 libatspi2.0-0 libx11-6 \
        libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
        libgbm1 libpango-1.0-0 libcairo2 libasound2 libxshmfence1 \
        fonts-liberation fonts-unifont \
    && rm -rf /var/lib/apt/lists/*
 
# Python deps
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt
 
# Cài Chromium cho Playwright (scrapy-playwright)
RUN playwright install chromium
 
# Source code
COPY pyproject.toml* README.md* ./
COPY src ./src
COPY cv_data ./cv_data
# sites_config nằm trong src/job_crawler theo cấu trúc project
# storage/ được mount volume lúc runtime
 
# Thư mục runtime
RUN mkdir -p /app/storage/cv_index /app/.cache/huggingface /app/logs
 
# Entrypoint mặc định: help
ENTRYPOINT ["python", "-m", "src.main"]
CMD ["--help"]