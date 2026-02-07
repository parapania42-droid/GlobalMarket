import sqlite3
import json
import time
import random
import threading
import os
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'global_market_secret_key_v2'

# Concurrency lock
lock = threading.Lock()

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

FACTORY_CONFIG = {
    "wood": {"name": "Odun Fabrikası", "cost": 100, "rate": 10, "capacity": 100, "unlock_lvl": 1, "type": "Odun"},
    "stone": {"name": "Taş Ocağı", "cost": 500, "rate": 5, "capacity": 50, "unlock_lvl": 2, "type": "Taş"},
    "iron": {"name": "Demir Madeni", "cost": 2000, "rate": 3, "capacity": 30, "unlock_lvl": 3, "type": "Demir"},
    "coal": {"name": "Kömür Madeni", "cost": 1500, "rate": 4, "capacity": 40, "unlock_lvl": 3, "type": "Kömür"},
    "steel": {"name": "Çelik Fabrikası", "cost": 250000, "rate": 1, "capacity": 15, "unlock_lvl": 20, "type": "Çelik"},
    "plastic": {"name": "Plastik Fabrikası", "cost": 500000, "rate": 1.5, "capacity": 20, "unlock_lvl": 25, "type": "Plastik"},
    "electronics": {"name": "Elektronik Fabrikası", "cost": 1000000, "rate": 0.8, "capacity": 10, "unlock_lvl": 30, "type": "Elektronik"}
}

# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

def get_db_connection():
    conn = sqlite3.connect('globalmarket.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Users table
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                data TEXT NOT NULL
            )
        ''')
        
        # Market table
        c.execute('''
            CREATE TABLE IF NOT EXISTS market (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                satici TEXT,
                item TEXT,
                adet INTEGER,
                fiyat INTEGER,
                time REAL
            )
        ''')
        
        # Chat table
        c.execute('''
            CREATE TABLE IF NOT EXISTS chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                message TEXT,
                time TEXT
            )
        ''')
        
        # Lands table
        c.execute('''
            CREATE TABLE IF NOT EXISTS lands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner TEXT NOT NULL,
                type TEXT NOT NULL,
                size TEXT NOT NULL,
                location TEXT NOT NULL,
                price INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
        ''')
        
        # Workers table
        c.execute('''
            CREATE TABLE IF NOT EXISTS workers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner TEXT NOT NULL,
                type TEXT NOT NULL,
                count INTEGER NOT NULL,
                salary INTEGER NOT NULL,
                productivity REAL NOT NULL,
                created_at REAL NOT NULL
            )
        ''')
        
        # Factories table (expanded system)
        c.execute('''
            CREATE TABLE IF NOT EXISTS factories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner TEXT NOT NULL,
                type TEXT NOT NULL,
                level INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
        ''')
        
        # Buildings table
        c.execute('''
            CREATE TABLE IF NOT EXISTS buildings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner TEXT NOT NULL,
                type TEXT NOT NULL,
                level INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
        ''')
        
        # Resources table
        c.execute('''
            CREATE TABLE IF NOT EXISTS resources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner TEXT NOT NULL,
                item TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                updated_at REAL NOT NULL
            )
        ''')
        
        # Transactions table
        c.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner TEXT NOT NULL,
                type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                time REAL NOT NULL,
                meta TEXT
            )
        ''')
        
        # Global Prices table
        c.execute('''
            CREATE TABLE IF NOT EXISTS prices (
                item TEXT PRIMARY KEY,
                price REAL NOT NULL,
                last_change REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        ''')
        
        # Market News table
        c.execute('''
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT,
                created_at REAL NOT NULL
            )
        ''')
        
        # Factory Assignments
        c.execute('''
            CREATE TABLE IF NOT EXISTS factory_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner TEXT NOT NULL,
                factory_type TEXT NOT NULL,
                count INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
        ''')
        
        # Seed default prices if empty
        items = ["Odun","Taş","Demir","Kömür","Buğday","Çelik","Plastik","Elektronik"]
        base_prices = {
            "Odun": 20, "Taş": 25, "Demir": 100, "Kömür": 40, "Buğday": 15,
            "Çelik": 300, "Plastik": 200, "Elektronik": 800
        }
        for it in items:
            c.execute('INSERT OR IGNORE INTO prices (item, price, last_change, updated_at) VALUES (?, ?, ?, ?)',
                      (it, base_prices[it], 0.0, time.time()))
        
        conn.commit()
        conn.close()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"Database initialization failed: {e}")

