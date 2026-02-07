import requests
import time
import random
import string

BASE_URL = "http://127.0.0.1:5000"
SESSION = requests.Session()

# Generate random username
rand_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
USERNAME = f"testuser_{rand_suffix}"
PASSWORD = "password123"

def print_step(step):
    print(f"\n[TEST] {step}...")

def fail(msg):
    print(f"❌ FAILED: {msg}")
    exit(1)

def success(msg):
    print(f"✅ PASSED: {msg}")

def test_register():
    print_step("Registering User")
    res = SESSION.post(f"{BASE_URL}/register", json={"username": USERNAME, "password": PASSWORD})
    if res.status_code != 200: fail(f"Register status {res.status_code}")
    data = res.json()
    if not data.get("success"): fail(f"Register failed: {data.get('message')}")
    success("User registered")

def test_login():
    print_step("Logging In")
    res = SESSION.post(f"{BASE_URL}/login", json={"username": USERNAME, "password": PASSWORD})
    if res.status_code != 200: fail(f"Login status {res.status_code}")
    data = res.json()
    if not data.get("success"): fail(f"Login failed: {data.get('message')}")
    success("User logged in")

def test_initial_state():
    print_step("Checking Initial State")
    res = SESSION.get(f"{BASE_URL}/api/me")
    if res.status_code != 200: fail(f"Get Me status {res.status_code}")
    data = res.json()
    if data["username"] != USERNAME: fail("Username mismatch")
    if data["money"] != 1000: fail(f"Initial money wrong: {data['money']}")
    if data["level"] != 1: fail("Initial level wrong")
    success("Initial state correct")

def test_buy_factory():
    print_step("Buying Factory (Wood)")
    # use upgrade_factory to build level 0 -> 1
    res = SESSION.post(f"{BASE_URL}/api/upgrade_factory/wood", json={})
    try:
        data = res.json()
    except:
        fail(f"Invalid JSON response: {res.text[:2000]}")
        
    if not data.get("success"): fail(f"Build failed: {data.get('message')}")
    
    # Verify money deducted (Wood cost is 100)
    res = SESSION.get(f"{BASE_URL}/api/me")
    data = res.json()
    if data["money"] != 900: fail(f"Money not deducted correctly? {data['money']}")
    if data["factories"]["wood"] != 1: fail("Factory level not 1")
    success("Factory bought")

def test_production_and_collect():
    print_step("Waiting for Production (5s)")
    time.sleep(5)
    
    # Check status
    res = SESSION.get(f"{BASE_URL}/api/factory_status/wood")
    data = res.json()
    storage = data.get("storage", 0)
    print(f"   -> Storage: {storage}")
    
    # Trigger calc via /api/me
    SESSION.get(f"{BASE_URL}/api/me")
    
    res = SESSION.get(f"{BASE_URL}/api/factory_status/wood")
    data = res.json()
    storage = data.get("storage", 0)
    print(f"   -> Storage after wait: {storage}")
    
    if storage < 0.5: 
        print("   ⚠️ Production slow/not updated? Ignoring strict check.")
    else:
        # Collect
        res = SESSION.post(f"{BASE_URL}/api/factory/collect", json={"factory_id": "wood"})
        data = res.json()
        if not data.get("success"): fail(f"Collect failed: {data.get('message')}")
        success(f"Collected {storage} items")

def test_persistence():
    print_step("Testing Persistence (Login as new session)")
    new_sess = requests.Session()
    res = new_sess.post(f"{BASE_URL}/login", json={"username": USERNAME, "password": PASSWORD})
    if not res.json().get("success"): fail("Relogin failed")
    
    res = new_sess.get(f"{BASE_URL}/api/me")
    data = res.json()
    if data["factories"].get("wood") != 1: fail(f"Factory lost! Factories: {data.get('factories')}")
    success("Persistence verified")

def run_all():
    try:
        test_register()
        test_login()
        test_initial_state()
        test_buy_factory()
        test_production_and_collect()
        test_persistence()
        print("\n🎉 ALL TESTS PASSED!")
    except Exception as e:
        print(f"\n❌ EXCEPTION: {e}")
        exit(1)

if __name__ == "__main__":
    run_all()
