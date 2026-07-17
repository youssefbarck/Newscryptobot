FROM python:3.11-slim

WORKDIR /app

# تثبيت المتطلبات النظامية
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# نسخ المتطلبات وتثبيتها
COPY requirements_v2.txt .
RUN pip install --no-cache-dir -r requirements_v2.txt

# نسخ الكود
COPY *.py .

# إنشاء مجلد البيانات
RUN mkdir -p /app/data

# المستخدم غير الجذر
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

# المنفذ
EXPOSE 10000

# التشغيل
CMD ["python", "main_v2.py"]
