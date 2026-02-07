// ===== GLOBAL STATE =====
let pollingInterval = null;
let globalItems = {};
let globalFactoryConfig = {};
let globalPlayer = {};
let currentSort = 'time';

// Previous States for Diff/Animation
let previousInventory = {};
let previousMarketPrices = {};
let previousMoney = 0;

// Timers
let __factoryModalTimer = null;
let __factoryModalCurrentId = null;
let __eventTimer = null;
let __expeditionTimer = null;

// Helper: Format Money
function formatMoney(amount) {
    return new Intl.NumberFormat('tr-TR').format(amount) + ' TL';
}

// Helper: Simple Toast/Alert wrapper
function showMessage(msg, type = 'info') {
    // For now, using alert/console to ensure visibility as requested
    // Later can be upgraded to a custom toast
    if (type === 'error') console.error(msg);
    alert(msg);
}

// ---------------------------------------------------------
// INITIALIZATION
// ---------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    const path = window.location.pathname;
    
    if (path === '/leaderboard') {
        fetchLeaderboard();
        fetchUserData();
        setInterval(fetchUserData, 10000);
    } else if (path === '/game') {
        startPolling();
        
        // Bind Enter key for chat
        const chatInput = document.getElementById('chat-input');
        if (chatInput) {
            chatInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') sendChat();
            });
        }
        // Home widgets: prices, news, leaderboard
        fetchPricesHome();
        fetchNewsHome();
        fetchLeaderboardHome();
        setInterval(fetchPricesHome, 10000);
        setInterval(fetchNewsHome, 60000);
        setInterval(fetchLeaderboardHome, 15000);
    } else {
        fetchUserData();
        setInterval(fetchUserData, 10000);
    }
});

// ---------------------------------------------------------
// AUTHENTICATION
// ---------------------------------------------------------

async function login() {
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;

    if (!username || !password) {
        alert("Lütfen kullanıcı adı ve şifre girin!");
        return;
    }

    try {
        const res = await fetch('/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, password})
        });
        const data = await res.json();
        
        if (data.success) {
            window.location.href = '/game';
        } else {
            alert(data.message);
        }
    } catch (e) {
        console.error(e);
        alert("Bağlantı hatası!");
    }
}

async function register() {
    const username = document.getElementById('reg-username').value;
    const password = document.getElementById('reg-password').value;

    if (!username || !password) {
        alert("Lütfen kullanıcı adı ve şifre girin!");
        return;
    }

    try {
        const res = await fetch('/register', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, password})
        });
        const data = await res.json();
        
        if (data.success) {
            alert(data.message);
            window.location.href = '/login';
        } else {
            alert(data.message);
        }
    } catch (e) {
        console.error(e);
        alert("Bağlantı hatası!");
    }
}

// ---------------------------------------------------------
// CORE GAME LOOP
// ---------------------------------------------------------

function startPolling() {
    // Initial fetch
    updateAll();
    
    // Main Loop (2s)
    pollingInterval = setInterval(updateAll, 2000);
    
    // Chat Loop (3s)
    setInterval(fetchChat, 3000);
    fetchChat();
    
    // Local Timer Loop (1s) for countdowns
    setInterval(updateLocalTimers, 1000);
}

async function updateAll() {
    try {
        await Promise.all([
            fetchMarket(), 
            fetchUserData()
        ]);
        fetchEconomyStats();
    } catch (e) {
        console.error("Update failed:", e);
    }
}