# Initialize DB immediately for Gunicorn/Render
init_db()

def get_user(username):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()
    if user:
        u_data = json.loads(user['data'])
        u_data['username'] = username # ensure username is in data
        
        # Migration/Repair for missing keys
        if "inventory" not in u_data: u_data["inventory"] = {}
        if "factories" not in u_data: u_data["factories"] = {}
        if "factory_storage" not in u_data: u_data["factory_storage"] = {}
        if "factory_last_update" not in u_data: u_data["factory_last_update"] = {}
        if "net_worth" not in u_data: u_data["net_worth"] = 0
        if "xp" not in u_data: u_data["xp"] = 0
        if "level" not in u_data: u_data["level"] = 1
        if "money" not in u_data: u_data["money"] = 0
        
        return u_data
    return None

def save_user(user_data):
    username = user_data['username']
    conn = get_db_connection()
    conn.execute('UPDATE users SET data = ? WHERE username = ?', 
                 (json.dumps(user_data), username))
    conn.commit()
    conn.close()

def create_user(username, password):
    if get_user(username):
        return False
        
    pw_hash = generate_password_hash(password)
    
    # Initial State
    initial_data = {
        "username": username,
        "money": 1000,
        "level": 1,
        "xp": 0,
        "inventory": {"Odun": 0, "Taş": 0},
        "factories": {},
        "factory_storage": {},
        "factory_last_update": {},
        "factory_boosts": {},
        "net_worth": 1000,
        "mission": {"description": "İlk fabrikanı kur!", "target_qty": 1, "current_qty": 0, "reward": 500},
        "last_active": time.time(),
        "is_afk": False,
        "is_admin": False,
        "expedition": None, # {type, start_time, end_time, cost}
        "last_daily_bonus": 0
    }
    
    conn = get_db_connection()
    conn.execute('INSERT INTO users (username, password_hash, data) VALUES (?, ?, ?)',
                 (username, pw_hash, json.dumps(initial_data)))
    conn.commit()
    conn.close()
    return True

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

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('game'))
    return redirect(url_for('login_page'))

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'GET':
        return render_template('login.html')
        
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()
    
    if user and check_password_hash(user['password_hash'], password):
        session['username'] = username
        return jsonify({"success": True})
    
    return jsonify({"success": False, "message": "Hatalı kullanıcı adı veya şifre!"})

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')

    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if create_user(username, password):
        return jsonify({"success": True, "message": "Kayıt başarılı! Giriş yapabilirsiniz."})
    return jsonify({"success": False, "message": "Bu kullanıcı adı alınmış!"})

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login_page'))

@app.route('/game')
def game():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    return render_template('game.html', active_page='game')

@app.route('/leaderboard')
def leaderboard_page():
    return render_template('leaderboard.html', active_page='leaderboard')

@app.route('/guide')
def guide_page():
    return render_template('guide.html', active_page='guide')

@app.route('/market')
def market_page():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    return render_template('market.html', active_page='market')
@app.route('/factory')
def factory_page():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    return render_template('factory.html', active_page='factory')

@app.route('/resources')
def resources_page():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    return render_template('resources.html', active_page='resources')

@app.route('/land')
def land_page():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    return render_template('land.html', active_page='land')

@app.route('/workers')
def workers_page():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    return render_template('workers.html', active_page='workers')

@app.route('/realestate')
def realestate_page():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    return render_template('realestate.html', active_page='realestate')

@app.route('/api/me')
def api_me():
    if 'username' not in session: return jsonify({}), 401
    u = get_user(session['username'])
    if not u: return jsonify({}), 401
    if u.get("is_banned"):
        return jsonify({"message": "Hesabınız yasaklandı"}), 403
    
    with lock:
        calculate_production(u)
        
        # Check Daily Bonus Availability
        now = time.time()
        last = u.get("last_daily_bonus", 0)
        u["daily_bonus_available"] = (now - last) >= 86400
        
        # Check Expedition
        exp = u.get("expedition")
        u["expedition_active"] = False
        if exp:
            u["expedition_active"] = True
            u["expedition_end_time"] = exp["end_time"]
            if now >= exp["end_time"]:
                u["expedition_completed"] = True
        
        # Admin flag for Paramen42
        u["is_admin"] = (u["username"] == "Paramen42")
        
        save_user(u)
        
    u["factory_config"] = FACTORY_CONFIG
    return jsonify(u)

