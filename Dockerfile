FROM python:3.10-slim

# Sistem güncellemeleri
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Çalışma dizini ayarla
WORKDIR /app

# Tüm dosyaları kopyala
COPY . .

# Zorla tüm paketleri yükle
RUN pip install --no-cache-dir --force-reinstall \
    Flask \
    Flask-SQLAlchemy \
    werkzeug

# Port 7860'i açıkla
EXPOSE 7860

# Hugging Face için host ayarı
CMD ["python", "-u", "final_app.py"]
