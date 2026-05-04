#!/usr/bin/env python3
import requests
import time
import json
import os
import logging

# ================= CONFIG =================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
APIFY_API_KEY      = os.environ.get("APIFY_API_KEY", "")

INTERVALLO = 300  # 5 minuti

SEARCHES = [
    {
        "nome": "Nintendo 3DS XL",
        "url": "https://www.subito.it/annunci/italia/vendita/?q=nintendo+3ds+xl&ps=5&pe=130",
        "prezzo_max": 130,
        "prezzo_revend": 200,
    },
    {
        "nome": "Nintendo 3DS",
        "url": "https://www.subito.it/annunci/italia/vendita/?q=nintendo+3ds&ps=5&pe=70",
        "prezzo_max": 70,
        "prezzo_revend": 150,
    },
]

APIFY_ACTOR = "santamaria-automations~subito-it-scraper"

# ================= LOGGING =================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ================= VALIDAZIONE =================

def validate():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not APIFY_API_KEY:
        raise Exception("❌ Variabili ambiente mancanti")

# ================= APIFY =================

def fetch(search):
    log.info(f"🔎 Avvio Apify: {search['nome']}")

    url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync"
    params = {"token": APIFY_API_KEY}

    payload = {
        "startUrls": [{"url": search["url"]}],
        "maxItems": 30
    }

    try:
        r = requests.post(url, params=params, json=payload, timeout=120)
        r.raise_for_status()
        items = r.json()
    except Exception as e:
        log.error(f"❌ Apify error: {e}")
        return []

    if not isinstance(items, list):
        log.error(f"❌ Risposta Apify non valida: {items}")
        return []

    log.info(f"📦 Trovati {len(items)} items")
    return items

# ================= TELEGRAM =================

def send(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text
            },
            timeout=10
        )
    except Exception as e:
        log.error(f"❌ Telegram error: {e}")

# ================= LOGICA =================

seen = set()

def check():
    global seen

    for s in SEARCHES:
        items = fetch(s)

        for i in items:
            title = i.get("title") or "No title"
            url = i.get("url") or ""
            price = i.get("price")

            key = url or title
            if key in seen:
                continue

            seen.add(key)

            msg = f"""🔥 NUOVO AFFARE
{s['nome']}

📦 {title}
💶 {price}
🔗 {url}
"""

            log.info(f"📢 NUOVO: {title}")
            send(msg)

# ================= MAIN =================

if __name__ == "__main__":
    try:
        print(">>> BOT STARTED")

        validate()

        log.info("🤖 Bot avviato")

        while True:
            try:
                check()
            except Exception as e:
                log.error(f"⚠️ Errore check: {e}")

            time.sleep(INTERVALLO)

    except Exception as e:
        log.error(f"💥 CRASH FATALE: {e}")