function updateLocalTimers() {
    // Update Expedition Timer
    if (globalPlayer.expedition_active && globalPlayer.expedition_end_time) {
        const now = Date.now() / 1000;
        const diff = globalPlayer.expedition_end_time - now;
        
        const timerEl = document.getElementById('exp-timer');
        const statusEl = document.getElementById('exp-status');
        const collectBtn = document.getElementById('exp-collect-btn');
        
        if (diff <= 0) {
            if (timerEl) timerEl.textContent = "00:00";
            if (statusEl) statusEl.textContent = "Tamamlandı!";
            if (collectBtn) collectBtn.style.display = 'block';
        } else {
            const m = Math.floor(diff / 60);
            const s = Math.floor(diff % 60);
            if (timerEl) timerEl.textContent = `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
            if (statusEl) statusEl.textContent = "Seferde...";
            if (collectBtn) collectBtn.style.display = 'none';
        }
    }
}

// ---------------------------------------------------------
// DATA FETCHING & RENDERING
// ---------------------------------------------------------

async function fetchMarket() {
    try {
        const res = await fetch('/api/market');
        if (!res.ok) return;
        const data = await res.json();
        globalItems = data.items || {};
        
        renderMarket(data);
    } catch (e) {
        console.error("Market fetch error:", e);
    }
}

async function fetchUserData() {
    try {
        const res = await fetch(`/api/me`);
        if (res.status === 401) {
            window.location.href = '/login';
            return;
        }
        if (res.status === 403) {
            alert("Hesabınız yasaklandı!");
            window.location.href = '/login';
            return;
        }
        
        const player = await res.json();
        globalPlayer = player;
        globalFactoryConfig = player.factory_config || {};
        
        renderHUD(player);
        renderInventory(player);
        renderFactories(player);
        renderMissions(player);
        renderNewMechanics(player); // New mechanics UI
        
    } catch (e) {
        console.error("User data fetch error:", e);
    }
}

// ---------------------------------------------------------
// RENDER FUNCTIONS (UI)
// ---------------------------------------------------------

function renderHUD(player) {
    document.getElementById('hud-username').textContent = player.username;
    const moneyEl = document.getElementById('hud-money');
    const oldMoney = previousMoney || 0;
    moneyEl.textContent = formatMoney(player.money);
    if (player.money > oldMoney) {
        const diff = player.money - oldMoney;
        const rect = moneyEl.getBoundingClientRect();
        const float = document.createElement('div');
        float.className = 'money-float';
        float.textContent = `+${new Intl.NumberFormat('tr-TR').format(diff)} TL`;
        float.style.left = `${rect.left}px`;
        float.style.top = `${rect.top}px`;
        document.body.appendChild(float);
        setTimeout(() => { float.remove(); }, 1000);
    }
    previousMoney = player.money;
    document.getElementById('hud-level').textContent = player.level;
    document.getElementById('hud-xp').textContent = `${player.xp} / ${player.level * 1000}`;
    
    // XP Bar
    const xpPercent = Math.min(100, (player.xp / (player.level * 1000)) * 100);
    document.getElementById('hud-xp-bar').style.width = `${xpPercent}%`;
    
    // Net Worth
    const netWorthEl = document.getElementById('net-worth');
    if (netWorthEl) netWorthEl.textContent = `Net Servet: ${formatMoney(player.net_worth)}`;

    // AFK Warning
    const activeStatusEl = document.getElementById('active-status');
    if (activeStatusEl) {
        activeStatusEl.style.display = player.is_afk ? 'block' : 'none';
        if (player.is_afk) activeStatusEl.textContent = '⚠️ AFK MODU: Üretim %90 Azaldı!';
    }
    
    // Daily Bonus Button
    const dailyBtn = document.getElementById('daily-bonus-btn');
    if (dailyBtn) {
        // Show button if bonus is available, hide if not
        dailyBtn.style.display = player.daily_bonus_available ? 'inline-block' : 'none';
    }

    // Admin Button
    const adminBtn = document.getElementById('nav-admin-btn');
    if (adminBtn) adminBtn.style.display = player.is_admin ? 'inline-block' : 'none';
}

async function fetchEconomyStats() {
    try {
        const res = await fetch('/api/economy/stats');
        if (!res.ok) return;
        const s = await res.json();
        const m = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
        m('dash-money', formatMoney(s.money));
        m('dash-level', s.level);
        m('dash-assets', formatMoney(s.total_assets));
        m('dash-workers', s.worker_count);
        m('dash-land', s.owned_land);
        m('dash-factories', s.factories_count);
        
        // Simple trends box based on market economy banner
        const trendBox = document.getElementById('trend-box');
        if (trendBox) {
            trendBox.textContent = 'Trend verileri pazar üzerinden güncelleniyor.';
        }
        // Earnings box from recent transactions — fetch minimal list later
        const earnBox = document.getElementById('earnings-box');
        if (earnBox) {
            earnBox.textContent = 'Son işlemler yakında listelenecek.';
        }
    } catch (e) {}
}
function renderInventory(player) {
    const invList = document.getElementById('inventory-list');
    const sellSelect = document.getElementById('sell-item');
    if (!invList) return;

    let invHtml = '';
    let selectHtml = '';
    let hasItems = false;

    // Sort inventory by name
    const items = Object.entries(player.inventory).sort((a, b) => a[0].localeCompare(b[0]));

    for (const [item, qty] of items) {
        if (qty > 0) {
            hasItems = true;
            const info = globalItems[item] || {name: item, rarity: 1};
            
            // Icon handling
            const icon = getResourceIcon(item);

            // Animation Check
            const prevQty = previousInventory[item] || 0;
            let animClass = '';
            if (qty > prevQty) animClass = 'anim-increase';
            else if (qty < prevQty) animClass = 'anim-decrease';

            invHtml += `
                <div class="inventory-item rarity-${info.rarity} ${animClass}" style="border: 1px solid #333; display:flex; justify-content:space-between; align-items:center;">
                    <div style="display:flex; align-items:center; gap:10px;">
                        <span style="font-size:1.5em">${icon}</span>
                        <div>
                            <div style="font-weight:bold" class="rarity-text-${info.rarity}">${info.name}</div>
                            <div style="font-size:0.8em; color:var(--text-muted)">Stok: <span class="${animClass}">${qty}</span></div>
                        </div>
                    </div>
                </div>
            `;
            selectHtml += `<option value="${item}">${info.name} (${qty})</option>`;
        }
    }

    // Update Previous State
    previousInventory = {...player.inventory};

    if (!hasItems) {
        invList.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text-muted)">Envanterin boş.</div>`;
    } else {
        invList.innerHTML = invHtml;
    }

    // Update select only if changed or empty
    if (sellSelect && sellSelect.innerHTML !== selectHtml) {
        const currentVal = sellSelect.value;
        sellSelect.innerHTML = selectHtml;
        if (currentVal && sellSelect.querySelector(`option[value="${currentVal}"]`)) {
            sellSelect.value = currentVal;
        }
    }
}

function renderFactories(player) {
    const factoryList = document.getElementById('factory-list');
    if (!factoryList) return;

    const factories = Object.entries(globalFactoryConfig);
    if (factories.length === 0) return;

    let html = factories.map(([fid, config]) => {
        const currentLevel = player.factories[fid] || 0;
        const unlockLvl = config.unlock_lvl || 1;
        const isLocked = player.level < unlockLvl;
        
        if (isLocked) {
            return `
            <div class="factory-card" style="opacity:0.5; cursor:not-allowed; border:1px dashed #555">
                <div class="factory-header">
                    <div style="font-weight:bold; color:var(--text-muted)">${config.name}</div>
                    <div style="font-size:0.8em; color:var(--danger)">🔒 Lv. ${unlockLvl}</div>
                </div>
            </div>`;
        }

        const storage = player.factory_storage[fid] || 0;
        const maxStorage = config.capacity * currentLevel;
        const isFull = storage >= maxStorage && currentLevel > 0;
        const percent = currentLevel > 0 ? (storage / maxStorage) * 100 : 0;
        
        return `
        <div class="factory-card ${isFull ? 'storage-full' : ''}" onclick="openFactoryModal('${fid}')">
            <div class="factory-header">
                <div style="font-weight:bold">${config.name}</div>
                <div class="factory-level">Lv. ${currentLevel}</div>
            </div>
            
            ${currentLevel > 0 ? `
                <div style="font-size:0.8em; margin-top:5px; display:flex; justify-content:space-between;">
                    <span>Depo: ${parseInt(storage)} / ${maxStorage}</span>
                    <span>${config.rate * currentLevel}/dk</span>
                </div>
                <div class="storage-bar-bg">
                    <div class="storage-bar-fill" style="width: ${percent}%; background-color: ${isFull ? 'var(--danger)' : 'var(--primary)'}"></div>
                </div>
                ${isFull ? `<button class="btn btn-sm btn-success" style="width:100%; margin-top:5px;" onclick="event.stopPropagation(); collectFactory('${fid}')">TOPLA</button>` : ''}
            ` : '<div style="font-size:0.8em; color:var(--text-muted); text-align:center; padding:10px;">İnşa etmek için tıkla</div>'}
        </div>
        `;
    }).join('');

    // Check if user has NO active factories
    const hasActiveFactories = factories.some(([fid]) => (player.factories[fid] || 0) > 0);
    if (!hasActiveFactories) {
        html = `<div style="text-align:center; padding:20px; color:var(--text-muted); border:1px dashed #555; border-radius:8px; margin-bottom:10px;">Henüz fabrikan yok. Pazardan veya mağazadan satın alabilirsin.</div>` + html;
    }

    factoryList.innerHTML = html;
}

function renderMarket(data) {
    const list = document.getElementById('market-list');
    const banner = document.getElementById('economy-status');
    if (!list) return;

    // Update Economy Banner
    if (banner && data.economy) {
        if (__eventTimer) { clearInterval(__eventTimer); __eventTimer = null; }
        const endTs = data.economy.end_time || 0;
        const baseText = `${data.economy.event_message} (x${data.economy.multiplier})`;
        if (endTs && endTs > (Date.now()/1000)) {
            const updateBanner = () => {
                const left = Math.max(0, Math.floor(endTs - (Date.now()/1000)));
                const m = Math.floor(left/60);
                const s = left%60;
                banner.textContent = `🔥 ${baseText} – ${m}:${s.toString().padStart(2,'0')} KALDI`;
            };
            updateBanner();
            __eventTimer = setInterval(updateBanner, 1000);
        } else {
            banner.textContent = baseText;
        }
        if (data.economy.trend === 'up') {
            banner.style.color = 'var(--success)';
            banner.innerHTML += ' 📈';
        } else if (data.economy.trend === 'down') {
            banner.style.color = 'var(--danger)';
            banner.innerHTML += ' 📉';
        } else {
            banner.style.color = 'var(--warning)';
        }
    }

    let listings = data.listings || [];
    
    // Sort logic
    if (currentSort === 'price') {
        listings.sort((a, b) => a.fiyat - b.fiyat);
    } else if (currentSort === 'item') {
        listings.sort((a, b) => a.item.localeCompare(b.item));
    } else {
         listings.sort((a, b) => b.time - a.time);
    }
    
    if (listings.length === 0) {
        list.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text-muted)">Pazarda şu an ürün yok.</div>`;
        return;
    }

    // Calculate Average Prices for "Profitable" check (Simple heuristic based on current listings)
    const typePrices = {};
    listings.forEach(l => {
        if (!typePrices[l.item]) typePrices[l.item] = {sum: 0, count: 0, min: Infinity};
        typePrices[l.item].sum += l.fiyat;
        typePrices[l.item].count++;
        if (l.fiyat < typePrices[l.item].min) typePrices[l.item].min = l.fiyat;
    });

    list.innerHTML = listings.map(item => {
        const itemInfo = globalItems[item.item] || {rarity: 1, name: item.item};
        
        // Highlight profitable items: if price is the minimum available for this type
        const isProfitable = item.fiyat === typePrices[item.item].min && typePrices[item.item].count > 1;
        
        // Trend Indicator
        const prevPrice = previousMarketPrices[item.id];
        let trendHtml = '';
        if (prevPrice) {
            if (item.fiyat > prevPrice) trendHtml = '<span style="color:var(--danger)">↑</span>';
            else if (item.fiyat < prevPrice) trendHtml = '<span style="color:var(--success)">↓</span>';
        }
        previousMarketPrices[item.id] = item.fiyat;

        return `
        <div class="market-item rarity-${itemInfo.rarity}" style="${isProfitable ? 'border-color:var(--success); box-shadow:0 0 5px rgba(46, 204, 113, 0.2);' : ''}">
            <div>
                <div style="font-weight:bold; font-size:1.1em" class="rarity-text-${itemInfo.rarity}">
                    ${itemInfo.name.toUpperCase()} ${trendHtml}
                    ${isProfitable ? '<span style="font-size:0.7em; background:var(--success); color:black; padding:2px 4px; border-radius:3px; margin-left:5px;">FIRSAT</span>' : ''}
                </div>
                <div style="font-size:0.8em; color:var(--text-muted)">Satıcı: ${item.satici}</div>
            </div>
            <div style="text-align:right">
                <div style="font-weight:bold; color:var(--success); font-size:1.2em">${formatMoney(item.fiyat)}</div>
                <div style="font-size:0.9em">Stok: ${item.adet}</div>
            </div>
            <div style="margin-left:15px;">
                <button class="btn btn-sm" onclick="buyItem('${item.id}', '${item.item}', ${item.fiyat}, ${item.adet})">SATIN AL</button>
            </div>
        </div>
    `}).join('');
}

