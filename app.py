import sqlite3
import json
import time
import random
import threading
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
    "wood": {"name": "Kereste Fabrikası", "cost": 100, "rate": 10, "capacity": 100, "unlock_lvl": 1, "type": "Odun"},
    "stone": {"name": "Taş Ocağı", "cost": 500, "rate": 5, "capacity": 50, "unlock_lvl": 2, "type": "Taş"},
    "iron": {"name": "Demir Madeni", "cost": 2000, "rate": 3, "capacity": 30, "unlock_lvl": 3, "type": "Demir"},
    "gold": {"name": "Altın Madeni", "cost": 10000, "rate": 1, "capacity": 10, "unlock_lvl": 5, "type": "Altın"},
    "diamond": {"name": "Elmas Madeni", "cost": 50000, "rate": 0.5, "capacity": 5, "unlock_lvl": 10, "type": "Elmas"},
    "oil": {"name": "Petrol Rafinerisi", "cost": 100000, "rate": 2, "capacity": 20, "unlock_lvl": 15, "type": "Petrol"},
    "steel": {"name": "Çelik Fabrikası", "cost": 250000, "rate": 1, "capacity": 15, "unlock_lvl": 20, "type": "Çelik"}
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
        
        rate = conf["rate"] * level * prod_mult
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
    return render_template('game.html')

@app.route('/leaderboard')
def leaderboard_page():
    return render_template('game.html') # Re-use game template but JS handles it? Or simple template? 
    # Context says "leaderboard and admin stats load correctly from SQLite". 
    # Let's assume game.html handles it via JS or it's a separate view.
    # But usually user expects a page. I'll redirect to game and let modal handle it, 
    # OR serve a simple page. Given previous context, it likely shares style.
    # For now, let's just serve game.html which has JS to check path.

@app.route('/api/me')
def api_me():
    if 'username' not in session: return jsonify({}), 401
    u = get_user(session['username'])
    if not u: return jsonify({}), 401
    
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
        
        save_user(u)
        
    u["factory_config"] = FACTORY_CONFIG
    return jsonify(u)

@app.route('/api/market')
def api_market():
    conn = get_db_connection()
    listings = conn.execute('SELECT * FROM market ORDER BY time DESC LIMIT 50').fetchall()
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
        "economy": economy
    })

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
        "is_boosted": u.get("factory_boosts", {}).get(fid, 0) > time.time()
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

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
