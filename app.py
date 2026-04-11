import os
import sys
import time
import json
import random
import threading
import sqlalchemy
import base64
import urllib.request
import urllib.error
import shutil
import re
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, g
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.secret_key = "globalmarket_fixed_secret_key"
app.config["SESSION_PERMANENT"] = False
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
app.config.update(
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax"
)

# ---------------------------------------------------------
# CONSTANTS & CONFIG
# ---------------------------------------------------------
STARTING_MONEY = 50000

FACTORY_CONFIG = {
    "wood_cutter": {"name": "Odun Kesim Alanı", "type": "Odun", "rate": 5, "capacity": 1000, "unlock_lvl": 1, "cost": 1000, "worker_capacity": 5, "duration_min": 5},
    "stone_quarry": {"name": "Taş Ocağı", "type": "Taş", "rate": 4, "capacity": 1000, "unlock_lvl": 2, "cost": 2000, "worker_capacity": 5, "duration_min": 10},
    "iron_mine": {"name": "Demir Madeni", "type": "Demir", "rate": 3, "capacity": 500, "unlock_lvl": 5, "cost": 5000, "worker_capacity": 10, "duration_min": 15},
    "steel_mill": {"name": "Çelik Fabrikası", "type": "Çelik", "rate": 2, "capacity": 200, "unlock_lvl": 10, "cost": 15000, "worker_capacity": 15, "duration_min": 20},
    "plastic_plant": {"name": "Plastik Tesisi", "type": "Plastik", "rate": 2, "capacity": 200, "unlock_lvl": 12, "cost": 20000, "worker_capacity": 15, "duration_min": 20},
    "electronics_factory": {"name": "Elektronik Fabrikası", "type": "Elektronik", "rate": 1, "capacity": 100, "unlock_lvl": 20, "cost": 50000, "worker_capacity": 20, "duration_min": 30},
    "food_factory": {"name": "Gıda Fabrikası", "type": "Gıda", "rate": 5, "capacity": 500, "unlock_lvl": 3, "cost": 3000, "worker_capacity": 8, "duration_min": 10},
    "textile_mill": {"name": "Tekstil Atölyesi", "type": "Tekstil", "rate": 3, "capacity": 400, "unlock_lvl": 4, "cost": 4000, "worker_capacity": 8, "duration_min": 10}
}

def _normalize_username(u: str) -> str:
    return str(u or "").strip()

def _find_username_ci(username: str):
    if not username: return None
    try:
        row = db.session.execute(text('SELECT username FROM users WHERE LOWER(username) = LOWER(:u)'), {"u": username}).fetchone()
        return row[0] if row else None
    except Exception: return None

import os
from flask_sqlalchemy import SQLAlchemy

# SQLite'ı tamamen yasakla, sadece Render'daki Postgres'e bağlan
database_url = os.getenv('DATABASE_URL')

if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

if not database_url:
    # Render'da çalışması için geçici SQLite
    database_url = f"sqlite:///{os.path.join(os.path.abspath(os.path.dirname(__file__)), 'render.db')}"
    print("UYARI: DATABASE_URL yok, SQLite kullanılıyor")

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# VERİTABANI BAŞLATILACAK - init_db içinde sıfırlanacak
# Not: Tam sıfırlama init_db() fonksiyonunda yapılıyor

# Concurrency lock
lock = threading.Lock()

# ---------------------------------------------------------
# DATABASE MODELS
# ---------------------------------------------------------

class User(db.Model):
    __tablename__ = 'users'
    username = db.Column(db.String, primary_key=True)
    password_hash = db.Column(db.String, nullable=False)
    data = db.Column(db.Text, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

class MarketplaceProduct(db.Model):
    __tablename__ = 'marketplace_products'
    id = db.Column(db.Integer, primary_key=True)
    seller = db.Column(db.String, nullable=False)
    name = db.Column(db.String, nullable=False)
    description = db.Column(db.String)
    price = db.Column(db.Integer, nullable=False)
    stock = db.Column(db.Integer, nullable=False)
    is_bot = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.Float, nullable=False)

class FactoryRow(db.Model):
    __tablename__ = 'factories'
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String, nullable=False)
    type = db.Column(db.String, nullable=False)
    level = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.Float, nullable=False)

class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String, nullable=False)
    type = db.Column(db.String, nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    balance_after = db.Column(db.Integer, default=0)
    description = db.Column(db.String)
    time = db.Column(db.Float, nullable=False)
    meta = db.Column(db.String)

# ---------------------------------------------------------
# DATABASE INITIALIZATION
# ---------------------------------------------------------

def _repo_cfg():
    return os.environ.get("GITHUB_REPO", "").strip(), os.environ.get("GITHUB_BRANCH", "main").strip(), os.environ.get("GITHUB_TOKEN", "").strip()

def restore_database_if_needed():
    base_dir = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(base_dir, "globalmarket.db")
    if os.path.exists(db_path) and os.path.getsize(db_path) > 0: return
    repo, branch, token = _repo_cfg()
    if repo:
        try:
            url = f"https://api.github.com/repos/{repo}/contents/backup/globalmarket.db?ref={branch}"
            headers = {"Accept": "application/vnd.github+json"}
            if token: headers["Authorization"] = f"Bearer {token}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as resp:
                j = json.loads(resp.read().decode("utf-8"))
                content_b64 = j.get("content", "").replace("\n", "")
                if content_b64:
                    with open(db_path, "wb") as f: f.write(base64.b64decode(content_b64))
                    print("DB Restored from GitHub")
        except Exception: pass

def backup_database():
    base_dir = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(base_dir, "globalmarket.db")
    if not os.path.exists(db_path): return
    backup_dir = os.path.join(base_dir, "backup")
    os.makedirs(backup_dir, exist_ok=True)
    ts_file = os.path.join(backup_dir, ".last_backup")
    if os.path.exists(ts_file) and time.time() - os.path.getmtime(ts_file) < 120: return
    try:
        shutil.copyfile(db_path, os.path.join(backup_dir, "globalmarket.db"))
        with open(ts_file, "w") as f: f.write(str(time.time()))
    except Exception: pass

def seed_db():
    with app.app_context():
        try:
            # Seed prices if empty
            row = db.session.execute(text('SELECT COUNT(*) FROM prices')).fetchone()
            if row and row[0] == 0:
                items = [
                    ("Odun", 50), ("Taş", 40), ("Demir", 120), ("Kömür", 80),
                    ("Çelik", 300), ("Plastik", 250), ("Elektronik", 1000), 
                    ("Gıda", 30), ("Tekstil", 60), ("Altın", 5000), ("Buğday", 20)
                ]
                now = time.time()
                for name, price in items:
                    db.session.execute(text('INSERT INTO prices (item, price, last_change, updated_at) VALUES (:i, :p, 0, :t)'),
                                 {"i": name, "p": price, "t": now})
                db.session.commit()
                print("Prices Seeded")
        except Exception as e:
            print(f"Seeding failed: {e}")
            db.session.rollback()

def init_db():
    with app.app_context():
        try:
            print("🔄 VERİTABANI TAMAMEN SIFIRLANIYOR...")
            
            # PostgreSQL için sıfırlama - önce her şeyi temizle
            db.drop_all()
            print("🗑️ Tüm tablolar silindi")
            
            db.create_all()
            print("✅ SQLAlchemy tabloları oluşturuldu")
            
            # PostgreSQL uyumlu tablolar oluştur
            for sql in [
                "CREATE TABLE IF NOT EXISTS user_ids (username TEXT PRIMARY KEY, user_id INTEGER UNIQUE)",
                "CREATE TABLE IF NOT EXISTS user_logs (id SERIAL PRIMARY KEY, user_id INTEGER, action TEXT, amount REAL, timestamp REAL)",
                "CREATE TABLE IF NOT EXISTS market (id SERIAL PRIMARY KEY, satici TEXT, item TEXT, adet INTEGER, fiyat INTEGER, time REAL)",
                "CREATE TABLE IF NOT EXISTS chat (id SERIAL PRIMARY KEY, username TEXT, message TEXT, time TEXT)",
                "CREATE TABLE IF NOT EXISTS prices (item TEXT PRIMARY KEY, price REAL NOT NULL, last_change REAL NOT NULL, updated_at REAL NOT NULL)",
                "CREATE TABLE IF NOT EXISTS system_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS factory_assignments (id SERIAL PRIMARY KEY, owner TEXT NOT NULL, factory_type TEXT NOT NULL, count INTEGER NOT NULL, created_at REAL NOT NULL)",
                "CREATE TABLE IF NOT EXISTS vehicles (id SERIAL PRIMARY KEY, owner TEXT NOT NULL, type TEXT NOT NULL, capacity INTEGER NOT NULL, created_at REAL NOT NULL)",
                "CREATE TABLE IF NOT EXISTS logistics_tasks (id SERIAL PRIMARY KEY, owner TEXT NOT NULL, vehicle_id INTEGER NOT NULL, item TEXT NOT NULL, amount INTEGER NOT NULL, destination TEXT NOT NULL, city_scope TEXT NOT NULL, eta REAL NOT NULL, delivered INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL)",
                "CREATE TABLE IF NOT EXISTS transactions (id SERIAL PRIMARY KEY, owner TEXT NOT NULL, type TEXT NOT NULL, amount INTEGER NOT NULL, balance_after INTEGER, description TEXT, time REAL NOT NULL, meta TEXT)"
            ]:
                try:
                    db.session.execute(text(sql))
                    print(f"✅ Tablo hazır: {sql.split('(')[0].replace('CREATE TABLE IF NOT EXISTS ', '')}")
                except Exception as table_error:
                    print(f"⚠️ Tablo zaten var: {table_error}")
            
            print("🎉 VERİTABANI SIFIRLANDI VE HAZIR (PostgreSQL)")
            seed_db()
        except Exception as e: 
            print(f"❌ DB Init Failed: {str(e)}")
            # Transaction olmadan devam et

def create_admin_if_not_exists():
    with app.app_context():
        try:
            admin = User.query.filter_by(username='Paramen42').first()
            if not admin:
                data = {"username": "Paramen42", "money": 1000000, "level": 100, "xp": 0, "inventory": {}, "factories": {}, "is_admin": True}
                new_admin = User(username='Paramen42', password_hash=generate_password_hash('admin123'), data=json.dumps(data))
                db.session.add(new_admin)
                db.session.commit()
                print("Admin Created")
        except Exception as e:
            print(f"Admin creation failed: {e}")
            # Transaction olmadan devam et

# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

class _DictRow:
    def __init__(self, mapping):
        self._d = dict(mapping)
    def __getitem__(self, k): return self._d[k]
    def get(self, k, d=None): return self._d.get(k, d)
    def keys(self): return self._d.keys()
    def items(self): return self._d.items()
    def __iter__(self): return iter(self._d)

class _SAResultWrapper:
    def __init__(self, res):
        self._rows = []
        if res:
            for r in res.fetchall():
                m = getattr(r, "_mapping", None)
                self._rows.append(_DictRow(m if m is not None else dict(r)))
            res.close()
    def fetchall(self): return self._rows
    def fetchone(self): return self._rows[0] if self._rows else None

class _SAConnection:
    def __init__(self, session): self._session = session
    def cursor(self): return self
    def execute(self, sql, params=()):
        if isinstance(params, (list, tuple)):
            out, bind, idx = [], {}, 0
            for ch in sql:
                if ch == '?':
                    key = f"p{idx}"; out.append(f":{key}"); bind[key] = params[idx]; idx += 1
                else: out.append(ch)
            sql, params = "".join(out), bind
        try:
            res = self._session.execute(text(sql), params)
            if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")): self._session.commit()
            return _SAResultWrapper(res)
        except Exception:
            self._session.rollback()
            return _SAResultWrapper(None)
    def commit(self):
        try: self._session.commit()
        except Exception: pass
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, et, e, tb): pass

def get_db_connection(): return _SAConnection(db.session)

@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()
    if app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {}).get('poolclass') == NullPool:
        db.engine.dispose()

@app.after_request
def cleanup(resp):
    db.session.remove()
    return resp

# ---------------------------------------------------------
# GLOBAL EVENT SYSTEM
# ---------------------------------------------------------
def _get_current_event():
    conn = get_db_connection()
    row = conn.execute("SELECT value FROM system_state WHERE key = 'current_event'").fetchone()
    conn.close()
    if not row:
        return None
    try:
        ev = json.loads(row['value'])
        if time.time() >= ev.get('end_time', 0):
            return None
        return ev
    except Exception:
        return None

def _set_current_event(ev):
    is_pg = db.engine.dialect.name == 'postgresql'
    conn = get_db_connection()
    if is_pg:
        conn.execute("INSERT INTO system_state (key, value) VALUES ('current_event', :v) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", {"v": json.dumps(ev)})
    else:
        conn.execute("INSERT OR REPLACE INTO system_state (key, value) VALUES ('current_event', ?)", (json.dumps(ev),))
    conn.commit()
    conn.close()

def _clear_current_event():
    conn = get_db_connection()
    conn.execute("DELETE FROM system_state WHERE key = 'current_event'")
    conn.commit()
    conn.close()