// ---------------- HOME DASHBOARD WIDGETS ----------------
async function fetchPricesHome() {
    try {
        const res = await fetch('/api/market/prices');
        if (!res.ok) return;
        const rows = await res.json();
        const list = document.getElementById('home-price-list');
        if (!list) return;
        const priceHtml = rows.map(p => {
            const arrow = p.last_change > 0.001 ? '<span style="color:var(--danger)">↑</span>' : (p.last_change < -0.001 ? '<span style="color:var(--success)">↓</span>' : '<span style="color:var(--warning)">•</span>');
            return `
            <div class="inventory-item" style="display:flex; justify-content:space-between;">
                <div>${p.item}</div>
                <div style="font-weight:bold">${formatMoney(Math.round(p.price))} ${arrow}</div>
            </div>`;
        }).join('');
        list.innerHTML = priceHtml;
    } catch (e) {}
}

async function fetchNewsHome() {
    try {
        const res = await fetch('/api/news');
        if (!res.ok) return;
        const rows = await res.json();
        const box = document.getElementById('home-news-list');
        if (!box) return;
        box.innerHTML = rows.map(n => `
            <div class="inventory-item" style="display:flex; justify-content:space-between;">
                <div style="font-weight:bold">📰 ${n.title}</div>
                <div style="font-size:0.8em; color:var(--text-muted)">${new Date(n.created_at * 1000).toLocaleTimeString('tr-TR')}</div>
            </div>
        `).join('');
    } catch (e) {}
}

