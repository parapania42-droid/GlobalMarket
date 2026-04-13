# 1. Python imajını çek
FROM python:3.10

# 2. Çalışma dizini
WORKDIR /app

# 3. KÜTÜPHANELERİ TEK TEK VE ZORLA KUR
# Eğer requirements.txt bozuksa bile bu komut Flask'ı zorla yükler
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir flask flask-sqlalchemy werkzeug gunicorn

# 4. Tüm dosyaları kopyala
COPY . .

# 5. Hugging Face Port Ayarı
ENV PORT=7860
EXPOSE 7860

# 6. Uygulamayı Gunicorn ile başlat (final_app.py dosyanı çalıştırır)
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "final_app:app"]