def _start_random_event():
    now = time.time()
    duration = random.randint(1200, 3600)
    end_time = now + duration
    opps = [
        {"title": "İnşaat Patlaması", "target": {"type": "item", "name": "Taş"}, "price_multiplier": 1.5},
        {"title": "Teknoloji Talebi", "target": {"type": "item", "name": "Elektronik"}, "price_multiplier": 1.3},
        {"title": "İhracat Fırsatı", "target": {"type": "item", "name": "Odun"}, "price_multiplier": 1.4},
    ]
    crises = [
        {"title": "Yakıt Krizi", "target": {"type": "logistics"}, "logistics_cost_multiplier": 1.3},
        {"title": "Fabrika Arızaları", "target": {"type": "production"}, "production_multiplier": 0.8},
        {"title": "Ekonomik Daralma", "target": {"type": "prices_all"}, "price_multiplier": 0.75},
    ]
    pool = opps + crises
    ev = random.choice(pool)
    ev['end_time'] = end_time
    ev['started_at'] = now
    _set_current_event(ev)

def _event_loop():
    while True:
        try:
            ev = _get_current_event()
            if ev and time.time() >= ev.get('end_time', 0):
                _clear_current_event()
                ev = None
            if not ev:
                if random.random() < 0.05:
                    _start_random_event()
        except Exception:
            pass
        time.sleep(30)

t = threading.Thread(target=_event_loop, daemon=True)
t.start()

# ---------------------------------------------------------
# BOT SELLERS BACKGROUND TASK
# ---------------------------------------------------------
def _bot_price_for(name):
    base = _avg_price_for(name)
    if base <= 0:
        # fallback to global prices if exists
        conn = get_db_connection()
        pr = conn.execute('SELECT price FROM prices WHERE item = ?', (name,)).fetchone()
        conn.close()
        base = int(pr['price']) if pr else random.randint(20, 200)
    # +/- 10-30%
    pct = random.uniform(0.10, 0.30)
    updown = 1 if random.random() < 0.5 else -1
    return max(1, int(base * (1 + updown * pct)))