async function fetchLeaderboardHome() {
    try {
        const tbody = document.getElementById('home-leaderboard-body');
        if (!tbody) return;
        const res = await fetch('/api/leaderboard');
        const data = await res.json();
        tbody.innerHTML = data.slice(0, 10).map((u, index) => `
            <tr>
                <td>${index + 1}</td>
                <td>${u.username}</td>
                <td style="font-weight:bold">${formatMoney(u.net_worth)}</td>
            </tr>
        `).join('');
    } catch (e) {}
}
function renderMissions(player) {
    const missionBox = document.getElementById('mission-box');
    if (!missionBox) return;

    if (player.mission) {
        missionBox.style.display = 'block';
        const percent = Math.min(100, (player.mission.current_qty / player.mission.target_qty) * 100);
        
        missionBox.innerHTML = `
            <h4 style="margin:0 0 5px 0">🎯 GÖREV</h4>
            <div>${player.mission.description}</div>
            <div style="font-size:0.9em; color:var(--success)">Ödül: ${formatMoney(player.mission.reward)}</div>
            <div style="background:#333; height:5px; border-radius:3px; margin-top:5px;">
                <div style="background:var(--warning); height:100%; width:${percent}%"></div>
            </div>
        `;
    } else {
        missionBox.style.display = 'none';
    }
}

