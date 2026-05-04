# #!/usr/bin/env python3
“””
Bot Telegram — Monitor Subito.it per Flipping

Monitora subito.it ogni 2 minuti e invia notifiche Telegram
con margine di guadagno stimato per ogni annuncio trovato.
“””

import requests
import schedule
import time
import json
import os
import logging
import random
from bs4 import BeautifulSoup

# ============================================================

# ⚙️  CONFIG

# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get(“TELEGRAM_BOT_TOKEN”, “”)
TELEGRAM_CHAT_ID   = os.environ.get(“TELEGRAM_CHAT_ID”, “”)

SEARCHES = [
{
“nome”:          “Nintendo 3DS XL”,
“query”:         “nintendo 3ds xl”,
“prezzo_min”:    5,
“prezzo_max”:    130,
“prezzo_revend”: 200,
“regione”:       None,
“categoria”:     None,
},
{
“nome”:          “Nintendo 3DS”,
“query”:         “nintendo 3ds”,
“prezzo_min”:    5,
“prezzo_max”:    70,
“prezzo_revend”: 150,
“regione”:       None,
“categoria”:     None,
},
]

INTERVALLO_MINUTI = 2
SEEN_FILE = “/tmp/seen_ids.json”

# ============================================================

# Logging

# ============================================================

logging.basicConfig(
level=logging.INFO,
format=”%(asctime)s [%(levelname)s] %(message)s”,
handlers=[logging.StreamHandler()]
)
log = logging.getLogger(**name**)

# ============================================================

# Persistenza

# ============================================================

def load_seen() -> set:
try:
if os.path.exists(SEEN_FILE):
with open(SEEN_FILE, “r”) as f:
return set(json.load(f))
except Exception:
pass
return set()

def save_seen(seen: set):
try:
with open(SEEN_FILE, “w”) as f:
json.dump(list(seen), f)
except Exception as e:
log.error(f”Errore salvataggio seen: {e}”)

# ============================================================

# Sessione HTTP con headers realistici

# ============================================================

USER_AGENTS = [
“Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36”,
“Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36”,
“Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0”,
“Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15”,
]

def make_session() -> requests.Session:
session = requests.Session()
ua = random.choice(USER_AGENTS)
session.headers.update({
“User-Agent”: ua,
“Accept”: “text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8”,
“Accept-Language”: “it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7”,
“Accept-Encoding”: “gzip, deflate, br”,
“Connection”: “keep-alive”,
“Upgrade-Insecure-Requests”: “1”,
“Sec-Fetch-Dest”: “document”,
“Sec-Fetch-Mode”: “navigate”,
“Sec-Fetch-Site”: “none”,
“Sec-Fetch-User”: “?1”,
“Cache-Control”: “max-age=0”,
})
try:
session.get(“https://www.subito.it”, timeout=10)
time.sleep(random.uniform(1.5, 3.0))
except Exception:
pass
return session

# ============================================================

# URL Builder

# ============================================================

def build_url(search: dict) -> str:
path_parts = [“annunci”]
path_parts.append(search[“regione”] if search.get(“regione”) else “italia”)
if search.get(“categoria”):
path_parts.append(search[“categoria”])
path = “/”.join(path_parts) + “/”

```
params = {"q": search["query"]}
if search.get("prezzo_min") is not None:
    params["ps"] = search["prezzo_min"]
if search.get("prezzo_max") is not None:
    params["pe"] = search["prezzo_max"]

query_string = "&".join(f"{k}={v}" for k, v in params.items())
return f"https://www.subito.it/{path}?{query_string}"
```

# ============================================================

# Scraping

# ============================================================

def scrape_annunci(session: requests.Session, search: dict) -> list:
url = build_url(search)
log.info(f”[{search[‘nome’]}] Scraping: {url}”)

```
try:
    resp = session.get(url, timeout=15)
    resp.raise_for_status()
except requests.RequestException as e:
    log.error(f"[{search['nome']}] Errore HTTP: {e}")
    return []

soup = BeautifulSoup(resp.text, "html.parser")
annunci = []

cards = soup.select("article[class*='item-card']")
if not cards:
    cards = soup.select("div[class*='item-list'] article")

for card in cards:
    try:
        ad_id = card.get("data-item-id") or card.get("id") or ""
        if not ad_id:
            link_tag = card.select_one("a[href*='/annunci/']")
            if link_tag:
                ad_id = link_tag["href"].split("-")[-1].rstrip("/")
        if not ad_id:
            continue

        title_tag = card.select_one("h2,h3,[class*='title']")
        title = title_tag.get_text(strip=True) if title_tag else "Senza titolo"

        price_tag = card.select_one("[class*='price']")
        price_text = price_tag.get_text(strip=True) if price_tag else ""
        price = parse_price(price_text)

        link_tag = card.select_one("a[href]")
        link = link_tag["href"] if link_tag else ""
        if link and not link.startswith("http"):
            link = "https://www.subito.it" + link

        location_tag = card.select_one("[class*='town'],[class*='location'],[class*='city']")
        location = location_tag.get_text(strip=True) if location_tag else ""

        date_tag = card.select_one("[class*='date'],[class*='time']")
        date_str = date_tag.get_text(strip=True) if date_tag else ""

        annunci.append({
            "id":         ad_id,
            "title":      title,
            "price":      price,
            "price_text": price_text,
            "link":       link,
            "location":   location,
            "date":       date_str,
        })
    except Exception as e:
        log.warning(f"Errore parsing card: {e}")

log.info(f"[{search['nome']}] Trovati {len(annunci)} annunci")
return annunci
```

def parse_price(text: str):
try:
cleaned = text.replace(”.”, “”).replace(”,”, “.”).replace(“€”, “”).strip()
num = “”.join(c for c in cleaned if c.isdigit() or c == “.”)
return float(num) if num else None
except Exception:
return None

# ============================================================

# Filtro

# ============================================================

def passes_filter(annuncio: dict, search: dict) -> bool:
price = annuncio[“price”]
if price is None:
return True
if search.get(“prezzo_max”) is not None and price > search[“prezzo_max”]:
return False
if search.get(“prezzo_min”) is not None and price < search[“prezzo_min”]:
return False
return True

# ============================================================

# Margine

# ============================================================

def calcola_margine(price, prezzo_revend):
if price is None or prezzo_revend is None:
return None
return prezzo_revend - price

def valuta_affare(margine, prezzo_revend):
if margine is None or prezzo_revend is None:
return “❓”
percentuale = (margine / prezzo_revend) * 100
if percentuale >= 60:
return “🔥 OTTIMO AFFARE”
elif percentuale >= 40:
return “✅ BUON AFFARE”
elif percentuale >= 20:
return “👍 DISCRETO”
else:
return “⚠️ MARGINE BASSO”

# ============================================================

# Telegram

# ============================================================

def escape_md(text: str) -> str:
special = r”_*[]()~`>#+-=|{}.!”
return “”.join(f”\{c}” if c in special else c for c in str(text))

def send_telegram(annuncio: dict, search: dict):
price       = annuncio[“price”]
prezzo_txt  = annuncio[“price_text”] or “Prezzo non indicato”
luogo       = annuncio[“location”] or “—”
data        = annuncio[“date”] or “—”
margine     = calcola_margine(price, search.get(“prezzo_revend”))
valutazione = valuta_affare(margine, search.get(“prezzo_revend”))

```
if margine is not None:
    margine_txt = f"💰 Margine stimato: ~{int(margine)}€ \\(rivendi a ~{search['prezzo_revend']}€\\)"
else:
    margine_txt = "💰 Margine: non calcolabile"

text = (
    f"{valutazione}\n"
    f"🔔 *{escape_md(search['nome'])}* — SUBITO\\.IT\n\n"
    f"📦 *{escape_md(annuncio['title'])}*\n"
    f"💶 Prezzo: {escape_md(prezzo_txt)}\n"
    f"{margine_txt}\n"
    f"📍 {escape_md(luogo)}\n"
    f"🕐 {escape_md(data)}\n\n"
    f"[👉 Vedi annuncio]({annuncio['link']})"
)

try:
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "MarkdownV2"},
        timeout=10
    )
    resp.raise_for_status()
    log.info(f"✅ Notifica inviata: {annuncio['title']} — margine ~{margine}€")
