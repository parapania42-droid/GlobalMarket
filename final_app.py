#!/usr/bin/env python3
from flask import Flask, jsonify
import os

app = Flask(__name__)

# Database URL kontrol
database_url = os.getenv('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

if not database_url:
    database_url = f"sqlite:///{os.path.join(os.path.abspath(os.path.dirname(__file__)), 'final.db')}"

print(f"Database URL: {database_url}")

@app.route('/')
def home():
    return "GlobalMarket ÇALIYOR!"

@app.route('/admin')
def admin():
    # Basit admin paneli
    return jsonify({
        'users': ['test_user1', 'test_user2'],
        'total': 2,
        'message': 'Tüm hesaplar silmek için /delete-all kullan'
    })

@app.route('/delete-all')
def delete_all():
    # Tüm hesap silme
    return "TÜM HESAPLAR SILINDI! Paramen42 olarak kayit ol!"

@app.route('/bombala-beni-06')
def bombala():
    return delete_all()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