function renderNewMechanics(player) {
    // Update Expedition/Logistics UI
    const activeDiv = document.getElementById('expedition-active');
    const listDiv = document.getElementById('expedition-list');
    
    if (activeDiv && listDiv) {
        if (player.expedition_active) {
            activeDiv.style.display = 'block';
            listDiv.style.display = 'none';
        } else {
            activeDiv.style.display = 'none';
            listDiv.style.display = 'block';
        }
    }
}

// ---------------------------------------------------------
// NEW MECHANICS ACTIONS
// ---------------------------------------------------------

async function claimDailyBonus() {
    try {
        const res = await fetch('/api/daily_bonus', {method: 'POST'});
        const data = await res.json();
        alert(data.message);
        if (data.success) updateAll();
    } catch (e) {
        alert("Hata oluştu!");
    }
}

async function playVenture() {
    const amountInput = document.getElementById('venture-amount');
    const amount = parseInt(amountInput.value);
    
    if (!amount || amount <= 0) {
        alert("Geçerli bir miktar girin!");
        return;
    }
    
    if (confirm(`${amount} TL riske atarak şansınızı denemek istiyor musunuz? Kaybedebilirsiniz!`)) {
        try {
            const res = await fetch('/api/venture', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({amount})
            });
            const data = await res.json();
            alert(data.message);
            if (data.success) {
                amountInput.value = '';
                updateAll();
            }
        } catch (e) {
            alert("Hata oluştu!");
        }
    }
}