# ---------------------------------------------------------
# ECONOMY API: LAND
# ---------------------------------------------------------

@app.route('/api/land/list')
def api_land_list():
    if 'username' not in session: return jsonify({}), 401
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM lands WHERE owner = ?', (session['username'],)).fetchall()
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
    if 'username' not in session: return jsonify({"success": False}), 401
    u = get_user(session['username'])
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

@app.route('/api/workers/hire', methods=['POST'])
def api_workers_hire():
    if 'username' not in session: return jsonify({"success": False}), 401
    u = get_user(session['username'])
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
    if 'username' not in session: return jsonify({"success": False}), 401
    u = get_user(session['username'])
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
# ECONOMY DASHBOARD STATS
# ---------------------------------------------------------
@app.route('/api/economy/stats')
def api_economy_stats():
    if 'username' not in session: return jsonify({}), 401
    u = get_user(session['username'])
    conn = get_db_connection()
    land_count = conn.execute('SELECT COUNT(*) as c FROM lands WHERE owner = ?', (u['username'],)).fetchone()['c']
    worker_count = conn.execute('SELECT COALESCE(SUM(count),0) as c FROM workers WHERE owner = ?', (u['username'],)).fetchone()['c']
    factory_count = len(u.get('factories', {}))
    # total assets: money + land prices + approximate factories
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
    if 'username' not in session: return jsonify({}), 401
    u = get_user(session['username'])
    with lock:
        calculate_economy(u)
        save_user(u)
    res = get_resources(u['username'])
    return jsonify(res)

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
    economy = {
        "event_message": "Piyasa Stabil",
        "multiplier": 1.0,
        "trend": "stable"
    }
    
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
    return jsonify([dict(r) for r in rows])

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
    if 'username' not in session: return jsonify({"success": False}), 401
    u = get_user(session['username'])
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
    if 'username' not in session: return jsonify({"success": False}), 401
    u = get_user(session['username'])
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
    if 'username' not in session: return jsonify({}), 401
    u = get_user(session['username'])
    
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
    if 'username' not in session: return jsonify({"success": False}), 401
    u = get_user(session['username'])
    conf = FACTORY_CONFIG.get(fid)
    if not conf: return jsonify({"success": False}), 404
    
    with lock:
        current_lvl = u['factories'].get(fid, 0)
        next_lvl = current_lvl + 1
        
        # Special case: Level 0 -> 1 (Build)
        cost = conf['cost'] * next_lvl
        
        if u['money'] < cost:
             return jsonify({"success": False, "message": "Yetersiz para!"})
             
        # Check unlock level
        if u['level'] < conf['unlock_lvl']:
             return jsonify({"success": False, "message": f"Seviye {conf['unlock_lvl']} gerekli!"})
             
        u['money'] -= cost
        u['factories'][fid] = next_lvl
        save_user(u)
        
    return jsonify({"success": True, "message": "Fabrika yükseltildi!"})

@app.route('/api/factories')
def api_factories():
    if 'username' not in session: return jsonify([]), 401
    u = get_user(session['username'])
    conn = get_db_connection()
    rows = []
    for fid, conf in FACTORY_CONFIG.items():
        lvl = u.get('factories', {}).get(fid, 0)
        running = bool(u.get('factory_running', {}).get(fid, True))
        assigned = conn.execute('SELECT COALESCE(SUM(count),0) AS c FROM factory_assignments WHERE owner = ? AND factory_type = ?', 
                                (u['username'], fid)).fetchone()['c']
        # rate per hour (base rate per minute * 60)
        rate_per_hour = int(conf['rate'] * max(1,lvl) * (1 + 0.05 * assigned) * (1 if running else 0))
        # approximate price from global prices
        pr = conn.execute('SELECT price FROM prices WHERE item = ?', (conf['type'],)).fetchone()
        price = pr['price'] if pr else 0
        daily_income = int(rate_per_hour * 24 * price)
        rows.append({
            "type": fid, "name": conf['name'], "level": lvl, "running": running,
            "rate_per_hour": rate_per_hour, "worker_count": assigned, "daily_income": daily_income
        })
    conn.close()
    return jsonify(rows)

@app.route('/api/factory/start', methods=['POST'])
def api_factory_start():
    if 'username' not in session: return jsonify({"success": False}), 401
    u = get_user(session['username'])
    fid = request.json.get('type')
    if fid not in FACTORY_CONFIG: return jsonify({"success": False, "message": "Geçersiz fabrika!"})
    with lock:
        fr = u.get('factory_running', {})
        fr[fid] = True
        u['factory_running'] = fr
        save_user(u)
    return jsonify({"success": True, "message": "Üretim başlatıldı"})

