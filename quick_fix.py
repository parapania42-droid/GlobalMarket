#!/usr/bin/env python3
print("Render için basit çözüm hazirlaniyor...")

# Basit Flask uygulamas
from flask import Flask
app = Flask(__name__)

@app.route('/')
def home():
    return "GlobalMarket ÇALIYOR!"

@app.route('/bombala-beni-06')
def reset():
    return "Tüm hesaplar silindi!"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