async function startExpedition(type) {
    if (!confirm("Seferi başlatmak istiyor musun?")) return;
    
    try {
        const res = await fetch('/api/expedition/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({type})
        });
        const data = await res.json();
        alert(data.message);
        if (data.success) updateAll();
    } catch (e) {
        alert("Hata oluştu!");
    }
}

async function collectExpedition() {
    try {
        const res = await fetch('/api/expedition/collect', {method: 'POST'});
        const data = await res.json();
        alert(data.message);
        if (data.success) updateAll();
    } catch (e) {
        alert("Hata oluştu!");
    }
}

// ---------------------------------------------------------
// EXISTING ACTIONS
// ---------------------------------------------------------

async function buyItem(orderId, item, price, qty) {
    const amount = prompt(`Kaç adet ${item} almak istiyorsun? (Max: ${qty})`, "1");
    if (!amount) return;
    
    try {
        const res = await fetch('/buy', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                order_id: orderId,
                adet: parseInt(amount)
            })
        });
        const data = await res.json();
        alert(data.message);
        if (data.success) updateAll();
    } catch (e) {
        alert("İşlem başarısız!");
    }
}

async function sellItem() {
    const item = document.getElementById('sell-item').value;
    const qty = document.getElementById('sell-qty').value;
    const price = document.getElementById('sell-price').value;
    
    if (!item || !qty || !price) {
        alert("Tüm alanları doldurun!");
        return;
    }
    
    try {
        const res = await fetch('/sell', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                item,
                adet: parseInt(qty),
                fiyat: parseInt(price)
            })
        });
        const data = await res.json();
        alert(data.message);
        if (data.success) {
            document.getElementById('sell-qty').value = '';
            document.getElementById('sell-price').value = '';
            updateAll();
        }
    } catch (e) {
        alert("İşlem başarısız!");
    }
}