@app.route('/api/factory/stop', methods=['POST'])
def api_factory_stop():
    if 'username' not in session: return jsonify({"success": False}), 401
    u = get_user(session['username'])
    fid = request.json.get('type')
    if fid not in FACTORY_CONFIG: return jsonify({"success": False, "message": "Geçersiz fabrika!"})
    with lock:
        fr = u.get('factory_running', {})
        fr[fid] = False
        u['factory_running'] = fr
        save_user(u)
    return jsonify({"success": True, "message": "Üretim durduruldu"})

@app.route('/api/factory/assign_workers', methods=['POST'])
def api_factory_assign_workers():
    if 'username' not in session: return jsonify({"success": False}), 401
    u = get_user(session['username'])
    fid = request.json.get('type')
    count = int(request.json.get('count', 0))
    if fid not in FACTORY_CONFIG or count <= 0:
        return jsonify({"success": False, "message": "Geçersiz parametre!"})
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM factory_assignments WHERE owner = ? AND factory_type = ?', (u['username'], fid)).fetchone()
    if row:
        conn.execute('UPDATE factory_assignments SET count = count + ? WHERE id = ?', (count, row['id']))
    else:
        conn.execute('INSERT INTO factory_assignments (owner, factory_type, count, created_at) VALUES (?, ?, ?, ?)',
                     (u['username'], fid, count, time.time()))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "İşçi atandı"})

@app.route('/api/factory/unassign_workers', methods=['POST'])
def api_factory_unassign_workers():
    if 'username' not in session: return jsonify({"success": False}), 401
    u = get_user(session['username'])
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
    return jsonify({"success": True, "message": "İşçi çıkarıldı"})

@app.route('/api/factory/collect', methods=['POST'])
def collect_factory():
    if 'username' not in session: return jsonify({"success": False}), 401
    u = get_user(session['username'])
    data = request.json
    fid = data.get('factory_id')
    
    with lock:
        calculate_production(u) # Ensure latest
        storage = u['factory_storage'].get(fid, 0)
        if storage <= 0:
             return jsonify({"success": False, "message": "Depo boş!"})
             
        conf = FACTORY_CONFIG.get(fid)
        rtype = conf['type']
        
        u['inventory'][rtype] = u['inventory'].get(rtype, 0) + int(storage)
        u['factory_storage'][fid] = 0
        
        # XP Reward
        u['xp'] += int(storage)
        check_level_up(u)
        
        save_user(u)
        
    return jsonify({"success": True, "message": f"{int(storage)} {rtype} toplandı!"})

@app.route('/api/factory/boost', methods=['POST'])
def boost_factory():
    if 'username' not in session: return jsonify({"success": False}), 401
    u = get_user(session['username'])
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
        if 'username' not in session: return jsonify({}), 401
        msg = request.json.get('message')
        if msg:
            conn.execute('INSERT INTO chat (username, message, time) VALUES (?, ?, ?)',
                         (session['username'], msg, time.strftime('%H:%M')))
            conn.commit()
        return jsonify({"success": True})
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
    if 'username' not in session:
        return redirect(url_for('login_page'))
    if session['username'] != 'Paramen42':
        return redirect(url_for('game'))
    
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM users').fetchall()
    market_count = conn.execute('SELECT COUNT(*) AS c FROM market').fetchone()['c']
    conn.close()
    
    users = []
    total_money = 0
    for r in rows:
        d = json.loads(r['data'])
        users.append({
            "username": r['username'],
            "money": d.get('money', 0),
            "level": d.get('level', 1),
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
    if 'username' not in session:
        return redirect(url_for('login_page'))
    if session['username'] != 'Paramen42':
        return redirect(url_for('game'))
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
    if 'username' not in session: return jsonify({"success": False}), 401
    if session['username'] != 'Paramen42': return jsonify({"success": False}), 403
    
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
        elif action == 'remove_money':
            val = int(amount or 0)
            u['money'] = max(0, u.get('money', 0) - max(0, val))
        elif action == 'set_level':
            val = int(amount or 1)
            u['level'] = max(1, val)
        elif action == 'ban_user':
            u['is_banned'] = True
        elif action == 'unban_user':
            u['is_banned'] = False
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

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
