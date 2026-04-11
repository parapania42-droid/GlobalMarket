#!/usr/bin/env python3
import os
import psycopg2
from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/')
def home():
    return "Admin Panel ÇALIYOR!"

@app.route('/users')
def list_users():
    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cur = conn.cursor()
        cur.execute("SELECT username FROM users")
        users = [row[0] for row in cur.fetchall()]
        conn.close()
        return jsonify({'users': users, 'total': len(users)})
    except Exception as e:
        return f"Hata: {str(e)}", 500

@app.route('/delete-all')
def delete_all():
    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cur = conn.cursor()
        cur.execute("DELETE FROM users")
        conn.commit()
        conn.close()
        return "Tüm kullaniciilar silindi!"
    except Exception as e:
        return f"Hata: {str(e)}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