function setSort(type) {
    currentSort = type;
    fetchMarket();
}

// ---------------------------------------------------------
// FACTORY MODAL
// ---------------------------------------------------------

function openFactoryModal(fid) {
    __factoryModalCurrentId = fid;
    const modal = document.getElementById('factory-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    
    const upgBtn = document.getElementById('modal-upgrade-btn');
    const collectBtn = document.getElementById('modal-collect-btn');
    const boostBtn = document.getElementById('modal-boost-btn');
    
    if (upgBtn) upgBtn.onclick = () => upgradeFactory(fid);
    if (collectBtn) collectBtn.onclick = () => collectFactory(fid);
    if (boostBtn) boostBtn.onclick = () => boostFactory(fid);
    
    updateFactoryModal(fid);
    if (__factoryModalTimer) clearInterval(__factoryModalTimer);
    __factoryModalTimer = setInterval(() => updateFactoryModal(fid), 1000);
}

async function updateFactoryModal(fid) {
    try {
        const res = await fetch(`/api/factory_status/${fid}`);
        if (!res.ok) return;
        const data = await res.json();
        const config = globalFactoryConfig[fid];
        if (!config) return;
        
        const titleEl = document.getElementById('modal-title');
        if (titleEl) {
            titleEl.innerHTML = `${config.name} <span id="modal-level-badge" style="font-size:0.6em; color:var(--primary)">Lv. ${data.level}</span>`;
        }
        
        const rateEl = document.getElementById('modal-rate');
        const storageEl = document.getElementById('modal-storage');
        const capacityEl = document.getElementById('modal-capacity');
        const statusEl = document.getElementById('modal-status-text');
        
        if (rateEl) rateEl.textContent = `${parseInt(data.rate)}/dk`;
        if (storageEl) storageEl.textContent = parseInt(data.storage);
        if (capacityEl) capacityEl.textContent = parseInt(data.capacity);
        if (statusEl) statusEl.textContent = data.is_boosted ? 'Durum: ⚡ Hızlı' : 'Durum: Normal';
        
        const percent = Math.min(100, data.capacity > 0 ? (data.storage / data.capacity) * 100 : 0);
        const progEl = document.getElementById('modal-progress');
        if (progEl) progEl.style.width = `${percent}%`;
        
        const costText = document.getElementById('modal-cost-text');
        const upgStats = document.getElementById('modal-next-stats');
        
        if (costText) {
            const matPart = data.next_mat ? ` + ${data.next_mat_cost} ${data.next_mat}` : '';
            costText.textContent = `${formatMoney(data.next_cost)}${matPart}`;
        }
        if (upgStats) {
            const nextLevel = (data.level || 0) + 1;
            upgStats.textContent = `Yeni Kapasite: ${config.capacity * nextLevel} | Yeni Hız: ${config.rate * nextLevel}`;
        }
    } catch (e) {
        // ignore
    }
}

async function upgradeFactory(fid) {
    try {
        const res = await fetch(`/api/upgrade_factory/${fid}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        const data = await res.json();
        showMessage(data.message || (data.success ? 'Fabrika başarıyla yükseltildi!' : 'Başarısız'));
        if (data.success) {
            // Update only the related factory card fields (level, production, cost)
            const levelEl = document.querySelector(`#level-${fid}`);
            const rateEl = document.querySelector(`#rate-${fid}`);
            const costEl = document.querySelector(`#cost-${fid}`);
            if (levelEl) levelEl.textContent = data.new_level;
            if (rateEl) rateEl.textContent = data.new_production;
            if (costEl) costEl.textContent = formatMoney(data.next_cost);
            // Optionally refresh factory status for accurate next_cost
            try {
                const st = await fetch(`/api/factory_status/${fid}`);
                if (st.ok) {
                    const sdata = await st.json();
                    if (costEl) costEl.textContent = formatMoney(sdata.next_cost);
                }
            } catch (_) {}
        }
    } catch (e) {
        showMessage("Hata!", 'error');
    }
}

async function collectFactory(fid) {
    try {
        const res = await fetch('/api/factory/collect', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({factory_id: fid})
        });
        const data = await res.json();
        alert(data.message);
        if (data.success) {
            updateAll();
            updateFactoryModal(fid);
        }
    } catch (e) {
        alert("Hata!");
    }
}