def start_bot_sellers():
    def run():
        bot_names = ["MarketPro","TradeX","GlobalSeller","MercuryMart","AtlasTrade","NeoBazaar","PrimeGoods","VeloShop"]
        items = ["Odun","Taş","Demir","Kömür","Çelik","Plastik","Elektronik","Gıda"]
        while True:
            try:
                seller = random.choice(bot_names)
                name = random.choice(items)
                price = _bot_price_for(name)
                stock = random.randint(5, 20)
                desc = "Otomatik satıcı ürünü"
                conn = get_db_connection()
                conn.execute('INSERT INTO marketplace_products (seller, name, description, price, stock, is_bot, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                             (seller, name, desc, price, stock, 1, time.time()))
                conn.commit()
                conn.close()
            except Exception:
                pass
            time.sleep(random.randint(90, 180))
    t = threading.Thread(target=run, daemon=True)
    t.start()

start_bot_sellers()

def get_user(username):
    if not username: return None
    uname = _normalize_username(username)
    try:
        res = db.session.execute(text('SELECT * FROM users WHERE username = :u'), {"u": uname})
        user = res.fetchone()
        if not user and uname:
            res = db.session.execute(text('SELECT * FROM users WHERE LOWER(username) = LOWER(:u) LIMIT 1'), {"u": uname})
            user = res.fetchone()
        
        if user:
            # SQLAlchemy row to dict mapping
            mapping = getattr(user, "_mapping", None)
            u_row = dict(mapping) if mapping else dict(user)
            u_data = json.loads(u_row['data'])
            db_username = u_row['username']
            u_data['username'] = db_username
            
            # Migration/Repair for missing keys
            if "inventory" not in u_data: u_data["inventory"] = {}
            # Ensure inventory keys exist
            for k in ["Odun","Taş","Demir","Çelik","Plastik","Elektronik","Gıda","Tekstil"]:
                u_data["inventory"][k] = u_data["inventory"].get(k, 0)
            if "factories" not in u_data: u_data["factories"] = {}
            if "factory_storage" not in u_data: u_data["factory_storage"] = {}
            if "factory_last_update" not in u_data: u_data["factory_last_update"] = {}
            if "factory_last_collect" not in u_data: u_data["factory_last_collect"] = {}
            if "factory_run_start" not in u_data: u_data["factory_run_start"] = {}
            if "factory_run_duration" not in u_data: u_data["factory_run_duration"] = {}
            if "net_worth" not in u_data: u_data["net_worth"] = 0
            if "xp" not in u_data: u_data["xp"] = 0
            if "level" not in u_data: u_data["level"] = 1
            if "money" not in u_data: u_data["money"] = STARTING_MONEY
            try:
                u_data["money"] = max(0, int(u_data.get("money", STARTING_MONEY)))
            except Exception:
                u_data["money"] = STARTING_MONEY
            if "workers_available" not in u_data: u_data["workers_available"] = 0
            if "avg_buy_prices" not in u_data: u_data["avg_buy_prices"] = {}
            if "council_member" not in u_data: u_data["council_member"] = (db_username.lower() == "konsey")
            
            # session commit'i get_user içinde yapmamak daha güvenli, sadece okuma yapıyoruz
            return u_data
    except Exception as e:
        print(f"get_user error for {username}: {str(e)}")
        db.session.rollback()
    finally:
        db.session.remove()
    return None

def save_user(user_data):
    username = user_data['username']
    try:
        db.session.execute(text('UPDATE users SET data = :d WHERE username = :u'), 
                     {"d": json.dumps(user_data), "u": username})
        db.session.commit()
        backup_database()
    except Exception as e:
        print(f"save_user error: {e}")
        db.session.rollback()
    finally:
        db.session.remove()

def create_user(username, password):
    username = _normalize_username(username)
    if _find_username_ci(username):
        return False
        
    pw_hash = generate_password_hash(password)
    
    # Special Logic for Paramen42
    is_admin = (username == 'Paramen42')
    starting_money = 50000 if is_admin else STARTING_MONEY
    
    # Initial State
    initial_data = {
        "username": username,
        "money": starting_money,
        "level": 1,
        "xp": 0,
        "inventory": {
            "Odun": 0, "Taş": 0, "Demir": 0, "Çelik": 0, 
            "Plastik": 0, "Elektronik": 0, "Gıda": 0, "Tekstil": 0,
            "Buğday": 5  # Hediye Buğday
        },
        "factories": {},
        "factory_storage": {},
        "factory_last_update": {},
        "factory_last_collect": {},
        "factory_run_start": {},
        "factory_run_duration": {},
        "factory_boosts": {},
        "net_worth": starting_money,
        "mission": {"description": "İlk fabrikanı kur!", "target_qty": 1, "current_qty": 0, "reward": 500},
        "last_active": time.time(),
        "last_login": 0,
        "is_afk": False,
        "is_admin": is_admin,
        "expedition": None, # {type, start_time, end_time, cost}
        "last_daily_bonus": 0,
        "workers_available": 0
    }
    
    try:
        with lock:
            # Tamamen raw SQL ile - SQLAlchemy session olmadan
            engine = db.engine
            with engine.connect() as conn:
                # Kullanıcı ekle
                conn.execute(text('INSERT INTO users (username, password_hash, data, is_admin) VALUES (:u, :p, :d, :a)'),
                             {"u": username, "p": pw_hash, "d": json.dumps(initial_data), "a": is_admin})
                
                # User ID ata
                res = conn.execute(text('SELECT MAX(user_id) AS m FROM user_ids'))
                row = res.fetchone()
                next_id = 1
                if row and row[0] is not None:
                    next_id = int(row[0]) + 1
                
                # User IDs tablosuna ekle
                conn.execute(text('INSERT OR REPLACE INTO user_ids (username, user_id) VALUES (:u, :id)'), 
                             {"u": username, "id": next_id})
                
                # Log ekle
                conn.execute(text('INSERT INTO user_logs (user_id, action, amount, timestamp) VALUES (:id, :a, :am, :t)'), 
                             {"id": next_id, "a": 'register', "am": 0, "t": time.time()})
                
                conn.commit()
                conn.close()
                
            print(f"✅ Kullanıcı başarıyla oluşturuldu: {username}")
            backup_database()
            return True
            
    except Exception as e:
        print(f"HATA: create_user error: {str(e)}")
        return False

# ---------------------------------------------------------
# USER ID & LOG HELPERS
# ---------------------------------------------------------
def get_user_id_by_username(username):
    try:
        conn = get_db_connection()
        row = conn.execute('SELECT user_id FROM user_ids WHERE username = ?', (username,)).fetchone()
        conn.close()
        return int(row['user_id']) if row and row['user_id'] is not None else None
    except Exception:
        return None

def get_username_by_user_id(uid):
    try:
        conn = get_db_connection()
        row = conn.execute('SELECT username FROM user_ids WHERE user_id = ?', (uid,)).fetchone()
        conn.close()
        return row['username'] if row else None
    except Exception:
        return None

def log_user_action(uid, action, amount=0):
    try:
        conn = get_db_connection()
        conn.execute('INSERT INTO user_logs (user_id, action, amount, timestamp) VALUES (?, ?, ?, ?)', (uid, action, amount, time.time()))
        conn.commit()
        conn.close()
    except Exception:
        pass
# ---------------------------------------------------------
# GAME LOGIC HELPERS
# ---------------------------------------------------------

def check_level_up(user):
    required_xp = user["level"] * 1000
    if user["xp"] >= required_xp:
        user["level"] += 1
        user["xp"] -= required_xp
        user["money"] += user["level"] * 500 # Level up bonus
        return True
    return False

def calculate_production(user):
    now = time.time()
    
    # Check AFK (5 mins inactivity)
    last_active = user.get("last_active", now)
    user["is_afk"] = (now - last_active) > 300
    user["last_active"] = now
    
    prod_mult = 0.1 if user["is_afk"] else 1.0
    
    for fid, level in user["factories"].items():
        if level <= 0: continue
        
        conf = FACTORY_CONFIG.get(fid)
        if not conf: continue
        
        last_upd = user["factory_storage"].get(fid, 0) # wait, storage is not last_upd
        # Fix: storage logic
        if "factory_last_update" not in user: user["factory_last_update"] = {}
        last_t = user["factory_last_update"].get(fid, now)
        
        elapsed_min = (now - last_t) / 60.0
        if elapsed_min <= 0: continue
        
        # Boost check
        is_boosted = False
        boost_end = user.get("factory_boosts", {}).get(fid, 0)
        if boost_end > now:
            is_boosted = True
        
        # Running status
        running = True
        running_map = user.get("factory_running", {})
        if fid in running_map:
            running = bool(running_map[fid])
        # Worker assignment multiplier
        conn = get_db_connection()
        assigned = conn.execute('SELECT COALESCE(SUM(count),0) AS c FROM factory_assignments WHERE owner = ? AND factory_type = ?', 
                                (user["username"], fid)).fetchone()['c']
        conn.close()
        worker_mult = 1.0 + (0.05 * assigned)
        
        rate = conf["rate"] * level * prod_mult * worker_mult
        if not running:
            rate = 0
        if is_boosted: rate *= 2
        
        produced = rate * elapsed_min
        
        current_storage = user["factory_storage"].get(fid, 0)
        max_storage = conf["capacity"] * level
        
        new_storage = min(max_storage, current_storage + produced)
        
        user["factory_storage"][fid] = new_storage
        user["factory_last_update"][fid] = now
        
    # Net worth calc
    nw = user["money"]
    for fid, level in user["factories"].items():
        conf = FACTORY_CONFIG.get(fid)
        if conf: nw += (conf["cost"] * level) * 0.8
    # Add inventory value (approx)
    user["net_worth"] = int(nw)

# ---------------------------------------------------------
# ROUTES
# ---------------------------------------------------------

@app.before_request
def load_logged_in_user():
    g.user = None
    if 'user_id' in session:
        # Optimized: Only fetch if needed or if user data is old in session
        # For now, let's keep the g.user for convenience but use session for HUD
        u = get_user(session['user_id'])
        if u:
            g.user = u
        else:
            session.clear()

@app.context_processor
def inject_user():
    """Tüm şablonlara kullanıcı bilgilerini otomatik gönder"""
    if 'user_id' in session and g.user:
        return {
            'current_user': g.user,
            'username': g.user.get('username', ''),
            'money': g.user.get('money', 0),
            'level': g.user.get('level', 1),
            'is_authenticated': True
        }
    return {
        'current_user': None,
        'username': None,
        'money': 0,
        'level': 1,
        'is_authenticated': False
    }

@app.route('/api/user/me')
def api_user_me():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Oturum kapalı"}), 401
    
    # Try to use cached data in session if possible for very fast HUD updates
    # But for now, get_user is already optimized with NullPool/dispose
    u = get_user(session['user_id'])
    if not u:
        return jsonify({"success": False, "message": "Kullanıcı bulunamadı"}), 404
    
    return jsonify({
        "success": True,
        "username": u['username'],
        "money": u['money'],
        "level": u['level'],
        "xp": u['xp'],
        "inventory": u.get('inventory', {})
    })

@app.route('/')
def index():
    try:
        if g.user:
            return redirect(url_for('game'))
    except Exception as e:
        print(f"Index route error: {str(e)}")
    return redirect(url_for('login_page'))

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'GET':
        return render_template('login.html')

    # Handle both JSON and Form data
    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form

    username = _normalize_username(data.get('username'))
    password = data.get('password') or ""
    
    if not username or not password:
        if request.is_json:
            return jsonify({"success": False, "message": "Kullanıcı adı ve şifre gerekli"})
        return render_template('login.html', error="Kullanıcı adı ve şifre gerekli")

    try:
        canonical = _find_username_ci(username)
        if not canonical:
            if request.is_json:
                return jsonify({"success": False, "message": "Kullanıcı bulunamadı"})
            return render_template('login.html', error="Kullanıcı bulunamadı")

        conn = get_db_connection()
        try:
            row = conn.execute('SELECT username, password_hash, data FROM users WHERE username = ?', (canonical,)).fetchone()
            if not row:
                if request.is_json:
                    return jsonify({"success": False, "message": "Kullanıcı veritabanında mevcut değil"})
                return render_template('login.html', error="Kullanıcı veritabanında mevcut değil")
                
            if not check_password_hash(row['password_hash'], password):
                if request.is_json:
                    return jsonify({"success": False, "message": "Şifre hatalı"})
                return render_template('login.html', error="Şifre hatalı")

            # Giriş başarılı: Session ata
            u_data = json.loads(row['data'])
            session.clear()
            session.permanent = True
            session['user_id'] = row['username']
            session['is_admin'] = u_data.get('is_admin', False)
            
            if request.is_json:
                return jsonify({"success": True, "message": "Giriş başarılı", "redirect": "/game"})
            return redirect(url_for('game'))
        except Exception as e:
            print(f"Login DB error: {str(e)}")
            if request.is_json:
                return jsonify({"success": False, "message": "Veritabanı bağlantı hatası"})
            return render_template('login.html', error="Veritabanı hatası")
        finally:
            conn.close()
    except Exception as e:
        print(f"Login route error: {str(e)}")
        if request.is_json:
            return jsonify({"success": False, "message": "Giriş sırasında teknik bir hata oluştu"})
        return render_template('login.html', error="Sistem hatası")

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')

    data = request.get_json(silent=True) or {}
    username = _normalize_username(data.get('username'))
    password = data.get('password')
    
    if not username:
        return jsonify({"success": False, "message": "Kullanıcı adı gerekli"})
    if not re.match(r"^[A-Za-z0-9_]{3,24}$", username):
        return jsonify({"success": False, "message": "Kullanıcı adı 3-24 karakter olmalı (harf/rakam/_)"})
    if not password or len(password) < 6:
        return jsonify({"success": False, "message": "Şifre en az 6 karakter"})
    canonical = _find_username_ci(username)
    if canonical:
        return jsonify({"success": False, "message": "Kullanıcı adı kullanımda"})
    
    try:
        if create_user(username, password):
            # Register başarılı olduğunda session set et ve yönlendir
            session.permanent = True
            session['user_id'] = username
            return jsonify({"success": True, "message": "Kayıt başarılı! Hoş geldiniz.", "redirect": "/game"})
    except Exception as e:
        print(f"Register route error: {str(e)}")
        
    return jsonify({"success": False, "message": "Kayıt sırasında teknik bir hata oluştu"})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/logout', methods=['POST'])
def logout_post():
    session.clear()
    return jsonify({"success": True, "redirect": "/login"})

# Auth devre dışı: before_request kaldırıldı

@app.route('/game')
def game():
    try:
        if 'user_id' not in session:
            return redirect(url_for('login_page'))
        u = get_user(session['user_id'])
        if not u:
            session.clear()
            return redirect(url_for('login_page'))
        # Ensure username is explicitly passed
        return render_template('game.html', active_page='game', user=u, username=u['username'])
    except Exception as e:
        print(f"Game route error: {str(e)}")
        return redirect(url_for('login_page'))

@app.route('/leaderboard')
def leaderboard_page():
    try:
        return render_template('leaderboard.html', active_page='leaderboard')
    except Exception as e:
        print(f"Leaderboard route error: {str(e)}")
        return redirect(url_for('game'))

@app.route('/guide')
def guide_page():
    try:
        return render_template('guide.html', active_page='guide')
    except Exception as e:
        print(f"Guide route error: {str(e)}")
        return redirect(url_for('game'))

@app.route('/market')
def market_page():
    try:
        # Mock data for demonstration
        market_items = [
            {"id": 1, "name": "Buğday", "price": 15, "stock": 100, "icon": "🌾"},
            {"id": 2, "name": "Demir", "price": 100, "stock": 50, "icon": "⛓️"},
            {"id": 3, "name": "Altın", "price": 5000, "stock": 10, "icon": "💰"}
        ]
        return render_template('market.html', active_page='market', items=market_items)
    except Exception as e:
        print(f"Market route error: {str(e)}")
        return redirect(url_for('game'))
    
@app.route('/marketplace')
def marketplace_page():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    u = get_user(session['user_id'])
    if not u:
        return redirect(url_for('login_page'))
    return render_template('marketplace.html', active_page='market', username=u['username'])

@app.route('/factory')
def factory_page():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    u = get_user(session['user_id'])
    if not u:
        return redirect(url_for('login_page'))
    # Mock factory options for demonstration
    available_factories = [
        {"id": "solar", "name": "Güneş Paneli", "cost": 5000, "rate": 2, "icon": "☀️"},
        {"id": "iron_mine", "name": "Demir Madeni", "cost": 2000, "rate": 3, "icon": "⛏️"}
    ]
    return render_template('factory.html', active_page='factory', factories=available_factories, username=u['username'])

@app.route('/resources')
def resources_page():
    try:
        return render_template('resources.html', active_page='resources')
    except Exception as e:
        print(f"Resources route error: {str(e)}")
        return redirect(url_for('game'))

@app.route('/land')
def land_page():
    try:
        return render_template('land.html', active_page='land')
    except Exception as e:
        print(f"Land route error: {str(e)}")
        return redirect(url_for('game'))

@app.route('/inventory')
def inventory_page():
    try:
        if 'user_id' not in session:
            return redirect(url_for('login_page'))
        u = get_user(session['user_id'])
        if not u:
            return redirect(url_for('login_page'))
        return render_template('inventory.html', active_page='inventory', inventory=u.get('inventory', {}), username=u['username'])
    except Exception as e:
        print(f"Inventory route error: {str(e)}")
        return redirect(url_for('game'))

@app.route('/logistics')
def logistics_page():
    try:
        return render_template('logistics.html', active_page='logistics')
    except Exception as e:
        print(f"Logistics route error: {str(e)}")
        return redirect(url_for('game'))

@app.route('/workers')
def workers_page():
    try:
        return render_template('workers.html', active_page='workers')
    except Exception as e:
        print(f"Workers route error: {str(e)}")
        return redirect(url_for('game'))

@app.route('/realestate')
def realestate_page():
    try:
        return render_template('realestate.html', active_page='realestate')
    except Exception as e:
        print(f"Realestate route error: {str(e)}")
        return redirect(url_for('game'))

# ---------------------------------------------------------
# MARKETPLACE API
# ---------------------------------------------------------
def _avg_price_for(name):
    conn = get_db_connection()
    row = conn.execute('SELECT AVG(price) AS avgp FROM marketplace_products WHERE name = ? AND is_bot = 0', (name,)).fetchone()
    conn.close()
    return int(row['avgp']) if row and row['avgp'] else 0

@app.route('/api/marketplace/list')
def api_marketplace_list():
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM marketplace_products ORDER BY created_at DESC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/marketplace/add', methods=['POST'])
def api_marketplace_add():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    data = request.json
    name = (data.get('name') or '').strip()
    desc = (data.get('description') or '').strip()
    price = int(data.get('price', 0))
    stock = int(data.get('stock', 0))
    if not name or price <= 0 or stock <= 0:
        return jsonify({"success": False, "message": "Geçersiz bilgi!"})
    with lock:
        current = u['inventory'].get(name, 0)
        if current < stock:
            return jsonify({"success": False, "message": "Envanterde yeterli stok yok!"})
        u['inventory'][name] = current - stock
        save_user(u)
    conn = get_db_connection()
    conn.execute('INSERT INTO marketplace_products (seller, name, description, price, stock, is_bot, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                 (u['username'], name, desc, price, stock, 0, time.time()))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Ürün eklendi!"})

@app.route('/api/marketplace/edit', methods=['POST'])
def api_marketplace_edit():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    data = request.json
    pid = int(data.get('id', 0))
    name = (data.get('name') or '').strip()
    desc = (data.get('description') or '').strip()
    price = int(data.get('price', 0))
    stock = int(data.get('stock', 0))
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM marketplace_products WHERE id = ?', (pid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"success": False, "message": "Ürün bulunamadı!"})
    if row['seller'] != u['username']:
        conn.close()
        return jsonify({"success": False, "message": "Yetkisiz işlem!"})
    if price <= 0 or stock < 0:
        conn.close()
        return jsonify({"success": False, "message": "Geçersiz bilgi!"})
    conn.execute('UPDATE marketplace_products SET name = ?, description = ?, price = ?, stock = ? WHERE id = ?',
                 (name or row['name'], desc or row['description'], price, stock, pid))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Ürün güncellendi!"})

@app.route('/api/marketplace/delete', methods=['POST'])
def api_marketplace_delete():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    data = request.json
    pid = int(data.get('id', 0))
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM marketplace_products WHERE id = ?', (pid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"success": False, "message": "Ürün bulunamadı!"})
    if row['seller'] != u['username']:
        conn.close()
        return jsonify({"success": False, "message": "Yetkisiz işlem!"})
    conn.execute('DELETE FROM marketplace_products WHERE id = ?', (pid,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Ürün silindi!"})

@app.route('/api/marketplace/buy', methods=['POST'])
def api_marketplace_buy():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    buyer = get_user(session['user_id'])
    data = request.json
    pid = int(data.get('id', 0))
    qty = int(data.get('qty', 0))
    if qty <= 0:
        return jsonify({"success": False, "message": "Geçersiz adet!"})
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM marketplace_products WHERE id = ?', (pid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"success": False, "message": "Ürün bulunamadı!"})
    if row['stock'] < qty:
        conn.close()
        return jsonify({"success": False, "message": "Yetersiz stok!"})
    cost = row['price'] * qty
    with lock:
        if buyer['money'] < cost:
            conn.close()
            return jsonify({"success": False, "message": "Yetersiz bakiye!"})
        buyer['money'] -= cost
        buyer['inventory'][row['name']] = buyer['inventory'].get(row['name'], 0) + qty
        save_user(buyer)
        # log user action
        try:
            uid_b = get_user_id_by_username(buyer['username'])
            if uid_b:
                log_user_action(uid_b, 'marketplace_buy', -cost)
        except Exception:
            pass
        seller = get_user(row['seller'])
        if seller:
            seller['money'] += cost
            save_user(seller)
            try:
                uid_s = get_user_id_by_username(seller['username'])
                if uid_s:
                    log_user_action(uid_s, 'marketplace_sale', cost)
            except Exception:
                pass
        new_stock = row['stock'] - qty
        if new_stock <= 0:
            conn.execute('DELETE FROM marketplace_products WHERE id = ?', (pid,))
        else:
            conn.execute('UPDATE marketplace_products SET stock = ? WHERE id = ?', (new_stock, pid))
        conn.execute('INSERT INTO transactions (owner, type, amount, time, meta) VALUES (?, ?, ?, ?, ?)',
                     (row['seller'], 'marketplace_buy', cost, time.time(), json.dumps({"product_id": pid, "name": row['name'], "price": row['price'], "qty": qty, "buyer": buyer['username']})))
        conn.commit()
        conn.close()
    return jsonify({"success": True, "message": "Satın alındı!"})

@app.route('/api/marketplace/avg_price')
def api_marketplace_avg():
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({"avg": 0})
    return jsonify({"avg": _avg_price_for(name)})

@app.route('/api/marketplace/price_hint')
def api_marketplace_price_hint():
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({"avg": 0, "trend": "stable"})
    avg = _avg_price_for(name)
    conn = get_db_connection()
    since = time.time() - 7*24*3600
    rows = conn.execute("SELECT meta FROM transactions WHERE type = 'marketplace_buy' AND time >= ?", (since,)).fetchall()
    conn.close()
    sales = 0
    for r in rows:
        try:
            m = json.loads(r['meta'])
            if m.get('name') == name:
                sales += 1
        except Exception:
            continue
    # Simple trend: >10 sales => up, <3 sales => down
    trend = "stable"
    if sales > 10: trend = "up"
    elif sales < 3: trend = "down"
    return jsonify({"avg": avg, "trend": trend, "sales": sales})
@app.route('/api/marketplace/top_sellers')
def api_marketplace_top_sellers():
    conn = get_db_connection()
    since = time.time() - 7*24*3600
    rows = conn.execute("SELECT owner, COUNT(*) AS c, SUM(amount) AS total FROM transactions WHERE type = 'marketplace_buy' AND time >= ? GROUP BY owner ORDER BY c DESC LIMIT 10", (since,)).fetchall()
    conn.close()
    return jsonify([{"seller": r['owner'], "sales": r['c'], "revenue": r['total']} for r in rows])

@app.route('/api/marketplace/recent_sales')
def api_marketplace_recent_sales():
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM transactions WHERE type = 'marketplace_buy' ORDER BY time DESC LIMIT 10").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/me')
def api_me():
    if 'user_id' not in session:
        u = {
            "username": "Misafir",
            "money": 0,
            "level": 1,
            "xp": 0,
            "inventory": {},
            "factories": {},
            "factory_storage": {},
            "factory_last_update": {},
            "factory_last_collect": {},
            "factory_run_start": {},
            "factory_run_duration": {},
            "factory_boosts": {},
            "net_worth": 0,
            "mission": None,
            "last_active": time.time(),
            "last_login": 0,
            "is_afk": False,
            "is_admin": False,
            "expedition": None,
            "last_daily_bonus": 0,
            "workers_available": 0
        }
    else:
        u = get_user(session['user_id'])
        if not u: return jsonify({}), 401
        if u.get("is_banned"):
            return jsonify({"message": "Hesabınız yasaklandı"}), 403
    
    with lock:
        calculate_production(u)
        now = time.time()
        last = u.get("last_daily_bonus", 0)
        u["daily_bonus_available"] = (now - last) >= 86400
        exp = u.get("expedition")
        u["expedition_active"] = False
        if exp:
            u["expedition_active"] = True
            u["expedition_end_time"] = exp.get("end_time")
            if u["expedition_end_time"] and now >= u["expedition_end_time"]:
                u["expedition_completed"] = True
        u["is_admin"] = False
        # only save for real users
        if 'user_id' in session:
            save_user(u)
        
    u["factory_config"] = FACTORY_CONFIG
    return jsonify(u)

# ---------------------------------------------------------
# ECONOMY API: LAND
# ---------------------------------------------------------

@app.route('/api/land/list')
def api_land_list():
    if 'user_id' not in session: return jsonify({}), 401
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM lands WHERE owner = ?', (session['user_id'],)).fetchall()
    conn.close()
    
    owned = [dict(r) for r in rows]
    # Available types & base prices
    options = {
        "Tarla": {"base_price": 1000, "locations": {"Kırsal": 0.9, "Şehir": 1.1}},
        "Sanayi Arsası": {"base_price": 5000, "locations": {"Kırsal": 0.95, "Şehir": 1.2}},
        "Şehir Arsası": {"base_price": 10000, "locations": {"Kırsal": 1.0, "Şehir": 1.4}}
    }
    sizes = {"Küçük": 1.0, "Orta": 1.8, "Büyük": 3.2}
    return jsonify({"owned": owned, "options": options, "sizes": sizes})

@app.route('/api/land/buy', methods=['POST'])
def api_land_buy():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    data = request.json
    type_ = data.get('type')
    size = data.get('size')
    location = data.get('location')
    
    options = {
        "Tarla": {"base_price": 1000, "locations": {"Kırsal": 0.9, "Şehir": 1.1}},
        "Sanayi Arsası": {"base_price": 5000, "locations": {"Kırsal": 0.95, "Şehir": 1.2}},
        "Şehir Arsası": {"base_price": 10000, "locations": {"Kırsal": 1.0, "Şehir": 1.4}}
    }
    sizes = {"Küçük": 1.0, "Orta": 1.8, "Büyük": 3.2}
    
    if type_ not in options or size not in sizes or location not in options[type_]["locations"]:
        return jsonify({"success": False, "message": "Geçersiz parametre!"})
    
    base = options[type_]["base_price"]
    price = int(base * sizes[size] * options[type_]["locations"][location])
    
    with lock:
        if u['money'] < price:
            return jsonify({"success": False, "message": "Yetersiz bakiye!"})
        u['money'] -= price
        save_user(u)
        
        conn = get_db_connection()
        conn.execute('INSERT INTO lands (owner, type, size, location, price, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                     (u['username'], type_, size, location, price, time.time()))
        conn.execute('INSERT INTO transactions (owner, type, amount, time, meta) VALUES (?, ?, ?, ?, ?)',
                     (u['username'], 'land_buy', -price, time.time(), json.dumps({"type": type_, "size": size, "location": location})))
        conn.commit()
        conn.close()
    
    return jsonify({"success": True, "message": f"{size} {type_} satın alındı! Maliyet: {price} TL"})

# ---------------------------------------------------------
# ECONOMY API: WORKERS
# ---------------------------------------------------------

@app.route('/api/workers/buy', methods=['POST'])
def api_workers_buy():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    data = request.json
    count = int(data.get('count', 0))
    if count <= 0:
        return jsonify({"success": False, "message": "Geçersiz adet!"})
    cost = 500 * count
    with lock:
        if u['money'] < cost:
            return jsonify({"success": False, "message": "Yetersiz bakiye!"})
        u['money'] -= cost
        u['workers_available'] = u.get('workers_available', 0) + count
        # Mission progress: workers buy
        m = u.get('mission') or {}
        if m.get('kind') == 'workers':
            m['current_qty'] = int(m.get('current_qty', 0)) + count
            if m['current_qty'] >= m.get('target_qty', 5):
                u['money'] += int(m.get('reward', 0))
                u['xp'] += int(m.get('reward', 0) // 2)
                # Loop back to upgrade mission
                u['mission'] = {"kind": "upgrade", "description": "1 fabrika yükselt!", "target_qty": 1, "current_qty": 0, "reward": 1000}
            else:
                u['mission'] = m
        save_user(u)
    conn = get_db_connection()
    conn.execute('INSERT INTO transactions (owner, type, amount, time, meta) VALUES (?, ?, ?, ?, ?)',
                 (u['username'], 'workers_buy', -cost, time.time(), json.dumps({"count": count})))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"{count} işçi satın alındı!"})

@app.route('/api/workers/hire', methods=['POST'])
def api_workers_hire():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    data = request.json
    type_ = data.get('type')
    count = int(data.get('count', 0))
    
    worker_defs = {
        "İşçi": {"salary": 50, "productivity": 1.0},
        "Usta": {"salary": 120, "productivity": 1.5},
        "Mühendis": {"salary": 300, "productivity": 2.0}
    }
    if type_ not in worker_defs or count <= 0:
        return jsonify({"success": False, "message": "Geçersiz parametre!"})
    
    # Hire fee: 10x salary per worker
    cost = worker_defs[type_]["salary"] * 10 * count
    with lock:
        if u['money'] < cost:
            return jsonify({"success": False, "message": "Yetersiz bakiye!"})
        u['money'] -= cost
        save_user(u)
        
        conn = get_db_connection()
        conn.execute('INSERT INTO workers (owner, type, count, salary, productivity, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                     (u['username'], type_, count, worker_defs[type_]["salary"], worker_defs[type_]["productivity"], time.time()))
        conn.execute('INSERT INTO transactions (owner, type, amount, time, meta) VALUES (?, ?, ?, ?, ?)',
                     (u['username'], 'workers_hire', -cost, time.time(), json.dumps({"type": type_, "count": count})))
        conn.commit()
        conn.close()
    return jsonify({"success": True, "message": f"{count} {type_} işe alındı! Maliyet: {cost} TL"})

@app.route('/api/workers/fire', methods=['POST'])
def api_workers_fire():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    data = request.json
    worker_id = int(data.get('id', 0))
    
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM workers WHERE id = ? AND owner = ?', (worker_id, u['username'])).fetchone()
    if not row:
        conn.close()
        return jsonify({"success": False, "message": "İşçi kaydı bulunamadı!"})
    # Severance cost: 2x salary per worker
    cost = row['salary'] * 2 * row['count']
    with lock:
        if u['money'] < cost:
            conn.close()
            return jsonify({"success": False, "message": "Yetersiz bakiye!"})
        u['money'] -= cost
        save_user(u)
        conn.execute('DELETE FROM workers WHERE id = ?', (worker_id,))
        conn.execute('INSERT INTO transactions (owner, type, amount, time, meta) VALUES (?, ?, ?, ?, ?)',
                     (u['username'], 'workers_fire', -cost, time.time(), json.dumps({"id": worker_id})))
        conn.commit()
        conn.close()
    return jsonify({"success": True, "message": f"İşten çıkarıldı. Tazminat: {cost} TL"})

# ---------------------------------------------------------
# LOGISTICS API
# ---------------------------------------------------------
@app.route('/api/logistics/vehicles')
def api_logistics_vehicles():
    if 'user_id' not in session: return jsonify([]), 401
    u = get_user(session['user_id'])
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM vehicles WHERE owner = ?', (u['username'],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/logistics/vehicles/buy', methods=['POST'])
def api_logistics_buy_vehicle():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    data = request.json
    type_ = data.get('type')
    types = {
        "Kamyon": {"capacity": 100, "price": 250000},
        "Tır": {"capacity": 500, "price": 1000000},
        "Uçak": {"capacity": 2000, "price": 10000000},
        "Gemi": {"capacity": 10000, "price": 50000000}
    }
    if type_ not in types:
        return jsonify({"success": False, "message": "Geçersiz araç türü!"})
    info = types[type_]
    with lock:
        if u['money'] < info['price']:
            return jsonify({"success": False, "message": "Yetersiz bakiye!"})
        u['money'] -= info['price']
        save_user(u)
        conn = get_db_connection()
        conn.execute('INSERT INTO vehicles (owner, type, capacity, created_at) VALUES (?, ?, ?, ?)',
                     (u['username'], type_, info['capacity'], time.time()))
        conn.execute('INSERT INTO transactions (owner, type, amount, time, meta) VALUES (?, ?, ?, ?, ?)',
                     (u['username'], 'vehicle_buy', -info['price'], time.time(), json.dumps({"type": type_})))
        conn.commit()
        conn.close()
    return jsonify({"success": True, "message": f"{type_} satın alındı!"})

@app.route('/api/logistics/tasks')
def api_logistics_tasks():
    if 'user_id' not in session: return jsonify([]), 401
    u = get_user(session['user_id'])
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM logistics_tasks WHERE owner = ? ORDER BY created_at DESC', (u['username'],)).fetchall()
    # Auto-complete delivered tasks
    now = time.time()
    for r in rows:
        if r['delivered'] == 0 and now >= r['eta']:
            if r['destination'] == 'Market':
                avg_price = _avg_price_for(r['item']) or 1
                conn.execute('INSERT INTO marketplace_products (seller, name, description, price, stock, is_bot, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                             (u['username'], r['item'], f"Lojistik teslimatı", avg_price, r['amount'], 0, time.time()))
            elif r['destination'].startswith('Fabrika'):
                pass
            conn.execute('UPDATE logistics_tasks SET delivered = 1 WHERE id = ?', (r['id'],))
    conn.commit()
    rows = conn.execute('SELECT * FROM logistics_tasks WHERE owner = ? ORDER BY created_at DESC', (u['username'],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/logistics/create_task', methods=['POST'])
def api_logistics_create_task():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    data = request.json
    vehicle_id = int(data.get('vehicle_id', 0))
    item = (data.get('item') or '').strip()
    amount = int(data.get('amount', 0))
    destination = (data.get('destination') or '').strip()
    city_scope = (data.get('city_scope') or 'same').strip()
    if not item or amount <= 0 or destination not in ['Market'] + [f"Fabrika:{fid}" for fid in FACTORY_CONFIG.keys()]:
        return jsonify({"success": False, "message": "Geçersiz görev!"})
    conn = get_db_connection()
    v = conn.execute('SELECT * FROM vehicles WHERE id = ? AND owner = ?', (vehicle_id, u['username'])).fetchone()
    if not v:
        conn.close()
        return jsonify({"success": False, "message": "Araç bulunamadı!"})
    if amount > v['capacity']:
        conn.close()
        return jsonify({"success": False, "message": "Araç kapasitesi yetersiz!"})
    current = u['inventory'].get(item, 0)
    if current < amount:
        conn.close()
        return jsonify({"success": False, "message": "Envanter yetersiz!"})
    with lock:
        u['inventory'][item] = current - amount
        save_user(u)
        eta_delta = 600 if city_scope == 'same' else 1800
        ev = _get_current_event()
        if ev and ev.get('target', {}).get('type') == 'logistics':
            eta_delta = int(eta_delta * float(ev.get('logistics_cost_multiplier', 1.0)))
        eta = time.time() + eta_delta
        conn.execute('INSERT INTO logistics_tasks (owner, vehicle_id, item, amount, destination, city_scope, eta, delivered, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                     (u['username'], vehicle_id, item, amount, destination, city_scope, eta, 0, time.time()))
        conn.commit()
        conn.close()
    return jsonify({"success": True, "message": "Lojistik görevi oluşturuldu!"})
# ---------------------------------------------------------
# ECONOMY DASHBOARD STATS
# ---------------------------------------------------------
@app.route('/api/economy/stats')
def api_economy_stats():
    if 'user_id' not in session:
        return jsonify({
            "money": 0,
            "level": 1,
            "total_assets": 0,
            "worker_count": 0,
            "owned_land": 0,
            "factories_count": 0
        })
    u = get_user(session['user_id'])
    conn = get_db_connection()
    land_count = conn.execute('SELECT COUNT(*) as c FROM lands WHERE owner = ?', (u['username'],)).fetchone()['c']
    worker_count = conn.execute('SELECT COALESCE(SUM(count),0) as c FROM workers WHERE owner = ?', (u['username'],)).fetchone()['c']
    factory_count = len(u.get('factories', {}))
    lands_rows = conn.execute('SELECT price FROM lands WHERE owner = ?', (u['username'],)).fetchall()
    conn.close()
    total_land_value = sum([r['price'] for r in lands_rows])
    approx_factory_value = 0
    for fid, lvl in u.get('factories', {}).items():
        conf = FACTORY_CONFIG.get(fid)
        if conf:
            approx_factory_value += int(conf['cost'] * lvl * 0.8)
    total_assets = u.get('money', 0) + total_land_value + approx_factory_value
    return jsonify({
        "money": u.get('money', 0),
        "level": u.get('level', 1),
        "total_assets": total_assets,
        "worker_count": worker_count,
        "owned_land": land_count,
        "factories_count": factory_count
    })

# ---------------------------------------------------------
# NEW API: FACTORY LIST (guest-friendly)
# ---------------------------------------------------------
@app.route('/api/factory/list')
def api_factory_list():
    if 'user_id' not in session:
        rows = []
        for fid, conf in FACTORY_CONFIG.items():
            rows.append({
                "type": fid,
                "name": conf['name'],
                "product_type": conf.get('type'),
                "level": 0,
                "running": False,
                "rate_per_hour": 0,
                "worker_count": 0,
                "worker_capacity": conf.get('worker_capacity', 0),
                "bonus_pct": 0,
                "production_interval_hours": 3,
                "last_collect_hours_ago": 0,
                "production_duration_minutes": None,
                "remaining_seconds": None,
                "collectable": False,
                "daily_income": 0,
                "build_cost": conf.get('cost', 0),
            })
        return jsonify(rows)
    # Reuse logic from /api/factories but add build_cost
    u = get_user(session['user_id'])
    conn = get_db_connection()
    rows = []
    for fid, conf in FACTORY_CONFIG.items():
        lvl = u.get('factories', {}).get(fid, 0)
        running = bool(u.get('factory_running', {}).get(fid, True))
        assigned = conn.execute('SELECT COALESCE(SUM(count),0) AS c FROM factory_assignments WHERE owner = ? AND factory_type = ?', 
                                (u['username'], fid)).fetchone()['c']
        ev = _get_current_event()
        prod_mult = 1.0
        if ev and ev.get('target', {}).get('type') == 'production':
            prod_mult = float(ev.get('production_multiplier', 1.0))
        rate_per_hour = int(FACTORY_CONFIG[fid]['rate'] * max(1,lvl) * (1 + 0.05 * assigned) * prod_mult * (1 if running else 0))
        pr = conn.execute('SELECT price FROM prices WHERE item = ?', (FACTORY_CONFIG[fid]['type'],)).fetchone()
        price = pr['price'] if pr else 0
        daily_income = int(rate_per_hour * 24 * price)
        last_collect = u.get('factory_last_collect', {}).get(fid, u.get('factory_last_update', {}).get(fid, time.time()))
        elapsed_hours = round((time.time() - last_collect) / 3600.0, 2)
        capacity = FACTORY_CONFIG[fid].get('worker_capacity', 0) * max(1, lvl or 1)
        bonus_pct = int(0.05 * assigned * 100)
        run_start = u.get('factory_run_start', {}).get(fid)
        run_dur_min = u.get('factory_run_duration', {}).get(fid)
        remaining_seconds = None
        collectable = False
        production_duration_minutes = None
        if run_start and run_dur_min:
            production_duration_minutes = run_dur_min
            remaining_seconds = max(0, int(run_dur_min*60 - (time.time() - run_start)))
            collectable = remaining_seconds == 0
        rows.append({
            "type": fid,
            "name": FACTORY_CONFIG[fid]['name'],
            "product_type": FACTORY_CONFIG[fid].get('type'),
            "level": lvl,
            "running": running,
            "rate_per_hour": rate_per_hour,
            "worker_count": assigned,
            "worker_capacity": capacity,
            "bonus_pct": bonus_pct,
            "production_interval_hours": 3,
            "last_collect_hours_ago": elapsed_hours,
            "production_duration_minutes": production_duration_minutes,
            "remaining_seconds": remaining_seconds,
            "collectable": collectable,
            "daily_income": daily_income,
            "build_cost": FACTORY_CONFIG[fid].get('cost', 0),
        })
    conn.close()
    return jsonify(rows)

# ---------------------------------------------------------
# NEW API: INVENTORY GET (guest-friendly)
# ---------------------------------------------------------
@app.route('/api/inventory/get')
def api_inventory_get():
    if 'user_id' not in session:
        return jsonify({"items": [], "total_value": 0})
    u = get_user(session['user_id'])
    conn = get_db_connection()
    rows = conn.execute('SELECT item, price FROM prices').fetchall()
    conn.close()
    ev = _get_current_event()
    prices = {}
    for r in rows:
        p = r['price']
        name = r['item']
        if ev:
            if ev.get('target', {}).get('type') == 'item' and ev['target'].get('name') == name:
                p = max(1.0, p * ev.get('price_multiplier', 1.0))
            elif ev.get('target', {}).get('type') == 'prices_all':
                p = max(1.0, p * ev.get('price_multiplier', 1.0))
        prices[name] = p
    items = []
    total_value = 0
    for name, qty in u.get('inventory', {}).items():
        if qty <= 0:
            continue
        price = int(prices.get(name, 0))
        avg_buy = int((u.get("avg_buy_prices", {}) or {}).get(name, max(1, int(price * 0.9))))
        value = int(price * qty)
        pnl = int((price - avg_buy) * qty)
        total_value += value
        items.append({"name": name, "qty": qty, "price": price, "value": value, "avg_buy": avg_buy, "pnl": pnl})
    return jsonify({"items": items, "total_value": total_value})

@app.route('/api/market/overview')
def api_market_overview():
    focus_map = {
        "Buğday": "Buğday",
        "Demir": "Demir",
        "Altın": "Altın",
        "Teknoloji": "Elektronik"
    }
    conn = get_db_connection()
    out = []
    try:
        for label, item_name in focus_map.items():
            row = conn.execute('SELECT price, last_change FROM prices WHERE item = ?', (item_name,)).fetchone()
            price = int(row['price']) if row else 0
            last_change = float(row['last_change']) if row else 0.0
            trend = "Yükselişte" if last_change >= 0 else "Düşüşte"
            out.append({
                "label": label,
                "item": item_name,
                "price": price,
                "last_change": last_change,
                "trend": trend
            })
    finally:
        conn.close()
    return jsonify(out)

@app.route('/api/market/quick_buy', methods=['POST'])
def api_market_quick_buy():
    if 'user_id' not in session:
        return jsonify({"success": False}), 401
    data = request.json or {}
    item = str(data.get('item', '')).strip()
    qty = int(data.get('qty', 1) or 1)
    if qty <= 0:
        return jsonify({"success": False, "message": "Geçersiz miktar"})
    u = get_user(session['user_id'])
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT price FROM prices WHERE item = ?', (item,)).fetchone()
        if not row:
            return jsonify({"success": False, "message": "Ürün bulunamadı"})
        unit_price = int(row['price'])
        total = unit_price * qty
        if u.get('money', 0) < total:
            return jsonify({"success": False, "message": "Yetersiz bakiye"})
        with lock:
            old_qty = int(u.get('inventory', {}).get(item, 0))
            old_avg = int((u.get('avg_buy_prices', {}) or {}).get(item, unit_price))
            new_qty = old_qty + qty
            weighted = int(((old_qty * old_avg) + (qty * unit_price)) / max(1, new_qty))
            u['money'] = int(u.get('money', 0) - total)
            u.setdefault('inventory', {})[item] = new_qty
            u.setdefault('avg_buy_prices', {})[item] = weighted
            save_user(u)
    finally:
        conn.close()
    return jsonify({"success": True, "message": f"{qty} {item} alındı", "money": u.get('money', 0)})

@app.route('/api/market/quick_sell', methods=['POST'])
def api_market_quick_sell():
    if 'user_id' not in session:
        return jsonify({"success": False}), 401
    data = request.json or {}
    item = str(data.get('item', '')).strip()
    qty = int(data.get('qty', 1) or 1)
    if qty <= 0:
        return jsonify({"success": False, "message": "Geçersiz miktar"})
    u = get_user(session['user_id'])
    have = int(u.get('inventory', {}).get(item, 0))
    if have < qty:
        return jsonify({"success": False, "message": "Yetersiz stok"})
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT price FROM prices WHERE item = ?', (item,)).fetchone()
        if not row:
            return jsonify({"success": False, "message": "Ürün bulunamadı"})
        unit_price = int(row['price'])
        total = unit_price * qty
        with lock:
            u['inventory'][item] = have - qty
            u['money'] = int(u.get('money', 0) + total)
            save_user(u)
    finally:
        conn.close()
    return jsonify({"success": True, "message": f"{qty} {item} satıldı", "money": u.get('money', 0)})

# ---------------------------------------------------------
# ECONOMY API: RESOURCES
# ---------------------------------------------------------

def get_resources(owner):
    conn = get_db_connection()
    rows = conn.execute('SELECT item, quantity FROM resources WHERE owner = ?', (owner,)).fetchall()
    conn.close()
    res = {}
    for r in rows:
        res[r['item']] = res.get(r['item'], 0) + r['quantity']
    return res

def add_resource(owner, item, qty):
    conn = get_db_connection()
    conn.execute('INSERT INTO resources (owner, item, quantity, updated_at) VALUES (?, ?, ?, ?)',
                 (owner, item, qty, time.time()))
    conn.commit()
    conn.close()

def calculate_economy(user):
    now = time.time()
    last = user.get('resource_last_update', now)
    elapsed_min = (now - last) / 60.0
    if elapsed_min <= 0:
        return
    
    # Production based on lands and workers
    conn = get_db_connection()
    lands = conn.execute('SELECT * FROM lands WHERE owner = ?', (user['username'],)).fetchall()
    workers = conn.execute('SELECT * FROM workers WHERE owner = ?', (user['username'],)).fetchall()
    conn.close()
    
    # Worker productivity multiplier
    prod_mult = 1.0
    for w in workers:
        prod_mult += 0.05 * w['count'] * (w['productivity'] - 1.0)
    
    # Size multipliers
    size_mult = {"Küçük": 1.0, "Orta": 1.8, "Büyük": 3.2}
    
    # Base per land per minute
    base_rates = {
        "Tarla": {"Buğday": 5},
        "Sanayi Arsası": {"Demir": 2, "Taş": 3, "Kömür": 1},
        "Şehir Arsası": {} # used for buildings; no raw production
    }
    
    # Accrue resources
    for l in lands:
        rates = base_rates.get(l['type'], {})
        for item, rate in rates.items():
            qty = int(rate * size_mult.get(l['size'], 1.0) * prod_mult * elapsed_min)
            if qty > 0:
                add_resource(user['username'], item, qty)
    
    user['resource_last_update'] = now

@app.route('/api/resources')
def api_resources():
    if 'user_id' not in session: return jsonify({}), 401
    u = get_user(session['user_id'])
    with lock:
        calculate_economy(u)
        save_user(u)
    res = get_resources(u['username'])
    return jsonify(res)

@app.route('/api/inventory')
def api_inventory():
    if 'user_id' not in session:
        return jsonify({"items": [], "total_value": 0})
    u = get_user(session['user_id'])
    conn = get_db_connection()
    rows = conn.execute('SELECT item, price FROM prices').fetchall()
    conn.close()
    ev = _get_current_event()
    prices = {}
    for r in rows:
        p = r['price']
        name = r['item']
        if ev:
            if ev.get('target', {}).get('type') == 'item' and ev['target'].get('name') == name:
                p = max(1.0, p * ev.get('price_multiplier', 1.0))
            elif ev.get('target', {}).get('type') == 'prices_all':
                p = max(1.0, p * ev.get('price_multiplier', 1.0))
        prices[name] = p
    items = []
    total_value = 0
    for name, qty in u.get('inventory', {}).items():
        if qty <= 0: 
            continue
        price = int(prices.get(name, 0))
        value = int(price * qty)
        total_value += value
        items.append({"name": name, "qty": qty, "price": price, "value": value})
    return jsonify({"items": items, "total_value": total_value})
@app.route('/api/market')
def api_market():
    conn = get_db_connection()
    listings = conn.execute('SELECT * FROM market ORDER BY time DESC LIMIT 50').fetchall()
    # Attach prices snapshot
    prices_rows = conn.execute('SELECT * FROM prices').fetchall()
    # Simple supply/demand based tweak on each call (10s gate)
    now = time.time()
    for pr in prices_rows:
        last_upd = pr['updated_at']
        if now - last_upd >= 10:
            # Demand proxy: count of listings with low stock vs high
            # Supply proxy: resources table aggregate
            items = [r['item'] for r in listings]
            demand_factor = items.count(pr['item']) * 0.01
            supply_rows = conn.execute('SELECT COALESCE(SUM(quantity),0) AS q FROM resources WHERE item = ?', (pr['item'],)).fetchone()
            supply_q = supply_rows['q']
            supply_factor = (supply_q / 1000.0) * 0.01
            delta = (demand_factor - supply_factor)
            # Clamp delta
            delta = max(-0.05, min(0.05, delta))
            new_price = max(1.0, pr['price'] * (1.0 + delta))
            last_change = new_price - pr['price']
            conn.execute('UPDATE prices SET price = ?, last_change = ?, updated_at = ? WHERE item = ?',
                         (new_price, last_change, now, pr['item']))
    conn.commit()
    # Re-read
    prices_rows = conn.execute('SELECT * FROM prices').fetchall()
    conn.close()
    
    items = {
        "Odun": {"name": "Odun", "rarity": 1},
        "Taş": {"name": "Taş", "rarity": 1},
        "Demir": {"name": "Demir", "rarity": 2},
        "Altın": {"name": "Altın", "rarity": 3},
        "Elmas": {"name": "Elmas", "rarity": 4},
        "Petrol": {"name": "Petrol", "rarity": 3},
        "Çelik": {"name": "Çelik", "rarity": 3},
    }
    
    # Simulate Economy
    ev = _get_current_event()
    economy = {"event_message": "Piyasa Stabil", "multiplier": 1.0, "trend": "stable"}
    if ev:
        ttl = ev.get('title', 'Olay')
        end_time = ev.get('end_time')
        mult = ev.get('price_multiplier') or ev.get('production_multiplier') or ev.get('logistics_cost_multiplier') or 1.0
        economy = {"event_message": f"{ttl}", "multiplier": mult, "trend": "up" if mult > 1 else ("down" if mult < 1 else "stable"), "end_time": end_time}
    
    return jsonify({
        "listings": [dict(ix) for ix in listings],
        "items": items,
        "economy": economy,
        "prices": [dict(p) for p in prices_rows]
    })

@app.route('/api/market/prices')
def api_market_prices():
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM prices').fetchall()
    conn.close()
    ev = _get_current_event()
    out = []
    for r in rows:
        pr = dict(r)
        if ev:
            if ev.get('target', {}).get('type') == 'item' and ev['target'].get('name') == pr['item']:
                pr['price'] = max(1.0, pr['price'] * ev.get('price_multiplier', 1.0))
            elif ev.get('target', {}).get('type') == 'prices_all':
                pr['price'] = max(1.0, pr['price'] * ev.get('price_multiplier', 1.0))
        out.append(pr)
    return jsonify(out)

@app.route('/api/news')
def api_news():
    conn = get_db_connection()
    last = conn.execute('SELECT * FROM news ORDER BY id DESC LIMIT 1').fetchone()
    now = time.time()
    if not last or (now - last['created_at']) > random.randint(300, 600):
        choices = ["Odun","Demir","Taş","Kömür","Buğday","Çelik","Plastik","Elektronik"]
        it = random.choice(choices)
        direction = random.choice(['up','down'])
        title = f"{it} {'talebi yükseldi' if direction=='up' else 'üretimi arttı'}"
        body = "Piyasa haberleri fiyatları etkiliyor."
        conn.execute('INSERT INTO news (title, body, created_at) VALUES (?, ?, ?)', (title, body, now))
        # Apply small price nudge
        pr = conn.execute('SELECT * FROM prices WHERE item = ?', (it,)).fetchone()
        if pr:
            factor = 1.03 if direction == 'up' else 0.97
            new_price = max(1.0, pr['price'] * factor)
            conn.execute('UPDATE prices SET price = ?, last_change = ?, updated_at = ? WHERE item = ?', 
                         (new_price, new_price - pr['price'], now, it))
        conn.commit()
        last = conn.execute('SELECT * FROM news ORDER BY id DESC LIMIT 1').fetchone()
    # Return recent 10
    rows = conn.execute('SELECT * FROM news ORDER BY id DESC LIMIT 10').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/buy', methods=['POST'])
def buy():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    data = request.json
    
    # Implement buy from market
    # This requires looking up the order in DB
    order_id = data.get('order_id')
    qty = data.get('adet')
    
    conn = get_db_connection()
    listing = conn.execute('SELECT * FROM market WHERE id = ?', (order_id,)).fetchone()
    
    if not listing:
        conn.close()
        return jsonify({"success": False, "message": "İlan bulunamadı!"})
        
    if listing['adet'] < qty:
        conn.close()
        return jsonify({"success": False, "message": "Yetersiz stok!"})
        
    cost = listing['fiyat'] * qty
    
    with lock:
        if u['money'] < cost:
            conn.close()
            return jsonify({"success": False, "message": "Yetersiz bakiye!"})
            
        # Update Buyer
        u['money'] -= cost
        item_name = listing['item']
        u['inventory'][item_name] = u['inventory'].get(item_name, 0) + qty
        # Event participation bonus XP
        ev = _get_current_event()
        if ev:
            u['xp'] = u.get('xp', 0) + 5
            check_level_up(u)
        save_user(u)
        
        # Update Seller
        seller = get_user(listing['satici'])
        if seller:
            seller['money'] += cost
            save_user(seller)
            
        # Update Market DB
        if listing['adet'] == qty:
            conn.execute('DELETE FROM market WHERE id = ?', (order_id,))
        else:
            conn.execute('UPDATE market SET adet = adet - ? WHERE id = ?', (qty, order_id))
        conn.commit()
        
    conn.close()
    return jsonify({"success": True, "message": f"{qty} adet {item_name} alındı!"})

@app.route('/sell', methods=['POST'])
def sell():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    data = request.json
    
    item = data.get('item')
    qty = int(data.get('adet', 0))
    price = int(data.get('fiyat', 0))
    
    if qty <= 0 or price <= 0:
        return jsonify({"success": False, "message": "Geçersiz miktar/fiyat!"})
        
    with lock:
        current_qty = u['inventory'].get(item, 0)
        if current_qty < qty:
            return jsonify({"success": False, "message": "Yetersiz stok!"})
            
        u['inventory'][item] -= qty
        # Event participation bonus XP
        ev = _get_current_event()
        if ev:
            u['xp'] = u.get('xp', 0) + 5
            check_level_up(u)
        save_user(u)
        
        conn = get_db_connection()
        conn.execute('INSERT INTO market (satici, item, adet, fiyat, time) VALUES (?, ?, ?, ?, ?)',
                     (u['username'], item, qty, price, time.time()))
        conn.commit()
        conn.close()
        
    return jsonify({"success": True, "message": "İlan oluşturuldu!"})

# Factory Actions
@app.route('/api/factory_status/<fid>')
def factory_status(fid):
    if 'user_id' not in session: return jsonify({}), 401
    u = get_user(session['user_id'])
    
    conf = FACTORY_CONFIG.get(fid)
    if not conf: return jsonify({}), 404
    
    level = u['factories'].get(fid, 0)
    storage = u['factory_storage'].get(fid, 0)
    
    next_level = level + 1
    next_cost = conf['cost'] * next_level
    
    # Calculate next mat cost logic (simplified)
    next_mat = None
    next_mat_cost = 0
    if level > 0:
        # Example: Upgrade needs previous tier material
        pass 
        
    return jsonify({
        "level": level,
        "storage": storage,
        "capacity": conf['capacity'] * level if level > 0 else conf['capacity'],
        "rate": conf['rate'] * level if level > 0 else conf['rate'],
        "next_cost": next_cost,
        "next_mat": next_mat,
        "next_mat_cost": next_mat_cost,
        "is_boosted": u.get("factory_boosts", {}).get(fid, 0) > time.time(),
        "running": bool(u.get("factory_running", {}).get(fid, True))
    })

@app.route('/api/upgrade_factory/<fid>', methods=['POST'])
def upgrade_factory(fid):
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    conf = FACTORY_CONFIG.get(fid)
    if not conf: return jsonify({"success": False}), 404
    
    with lock:
        current_lvl = u['factories'].get(fid, 0)
        next_lvl = current_lvl + 1
        
        # Special case: Level 0 -> 1 (Build)
        cost = conf['cost'] * next_lvl
        
        if u['money'] < cost:
             return jsonify({"success": False, "message": "Yetersiz bakiye!"})
             
        # Check unlock level
        if u['level'] < conf['unlock_lvl']:
             return jsonify({"success": False, "message": f"Seviye {conf['unlock_lvl']} gerekli!"})
             
        u['money'] -= cost
        u['factories'][fid] = next_lvl
        # Mission progress for upgrade
        m = u.get('mission') or {}
        if m.get('kind') == 'upgrade':
            m['current_qty'] = int(m.get('current_qty', 0)) + 1
            if m['current_qty'] >= m.get('target_qty', 1):
                u['money'] += int(m.get('reward', 0))
                u['xp'] += int(m.get('reward', 0) // 2)
                u['mission'] = {"kind": "produce", "description": "100 ürün üret!", "target_qty": 100, "current_qty": 0, "reward": 1000}
            else:
                u['mission'] = m
        save_user(u)
    
    # Compute new production metrics for response
    conn = get_db_connection()
    assigned = conn.execute('SELECT COALESCE(SUM(count),0) AS c FROM factory_assignments WHERE owner = ? AND factory_type = ?', 
                            (u['username'], fid)).fetchone()['c']
    conn.close()
    running = bool(u.get('factory_running', {}).get(fid, True))
    rate_per_hour = int(conf['rate'] * max(1, next_lvl) * (1 + 0.05 * assigned) * (1 if running else 0))
    next_cost = conf['cost'] * (next_lvl + 1)
    return jsonify({
        "success": True,
        "message": "Fabrika başarıyla yükseltildi!",
        "new_level": next_lvl,
        "new_production": rate_per_hour,
        "next_cost": next_cost
    })

@app.route('/api/factories')
def api_factories():
    if 'user_id' not in session:
        rows = []
        for fid, conf in FACTORY_CONFIG.items():
            rows.append({
                "type": fid,
                "name": conf['name'],
                "product_type": conf.get('type'),
                "level": 0,
                "running": False,
                "rate_per_hour": 0,
                "worker_count": 0,
                "worker_capacity": conf.get('worker_capacity', 0),
                "bonus_pct": 0,
                "production_interval_hours": 3,
                "last_collect_hours_ago": 0,
                "production_duration_minutes": None,
                "remaining_seconds": None,
                "collectable": False,
                "daily_income": 0
            })
        return jsonify(rows)
    u = get_user(session['user_id'])
    conn = get_db_connection()
    rows = []
    for fid, conf in FACTORY_CONFIG.items():
        lvl = u.get('factories', {}).get(fid, 0)
        running = bool(u.get('factory_running', {}).get(fid, True))
        assigned = conn.execute('SELECT COALESCE(SUM(count),0) AS c FROM factory_assignments WHERE owner = ? AND factory_type = ?', 
                                (u['username'], fid)).fetchone()['c']
        # rate per hour
        ev = _get_current_event()
        prod_mult = 1.0
        if ev and ev.get('target', {}).get('type') == 'production':
            prod_mult = float(ev.get('production_multiplier', 1.0))
        rate_per_hour = int(conf['rate'] * max(1,lvl) * (1 + 0.05 * assigned) * prod_mult * (1 if running else 0))
        # approximate price from global prices
        pr = conn.execute('SELECT price FROM prices WHERE item = ?', (conf['type'],)).fetchone()
        price = pr['price'] if pr else 0
        daily_income = int(rate_per_hour * 24 * price)
        last_collect = u.get('factory_last_collect', {}).get(fid, u.get('factory_last_update', {}).get(fid, time.time()))
        elapsed_hours = round((time.time() - last_collect) / 3600.0, 2)
        capacity = conf.get('worker_capacity', 0) * max(1, lvl)
        bonus_pct = int(0.05 * assigned * 100)
        # Production countdown
        run_start = u.get('factory_run_start', {}).get(fid)
        run_dur_min = u.get('factory_run_duration', {}).get(fid)
        remaining_seconds = None
        collectable = False
        production_duration_minutes = None
        if run_start and run_dur_min:
            production_duration_minutes = run_dur_min
            remaining_seconds = max(0, int(run_dur_min*60 - (time.time() - run_start)))
            collectable = remaining_seconds == 0
        rows.append({
            "type": fid,
            "name": conf['name'],
            "level": lvl,
            "running": running,
            "rate_per_hour": rate_per_hour,
            "worker_count": assigned,
            "worker_capacity": capacity,
            "bonus_pct": bonus_pct,
            "production_interval_hours": 3,
            "last_collect_hours_ago": elapsed_hours,
            "production_duration_minutes": production_duration_minutes,
            "remaining_seconds": remaining_seconds,
            "collectable": collectable,
            "daily_income": daily_income
        })
    conn.close()
    return jsonify(rows)

@app.route('/api/factory/start', methods=['POST'])
def api_factory_start():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    fid = request.json.get('type')
    if fid not in FACTORY_CONFIG: return jsonify({"success": False, "message": "Geçersiz fabrika!"})
    with lock:
        fr = u.get('factory_running', {})
        fr[fid] = True
        u['factory_running'] = fr
        # start production run countdown
        lvl = u.get('factories', {}).get(fid, 1)
        conf = FACTORY_CONFIG.get(fid, {})
        base_dur = conf.get('duration_min')
        duration_min = base_dur if base_dur else max(2, 10 - 2 * (int(lvl) - 1))
        u.setdefault('factory_run_start', {})[fid] = time.time()
        u.setdefault('factory_run_duration', {})[fid] = duration_min
        save_user(u)
    return jsonify({"success": True, "message": "Üretim başlatıldı"})

@app.route('/api/factory/stop', methods=['POST'])
def api_factory_stop():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    fid = request.json.get('type')
    if fid not in FACTORY_CONFIG: return jsonify({"success": False, "message": "Geçersiz fabrika!"})
    with lock:
        fr = u.get('factory_running', {})
        fr[fid] = False
        u['factory_running'] = fr
        # clear production run
        rs = u.get('factory_run_start', {})
        rd = u.get('factory_run_duration', {})
        if fid in rs: del rs[fid]
        if fid in rd: del rd[fid]
        u['factory_run_start'] = rs
        u['factory_run_duration'] = rd
        save_user(u)
    return jsonify({"success": True, "message": "Üretim durduruldu"})

@app.route('/api/factory/assign_workers', methods=['POST'])
def api_factory_assign_workers():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    fid = request.json.get('type')
    count = int(request.json.get('count', 0))
    if fid not in FACTORY_CONFIG or count <= 0:
        return jsonify({"success": False, "message": "Geçersiz parametre!"})
    level = int(u.get('factories', {}).get(fid, 0))
    if level <= 0:
        return jsonify({"success": False, "message": "Önce fabrikayı kurmalısınız!"})
    capacity = FACTORY_CONFIG[fid].get('worker_capacity', 0) * level
    with lock:
        available = u.get('workers_available', 0)
        if available < count:
            return jsonify({"success": False, "message": "Yetersiz işçi havuzu!"})
        conn = get_db_connection()
        row = conn.execute('SELECT * FROM factory_assignments WHERE owner = ? AND factory_type = ?', (u['username'], fid)).fetchone()
        current = row['count'] if row else 0
        if current + count > capacity:
            conn.close()
            return jsonify({"success": False, "message": f"Kapasite dolu! (Kapasite: {capacity})"})
        if row:
            conn.execute('UPDATE factory_assignments SET count = count + ? WHERE id = ?', (count, row['id']))
        else:
            conn.execute('INSERT INTO factory_assignments (owner, factory_type, count, created_at) VALUES (?, ?, ?, ?)',
                         (u['username'], fid, count, time.time()))
        conn.commit()
        conn.close()
        u['workers_available'] = available - count
        save_user(u)
    return jsonify({"success": True, "message": "İşçi atandı"})

@app.route('/api/factory/unassign_workers', methods=['POST'])
def api_factory_unassign_workers():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    fid = request.json.get('type')
    count = int(request.json.get('count', 0))
    if fid not in FACTORY_CONFIG or count <= 0:
        return jsonify({"success": False, "message": "Geçersiz parametre!"})
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM factory_assignments WHERE owner = ? AND factory_type = ?', (u['username'], fid)).fetchone()
    if not row:
        conn.close()
        return jsonify({"success": False, "message": "Atama bulunamadı"})
    newc = max(0, row['count'] - count)
    conn.execute('UPDATE factory_assignments SET count = ? WHERE id = ?', (newc, row['id']))
    conn.commit()
    conn.close()
    with lock:
        u['workers_available'] = u.get('workers_available', 0) + min(count, row['count'])
        save_user(u)
    return jsonify({"success": True, "message": "İşçi çıkarıldı"})

@app.route('/api/factory/collect', methods=['POST'])
def collect_factory():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    data = request.json
    fid = data.get('factory_id')
    
    conf = FACTORY_CONFIG.get(fid)
    if not conf:
        return jsonify({"success": False, "message": "Geçersiz fabrika!"})
    with lock:
        now = time.time()
        last = u.get('factory_last_collect', {}).get(fid, u.get('factory_last_update', {}).get(fid, now))
        elapsed = now - last
        if elapsed <= 0:
            return jsonify({"success": False, "message": "Üretim yok!"})
        # Assigned workers
        conn = get_db_connection()
        assigned = conn.execute('SELECT COALESCE(SUM(count),0) AS c FROM factory_assignments WHERE owner = ? AND factory_type = ?', 
                                (u['username'], fid)).fetchone()['c']
        conn.close()
        worker_mult = 1.0 + (0.05 * assigned)
        level = u.get('factories', {}).get(fid, 0)
        running = bool(u.get('factory_running', {}).get(fid, True))
        # Boost
        is_boosted = u.get("factory_boosts", {}).get(fid, 0) > now
        ev = _get_current_event()
        prod_mult = 1.0
        if ev and ev.get('target', {}).get('type') == 'production':
            prod_mult = float(ev.get('production_multiplier', 1.0))
        rate_per_hour = conf["rate"] * max(1, level) * worker_mult * (2 if is_boosted else 1) * prod_mult * (1 if running else 0)
        produced = int((elapsed / 10800.0) * rate_per_hour)
        if produced <= 0:
            # Update last collect anyway to avoid zero spam on tiny intervals
            u.setdefault('factory_last_collect', {})[fid] = now
            save_user(u)
            return jsonify({"success": False, "message": "Üretim henüz birikmedi!"})
        rtype = conf['type']
        if rtype.startswith('Vehicle:') and u.get('factory_run_start', {}).get(fid):
            kind = rtype.split(':',1)[1]
            capacities = {"Kamyon": 500, "Tır": 1000, "Uçak": 2000, "Gemi": 10000}
            cap = capacities.get(kind, 100)
            conn = get_db_connection()
            conn.execute('INSERT INTO vehicles (owner, type, capacity, created_at) VALUES (?, ?, ?, ?)',
                         (u['username'], kind, cap, time.time()))
            conn.commit()
            conn.close()
            # reset run to require next start
            u['factory_run_start'].pop(fid, None)
            u['factory_run_duration'].pop(fid, None)
        else:
            u['inventory'][rtype] = u['inventory'].get(rtype, 0) + produced
        # Random critical bonus +20% chance
        if random.random() < 0.1:
            produced = int(produced * 1.2)
        u.setdefault('factory_last_collect', {})[fid] = now
        # XP reward proportional
        u['xp'] += produced
        # Mission progress: production
        m = u.get('mission') or {}
        if m.get('kind') == 'produce':
            m['current_qty'] = int(m.get('current_qty', 0)) + int(produced)
            if m['current_qty'] >= m.get('target_qty', 100):
                u['money'] += int(m.get('reward', 0))
                u['xp'] += int(m.get('reward', 0) // 2)
                # Next mission: buy workers
                u['mission'] = {"kind": "workers", "description": "5 işçi satın al!", "target_qty": 5, "current_qty": 0, "reward": 1500}
            else:
                u['mission'] = m
        check_level_up(u)
        save_user(u)
    return jsonify({"success": True, "message": f"{produced} {conf['type']} toplandı!"})

@app.route('/api/factory/boost', methods=['POST'])
def boost_factory():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    u = get_user(session['user_id'])
    data = request.json
    fid = data.get('factory_id')
    
    # Cost: 1000 TL for 5 mins
    COST = 1000
    DURATION = 300
    
    with lock:
        if u['money'] < COST:
             return jsonify({"success": False, "message": "Yetersiz bakiye (1000 TL gerekli)!"})
             
        if u.get("factory_boosts", {}).get(fid, 0) > time.time():
             return jsonify({"success": False, "message": "Zaten aktif!"})
             
        u['money'] -= COST
        if "factory_boosts" not in u: u["factory_boosts"] = {}
        u["factory_boosts"][fid] = time.time() + DURATION
        save_user(u)
        
    return jsonify({"success": True, "message": "Fabrika hızlandırıldı!"})

# Chat
@app.route('/api/chat', methods=['GET', 'POST'])
def api_chat():
    conn = get_db_connection()
    if request.method == 'POST':
        if 'user_id' not in session: return jsonify({}), 401
        u = get_user(session['user_id'])
        now = time.time()
        if u.get('chat_mute_until', 0) > now:
            return jsonify({"success": False, "message": "Chat geçici olarak engellendi"}), 403
        msg = (request.json.get('message') or '').strip()
        if msg:
            banned = ["salak","aptal","küfür","yarrak","orospu","piç","lanet","fuck","shit"]
            moderated = False
            low = msg.lower()
            for w in banned:
                if w in low:
                    moderated = True
                    msg = msg.lower().replace(w, "***")
            if moderated:
                u['chat_violations'] = int(u.get('chat_violations', 0)) + 1
                if u['chat_violations'] >= 3:
                    u['chat_mute_until'] = now + 300
                    u['chat_violations'] = 0
                save_user(u)
            conn.execute('INSERT INTO chat (username, message, time) VALUES (?, ?, ?)',
                         (u['username'], msg, time.strftime('%H:%M')))
            conn.commit()
        return jsonify({"success": True, "moderated": moderated})
    else:
        msgs = conn.execute('SELECT * FROM chat ORDER BY id DESC LIMIT 50').fetchall()
        # Return reversed (oldest first)
        return jsonify([dict(m) for m in msgs][::-1])

@app.route('/api/leaderboard')
def api_leaderboard():
    conn = get_db_connection()
    # This is tricky with JSON data. We need to fetch all and sort in Py
    users = conn.execute('SELECT * FROM users').fetchall()
    conn.close()
    
    leaderboard = []
    for user_row in users:
        d = json.loads(user_row['data'])
        leaderboard.append({
            "username": user_row['username'],
            "money": d.get('money', 0),
            "net_worth": d.get('net_worth', 0)
        })
        
    # Sort by net worth
    leaderboard.sort(key=lambda x: x['net_worth'], reverse=True)
    return jsonify(leaderboard[:20])

# ---------------------------------------------------------
# NEW MECHANICS ROUTES
# ---------------------------------------------------------

@app.route('/api/daily_bonus', methods=['POST'])
def daily_bonus():
    if 'username' not in session: return jsonify({"success": False}), 401
    u = get_user(session['username'])
    if not u: return jsonify({"success": False}), 401
    
    with lock:
        now = time.time()
        last = u.get("last_daily_bonus", 0)
        
        if (now - last) < 86400:
            remaining = int(86400 - (now - last))
            hours = remaining // 3600
            mins = (remaining % 3600) // 60
            return jsonify({"success": False, "message": f"Henüz zamanı gelmedi! ({hours}sa {mins}dk)"})
            
        reward = 1000 + (u["level"] * 100)
        u["money"] += reward
        u["xp"] += 200
        u["last_daily_bonus"] = now
        
        check_level_up(u)
        save_user(u)
        
        return jsonify({"success": True, "message": f"Günlük ödül: {reward} TL ve 200 XP alındı!"})

@app.route('/api/venture', methods=['POST'])
def venture():
    if 'username' not in session: return jsonify({"success": False}), 401
    u = get_user(session['username'])
    if not u: return jsonify({"success": False}), 401
    
    data = request.json
    amount = int(data.get('amount', 0))
    
    if amount <= 0:
        return jsonify({"success": False, "message": "Geçersiz miktar!"})
        
    with lock:
        if u["money"] < amount:
            return jsonify({"success": False, "message": "Yetersiz bakiye!"})
            
        u["money"] -= amount
        
        # Risk: 50% chance
        if random.random() < 0.5:
            # Win 2x
            win = amount * 2
            u["money"] += win
            msg = f"BAŞARILI! Risk aldın ve {win} TL kazandın!"
            success = True
        else:
            # Lose
            msg = f"BAŞARISIZ! {amount} TL kaybettin..."
            success = False
            
        save_user(u)
        return jsonify({"success": True, "message": msg, "win": success})

@app.route('/api/expedition/start', methods=['POST'])
def start_expedition():
    if 'username' not in session: return jsonify({"success": False}), 401
    u = get_user(session['username'])
    if not u: return jsonify({"success": False}), 401
    
    data = request.json
    type_ = data.get('type') # short, medium, long
    
    with lock:
        if u.get("expedition"):
             return jsonify({"success": False, "message": "Zaten bir seferdesin!"})
             
        # Config
        types = {
            "short": {"name": "Kısa Mesafe", "time": 300, "cost": 100, "reward_mult": 1.5},
            "medium": {"name": "Orta Mesafe", "time": 900, "cost": 500, "reward_mult": 2.0},
            "long": {"name": "Uzun Mesafe", "time": 3600, "cost": 2000, "reward_mult": 3.0}
        }
        
        if type_ not in types:
             return jsonify({"success": False, "message": "Geçersiz sefer türü!"})
             
        conf = types[type_]
        
        if u["money"] < conf["cost"]:
             return jsonify({"success": False, "message": "Yetersiz bakiye!"})
             
        u["money"] -= conf["cost"]
        u["expedition"] = {
            "type": type_,
            "start_time": time.time(),
            "end_time": time.time() + conf["time"],
            "cost": conf["cost"],
            "reward_mult": conf["reward_mult"]
        }
        
        save_user(u)
        return jsonify({"success": True, "message": f"{conf['name']} seferi başladı!"})

@app.route('/api/expedition/collect', methods=['POST'])
def collect_expedition():
    if 'username' not in session: return jsonify({"success": False}), 401
    u = get_user(session['username'])
    if not u: return jsonify({"success": False}), 401
    
    with lock:
        exp = u.get("expedition")
        if not exp:
             return jsonify({"success": False, "message": "Aktif sefer yok!"})
             
        if time.time() < exp["end_time"]:
             return jsonify({"success": False, "message": "Sefer henüz bitmedi!"})
             
        # Reward
        base_reward = exp["cost"] * exp["reward_mult"]
        # Add random bonus
        bonus = random.randint(0, int(base_reward * 0.2))
        total = int(base_reward + bonus)
        
        u["money"] += total
        u["xp"] += int(total / 10)
        u["expedition"] = None
        
        check_level_up(u)
        save_user(u)
        
        return jsonify({"success": True, "message": f"Sefer tamamlandı! {total} TL ve {int(total/10)} XP kazanıldı!"})

# ---------------------------------------------------------
# ADMIN PAGES & ACTIONS
# ---------------------------------------------------------

@app.route('/admin')
def admin_page():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    # Strictly check for 'Paramen42' and admin flag
    if session.get('user_id') != 'Paramen42' or not session.get('is_admin'):
        return redirect(url_for('game'))
    
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM users').fetchall()
    market_count = conn.execute('SELECT COUNT(*) AS c FROM market').fetchone()['c']
    conn.close()
    
    users = []
    total_money = 0
    for r in rows:
        d = json.loads(r['data'])
        conn2 = get_db_connection()
        uid_row = conn2.execute('SELECT user_id FROM user_ids WHERE username = ?', (r['username'],)).fetchone()
        conn2.close()
        factories_count = len(d.get('factories', {}))
        users.append({
            "user_id": uid_row['user_id'] if uid_row else None,
            "username": r['username'],
            "money": d.get('money', 0),
            "level": d.get('level', 1),
            "factories_count": factories_count,
            "last_login": d.get('last_login', 0),
            "is_banned": d.get('is_banned', False)
        })
        total_money += d.get('money', 0)
    
    stats = {
        "total_users": len(users),
        "total_money": total_money,
        "market_listings": market_count
    }
    
    return render_template('admin.html', users=users, stats=stats, active_page='admin')

def _admin_guard():
    return None

@app.route('/admin/users')
def admin_users():
    guard = _admin_guard()
    if guard: return guard
    return redirect(url_for('admin_page'))

@app.route('/admin/economy')
def admin_economy():
    guard = _admin_guard()
    if guard: return guard
    return redirect(url_for('admin_page'))

@app.route('/admin/control')
def admin_control():
    guard = _admin_guard()
    if guard: return guard
    return redirect(url_for('admin_page'))

@app.route('/api/admin/action', methods=['POST'])
def admin_action():
    if 'user_id' not in session: return jsonify({"success": False}), 401
    if not session.get('is_admin'): return jsonify({"success": False}), 403
    
    data = request.json
    target = data.get('username')
    action = data.get('action')
    amount = data.get('amount')
    meta_raw = data.get('meta')
    meta = None
    try:
        if meta_raw:
            meta = json.loads(meta_raw)
    except Exception:
        meta = None
    
    if not target or not action:
        return jsonify({"success": False, "message": "Eksik parametre!"})
    
    u = get_user(target)
    if not u:
        return jsonify({"success": False, "message": "Kullanıcı bulunamadı!"})
    
    with lock:
        if action == 'add_money':
            val = int(amount or 0)
            u['money'] = u.get('money', 0) + max(0, val)
            try:
                conn = get_db_connection()
                uid_row = conn.execute('SELECT user_id FROM user_ids WHERE username = ?', (u['username'],)).fetchone()
                if uid_row:
                    conn.execute('INSERT INTO user_logs (user_id, action, amount, timestamp) VALUES (?, ?, ?, ?)', (uid_row['user_id'], 'admin_add_money', val, time.time()))
                    conn.commit()
                conn.close()
            except Exception:
                pass
        elif action == 'remove_money':
            val = int(amount or 0)
            u['money'] = max(0, u.get('money', 0) - max(0, val))
            try:
                conn = get_db_connection()
                uid_row = conn.execute('SELECT user_id FROM user_ids WHERE username = ?', (u['username'],)).fetchone()
                if uid_row:
                    conn.execute('INSERT INTO user_logs (user_id, action, amount, timestamp) VALUES (?, ?, ?, ?)', (uid_row['user_id'], 'admin_remove_money', val, time.time()))
                    conn.commit()
                conn.close()
            except Exception:
                pass
        elif action == 'set_level':
            val = int(amount or 1)
            u['level'] = max(1, val)
        elif action == 'ban_user':
            u['is_banned'] = True
        elif action == 'unban_user':
            u['is_banned'] = False
        elif action == 'reset_password':
            # set new password
            new_pw = str(amount or '').strip()
            if len(new_pw) < 6:
                return jsonify({"success": False, "message": "Yeni şifre en az 6 karakter!"})
            conn = get_db_connection()
            conn.execute('UPDATE users SET password_hash = ? WHERE username = ?', (generate_password_hash(new_pw), u['username']))
            conn.commit()
            conn.close()
        elif action == 'rename_user':
            new_name = str(amount or '').strip()
            if not new_name:
                return jsonify({"success": False, "message": "Yeni kullanıcı adı gerekli!"})
            # enforce uniqueness
            conn = get_db_connection()
            exists = conn.execute('SELECT username FROM users WHERE username = ?', (new_name,)).fetchone()
            if exists:
                conn.close()
                return jsonify({"success": False, "message": "Bu kullanıcı adı zaten alınmış"})
            # update primary and all references
            conn.execute('UPDATE users SET username = ? WHERE username = ?', (new_name, u['username']))
            # update mapping
            conn.execute('UPDATE user_ids SET username = ? WHERE username = ?', (new_name, u['username']))
            # update related tables
            for tbl_col in [
                ('lands','owner'),('workers','owner'),('buildings','owner'),('resources','owner'),
                ('factories','owner'),('transactions','owner'),('factory_assignments','owner'),
                ('vehicles','owner'),('logistics_tasks','owner'),('marketplace_products','seller'),('chat','username')
            ]:
                tbl, col = tbl_col
                conn.execute(f'UPDATE {tbl} SET {col} = ? WHERE {col} = ?', (new_name, u['username']))
            conn.commit()
            conn.close()
            u['username'] = new_name
        elif action == 'give_land':
            if not meta or not all(k in meta for k in ['type','size','location']):
                return jsonify({"success": False, "message": "Meta eksik: type,size,location"})
            conn = get_db_connection()
            price = int(meta.get('price', 0))
            conn.execute('INSERT INTO lands (owner, type, size, location, price, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                         (u['username'], meta['type'], meta['size'], meta['location'], price, time.time()))
            conn.execute('INSERT INTO transactions (owner, type, amount, time, meta) VALUES (?, ?, ?, ?, ?)',
                         (u['username'], 'admin_give_land', 0, time.time(), json.dumps(meta)))
            conn.commit()
            conn.close()
        elif action == 'give_factory':
            if not meta or not all(k in meta for k in ['type','level']):
                return jsonify({"success": False, "message": "Meta eksik: type,level"})
            # store high-level ownership in factories table, and user dict for gameplay
            fid = meta['type']
            lvl = int(meta['level'])
            u.setdefault('factories', {})[fid] = lvl
            conn = get_db_connection()
            conn.execute('INSERT INTO factories (owner, type, level, created_at) VALUES (?, ?, ?, ?)',
                         (u['username'], fid, lvl, time.time()))
            conn.execute('INSERT INTO transactions (owner, type, amount, time, meta) VALUES (?, ?, ?, ?, ?)',
                         (u['username'], 'admin_give_factory', 0, time.time(), json.dumps(meta)))
            conn.commit()
            conn.close()
        elif action == 'set_factory_level':
            if not meta or not all(k in meta for k in ['type','level']):
                return jsonify({"success": False, "message": "Meta eksik: type,level"})
            fid = meta['type']
            lvl = int(meta['level'])
            u.setdefault('factories', {})[fid] = lvl
        elif action == 'reset_economy':
            conn = get_db_connection()
            conn.execute('DELETE FROM lands WHERE owner = ?', (u['username'],))
            conn.execute('DELETE FROM workers WHERE owner = ?', (u['username'],))
            conn.execute('DELETE FROM buildings WHERE owner = ?', (u['username'],))
            conn.execute('DELETE FROM resources WHERE owner = ?', (u['username'],))
            conn.execute('DELETE FROM transactions WHERE owner = ?', (u['username'],))
            conn.commit()
            conn.close()
            # reset in-user aggregates
            u['inventory'] = {}
            u['factories'] = {}
            u['factory_storage'] = {}
            u['factory_last_update'] = {}
        elif action == 'delete_user':
            conn = get_db_connection()
            conn.execute('DELETE FROM users WHERE username = ?', (target,))
            conn.commit()
            conn.close()
            return jsonify({"success": True, "message": "Kullanıcı silindi!"})
        else:
            return jsonify({"success": False, "message": "Geçersiz eylem!"})
        
        save_user(u)
    
    return jsonify({"success": True, "message": "İşlem tamamlandı!"})

@app.route('/api/admin/user_logs')
def api_admin_user_logs():
    guard = _admin_guard()
    if guard: 
        if isinstance(guard, str):
            return jsonify({"success": False}), 403
        return guard
    username = request.args.get('username', '').strip()
    if not username:
        return jsonify([])
    uid = get_user_id_by_username(username)
    if not uid:
        return jsonify([])
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM user_logs WHERE user_id = ? ORDER BY timestamp DESC LIMIT 200', (uid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

def _wrap_routes_with_session_cleanup():
    for endpoint, view_func in list(app.view_functions.items()):
        if endpoint == 'static':
            continue
        if getattr(view_func, "_session_cleanup_wrapped", False):
            continue

        @wraps(view_func)
        def _wrapped(*args, __view_func=view_func, **kwargs):
            try:
                return __view_func(*args, **kwargs)
            finally:
                try:
                    db.session.remove()
                except Exception:
                    pass

        _wrapped._session_cleanup_wrapped = True
        app.view_functions[endpoint] = _wrapped

_wrap_routes_with_session_cleanup()

@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()

@app.errorhandler(500)
def internal_error(error):
    """500 hatası olduğunda uygulamanın çökmesini engelle"""
    print(f"500 Internal Server Error: {error}")
    return "Bir hata oluştu ama uygulama hala ayakta!", 500

@app.errorhandler(404)
def not_found_error(error):
    """404 hatası yönlendirme"""
    return redirect(url_for('game'))

@app.errorhandler(Exception)
def handle_exception(error):
    """Genel exception handler"""
    print(f"Unhandled Exception: {error}")
    return "Bir hata oluştu ama uygulama hala ayakta!", 500

# Initial startup tasks for both dev and prod (Gunicorn/Render)
print("=== UYGULAMA BAŞLATILIYOR ===")
print(f"Python Version: {sys.version}")
print(f"Working Directory: {os.getcwd()}")

try:
    print("Environment Variables:")
    print(f"  DATABASE_URL: {os.environ.get('DATABASE_URL', 'BULUNAMADI')[:50]}...")
    print(f"  PORT: {os.environ.get('PORT', '5000')}")
    print(f"  FLASK_ENV: {os.environ.get('FLASK_ENV', 'development')}")
    
    with app.app_context():
        print("Veritabanı başlatılıyor...")
        init_db()
        print("Admin kullanıcısı kontrol ediliyor...")
        create_admin_if_not_exists()
        print("=== UYGULAMA BAŞARILIYLA BAŞLATILDI ===")
except Exception as e:
    print(f"!!! Startup initialization failed: {e}")
    import traceback
    traceback.print_exc()

@app.route('/bombala-beni-06')
def veritabani_temizlik():
    try:
        with app.app_context():
            db.drop_all()
            db.create_all()
        return "BUM! Eski hesaplar uçtu. Şimdi gidip Paramen42 olarak kayıt olabilirsin!"
    except Exception as e:
        return f"Hata: {str(e)}", 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    # Debug modu geçici olarak açık - hata mesajlarını görmek için
    debug_mode = os.environ.get("FLASK_ENV") != "production"
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
