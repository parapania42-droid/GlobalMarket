import requests
import time
import json

BASE_URL = "http://localhost:5000"
SESSION = requests.Session()

def log(msg, status="INFO"):
    print(f"[{status}] {msg}")

def test_new_mechanics():
    # 1. Login/Register
    username = f"test_mech_{int(time.time())}"
    password = "password123"
    
    log(f"Registering user: {username}")
    res = SESSION.post(f"{BASE_URL}/register", json={"username": username, "password": password})
    if res.status_code != 200 or not res.json().get("success"):
        log("Registration failed", "ERROR")
        return

    log("Logging in...")
    res = SESSION.post(f"{BASE_URL}/login", json={"username": username, "password": password})
    if res.status_code != 200 or not res.json().get("success"):
        log("Login failed", "ERROR")
        return

    # 2. Test Daily Bonus
    log("Testing Daily Bonus...")
    res = SESSION.post(f"{BASE_URL}/api/daily_bonus")
    data = res.json()
    if data.get("success"):
        log("Daily bonus claimed successfully", "PASS")
    else:
        log(f"Daily bonus failed: {data.get('message')}", "FAIL")

    # 3. Test Venture (Risk System)
    log("Testing Venture (Risk System)...")
    # First, ensure we have money (daily bonus gave some)
    res = SESSION.get(f"{BASE_URL}/api/me")
    money = res.json().get("money", 0)
    log(f"Current Money: {money}")
    
    if money >= 100:
        res = SESSION.post(f"{BASE_URL}/api/venture", json={"amount": 100})
        data = res.json()
        log(f"Venture result: {data.get('message')}", "PASS" if res.status_code == 200 else "FAIL")
    else:
        log("Not enough money for venture test", "WARN")

    # 4. Test Expedition
    log("Testing Expedition Start...")
    res = SESSION.post(f"{BASE_URL}/api/expedition/start", json={"type": "short"})
    data = res.json()
    if data.get("success"):
        log("Expedition started", "PASS")
        
        # Verify status
        res = SESSION.get(f"{BASE_URL}/api/me")
        me = res.json()
        if me.get("expedition_active"):
            log("Expedition active in user profile", "PASS")
        else:
            log("Expedition NOT active in profile", "FAIL")
            
        # Try to collect immediately (should fail)
        log("Testing Premature Collection...")
        res = SESSION.post(f"{BASE_URL}/api/expedition/collect")
        if not res.json().get("success"):
            log("Premature collection blocked correctly", "PASS")
        else:
            log("Premature collection allowed (Error)", "FAIL")
            
    else:
        log(f"Expedition start failed: {data.get('message')}", "FAIL")

if __name__ == "__main__":
    try:
        test_new_mechanics()
    except Exception as e:
        log(f"Exception: {e}", "ERROR")