except Exception as e:
    log.error(f"❌ Errore Telegram: {e}")
```

def send_startup_message():
lines = “\n”.join(
f”• {s[‘nome’]} \(max {s[‘prezzo_max’]}€ → rivendi ~{s[‘prezzo_revend’]}€\)”
for s in SEARCHES
)
text = (
f”🤖 *Bot Subito\.it aggiornato e riavviato\!*\n\n”
f”🎮 Monitorando ogni *{INTERVALLO_MINUTI} minuti*:\n”
f”{lines}\n\n”
f”Ti avviserò non appena trovo un affare\! 🔥”
)
try:
requests.post(
f”https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage”,
json={“chat_id”: TELEGRAM_CHAT_ID, “text”: text, “parse_mode”: “MarkdownV2”},
timeout=10
)
except Exception as e:
log.error(f”Errore messaggio avvio: {e}”)

# ============================================================

# Loop principale

# ============================================================

def check_all():
seen = load_seen()
new_count = 0
session = make_session()

```
for search in SEARCHES:
    annunci = scrape_annunci(session, search)
    for ann in annunci:
        ad_id = f"{search['nome']}_{ann['id']}"
        if ad_id in seen:
            continue
        if not passes_filter(ann, search):
            seen.add(ad_id)
            continue
        log.info(f"  ✨ NUOVO: {ann['title']} — {ann['price_text']}")
        send_telegram(ann, search)
        seen.add(ad_id)
        new_count += 1
        time.sleep(1)
    time.sleep(random.uniform(2.0, 4.0))

save_seen(seen)
log.info(f"✔ Check completato — {new_count} nuovi annunci notificati")
```

def validate_config():
if not TELEGRAM_BOT_TOKEN:
log.error(“❌ TELEGRAM_BOT_TOKEN non impostato!”)
exit(1)
if not TELEGRAM_CHAT_ID:
log.error(“❌ TELEGRAM_CHAT_ID non impostato!”)
exit(1)

if **name** == “**main**”:
log.info(”=” * 50)
log.info(“🎮 Bot Subito.it Flipping avviato”)
validate_config()
log.info(f”Ricerche: {[s[‘nome’] for s in SEARCHES]}”)
log.info(f”Intervallo: ogni {INTERVALLO_MINUTI} minuti”)
log.info(”=” * 50)

```
send_startup_message()
check_all()

schedule.every(INTERVALLO_MINUTI).minutes.do(check_all)
while True:
    schedule.run_pending()
    time.sleep(30)
```
