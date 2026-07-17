FROM python:3.11-slim

WORKDIR /app

# تثبيت الاعتمادات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تثبيت خطوط DejaVu (للـ watermark)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# نسخ الملفات
COPY config.py .
COPY filters.py .
COPY rss.py .
COPY translate.py .
COPY telegram_bot.py .
COPY main.py .

# التشغيل
CMD ["python", "main.py"]