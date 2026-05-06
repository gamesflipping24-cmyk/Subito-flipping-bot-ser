#!/usr/bin/env python3
"""
Bot Telegram — Monitor Subito.it + eBay (Railway SAFE VERSION)
"""

import os
import time
import json
import random
import logging
import schedule
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

SEARCHES = [
    {"nome": "Nintendo 3DS XL", "query": "nintendo 3ds xl"},
    {"nome": "Nintendo 3DS", "query": "nintendo 3ds"},
]

INTERVALLO_MINUTI = 2
SEEN_FILE = "/tmp/seen.json"

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ============================================================
# STORAGE
# ============================================================

def load_seen():
    try:
        if os.path.exists(SEEN_FILE):
            with open(SEEN_FILE, "r") as f:
                return set(json.load(f))
    except:
        pass
    return set()

def save_seen(seen):
    try:
        with open(SEEN_FILE, "w") as f:
            json.dump(list(seen), f)
    except:
        pass

# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(title, link, source, search_name):
    text = f"""
🔥 NUOVO AFFARE
📦 {search_name} — {source}

🛒 {title}

👉 {link}
"""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=10
        )
    except Exception as e:
        log.error(f"Telegram error: {e}")

# ============================================================
# FETCH (SAFE MODE — NO CRASH)
# ============================================================

def fetch(search):
    results = []

    try:
        q = search["query"].replace(" ", "%20")
        url = f"https://www.subito.it/annunci-italia/vendita/usato/?q={q}"

        log.info(f"Fetching: {search['nome']}")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto(url, timeout=60000)
            page.wait_for_timeout(3000)

            soup = BeautifulSoup(page.content(), "html.parser")
            cards = soup.select("article")

            for c in cards:
                text = c.get_text(" ", strip=True)
                if text:
                    results.append({
                        "id": "subito_" + str(hash(text)),
                        "title": text[:120],
                        "link": url,
                        "source": "SUBITO"
                    })

            browser.close()

    except Exception as e:
        log.error(f"FETCH ERROR: {e}")

    return results

# ============================================================
# LOOP LOGIC SAFE
# ============================================================

def check_all():
    log.info("CHECK_ALL START")

    seen = load_seen()

    for search in SEARCHES:
        try:
            results = fetch(search)

            for r in results:
                if r["id"] in seen:
                    continue

                log.info(f"NUOVO: {r['title']}")

                send_telegram(
                    r["title"],
                    r["link"],
                    r["source"],
                    search["nome"]
                )

                seen.add(r["id"])

        except Exception as e:
            log.error(f"SEARCH ERROR: {e}")

    save_seen(seen)

# ============================================================
# START (CRASH-PROOF)
# ============================================================

def main():
    log.info("BOT STARTED")

    while True:
        try:
            check_all()
        except Exception as e:
            log.error(f"MAIN LOOP ERROR: {e}")

        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    main()