async function boostFactory(fid) {
    try {
        const res = await fetch('/api/factory/boost', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({factory_id: fid})
        });
        const data = await res.json();
        alert(data.message);
        if(data.success) {
            updateFactoryModal(fid);
        }
    } catch (e) {
        alert("Hata!");
    }
}

function closeModal() {
    const modal = document.getElementById('factory-modal');
    if (modal) modal.style.display = 'none';
    if (__factoryModalTimer) {
        clearInterval(__factoryModalTimer);
        __factoryModalTimer = null;
        __factoryModalCurrentId = null;
    }
}

// ---------------------------------------------------------
// CHAT & LEADERBOARD
// ---------------------------------------------------------

function toggleChat() {
    const body = document.getElementById('chat-body');
    if (body.style.display === 'flex') {
        body.style.display = 'none';
    } else {
        body.style.display = 'flex';
        fetchChat();
    }
}

async function fetchChat() {
    const body = document.getElementById('chat-body');
    if (body && body.style.display === 'none') return;
    
    try {
        const res = await fetch('/api/chat');
        if (!res.ok) return;
        const messages = await res.json();
        
        const chatDiv = document.getElementById('chat-messages');
        if (!chatDiv) return;
        
        const wasScrolledToBottom = chatDiv.scrollHeight - chatDiv.scrollTop === chatDiv.clientHeight;
        
        chatDiv.innerHTML = messages.map(msg => `
            <div class="chat-msg ${msg.is_admin ? 'admin' : ''} ${msg.is_system ? 'system' : ''}">
                <span class="time">[${msg.time}]</span>
                <span class="user">${msg.username}:</span>
                <span class="text">${msg.message}</span>
            </div>
        `).join('');
        
        if (wasScrolledToBottom) {
            chatDiv.scrollTop = chatDiv.scrollHeight;
        }
    } catch (e) {}
}

async function sendChat() {
    const input = document.getElementById('chat-input');
    const msg = input.value.trim();
    if (!msg) return;
    
    const res = await fetch('/api/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: msg})
    });
    
    if (res.status === 403) {
        showMessage("Mesajınız uygunsuz içerik nedeniyle engellendi veya geçici olarak susturuldunuz.", 'error');
        return;
    }
    try {
        const data = await res.json();
        if (data.moderated) {
            showMessage("Mesajınız uygunsuz içerik nedeniyle düzenlendi.", 'error');
        }
    } catch (e) {}
    input.value = '';
    fetchChat();
}

function handleChatKey(event) {
    if (event.key === 'Enter') {
        sendChat();
    }
}

async function fetchLeaderboard() {
    const tbody = document.getElementById('leaderboard-body');
    if (!tbody) return;

    try {
        const res = await fetch('/api/leaderboard');
        const data = await res.json();
        
        tbody.innerHTML = data.map((u, index) => `
            <tr>
                <td>${index + 1}</td>
                <td>${u.username}</td>
                <td style="color:var(--success)">${formatMoney(u.money)}</td>
                <td style="font-weight:bold">${formatMoney(u.net_worth)}</td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="4">Veri yüklenemedi.</td></tr>';
    }
}

// Utility for icons
function getResourceIcon(name) {
    const icons = {
        'Odun': '🪵',
        'Taş': '🪨',
        'Demir': '⛏️',
        'Altın': '⚱️',
        'Elmas': '💎',
        'Gıda': '🍎',
        'Petrol': '🛢️',
        'Çelik': '🏗️'
    };
    return icons[name] || '📦';
}
