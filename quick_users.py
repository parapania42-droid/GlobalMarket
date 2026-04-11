#!/usr/bin/env python3
from flask import Flask, jsonify
import os

app = Flask(__name__)

# DATABASE_URL zorla ekle
if not os.getenv('DATABASE_URL'):
    os.environ['DATABASE_URL'] = 'sqlite:///quick.db'

@app.route('/')
def home():
    return "User Management ÇALIYOR!"

@app.route('/users')
def list_users():
    try:
        # Basit liste simülasyonu
        return jsonify({
            'users': ['test_user1', 'test_user2', 'paramen42'],
            'total': 3,
            'message': 'DATABASE_URL eksikse bu simülasyon'
        })
    except Exception as e:
        return f"Hata: {str(e)}", 500

@app.route('/delete-all')
def delete_all():
    return "Tüm kullaniciilar silindi! (Simülasyon)"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
