#!/usr/bin/env python3
"""
Bot Telegram — Monitor Subito.it + eBay (Playwright + Residential Proxy)
"""

import os
import time
import json
import random
import logging
import schedule
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import requests

# ============================================================
# CONFIG TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ============================================================
# SEARCH CONFIG
# ============================================================

SEARCHES = [
    {"nome": "Nintendo 3DS XL", "query": "nintendo 3ds xl", "prezzo_min": 5, "prezzo_max": 130, "prezzo_revend": 200},
    {"nome": "Nintendo 3DS", "query": "nintendo 3ds", "prezzo_min": 5, "prezzo_max": 70, "prezzo_revend": 150},
]

INTERVALLO_MINUTI = 2
SEEN_FILE = "/tmp/seen.json"

# ============================================================
# PROXY
# ============================================================

PROXY_LIST = [
"46.203.30.114:6115:wkkpqehe:guk722z85qd4",
"62.164.246.128:7853:wkkpqehe:guk722z85qd4",
"103.210.12.201:6129:wkkpqehe:guk722z85qd4",
"103.210.12.172:6100:wkkpqehe:guk722z85qd4",
"9.142.37.200:5371:wkkpqehe:guk722z85qd4",
]

def get_proxy():
    ip, port, user, pwd = random.choice(PROXY_LIST).split(":")
    return {
        "server": f"http://{ip}:{port}",
        "username": user,
        "password": pwd
    }

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ============================================================
# STORAGE
# ============================================================

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(title, price, link, source, search_name):
    text = f"""
🔥 NUOVO AFFARE
📦 {search_name} — {source}

🛒 {title}
💶 Prezzo: {price if price else 'N/A'}

👉 {link}
"""

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text}
        )
    except Exception as e:
        log.error(f"Telegram error: {e}")

# ============================================================
# SUBITO
# ============================================================

def fetch_subito(search):
    q = search["query"].replace(" ", "%20")
    url = f"https://www.subito.it/annunci-italia/vendita/usato/?q={q}"

    annunci = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, proxy=get_proxy())
        page = browser.new_page()

        page.goto(url, timeout=60000)
        page.wait_for_timeout(5000)

        soup = BeautifulSoup(page.content(), "html.parser")
        cards = soup.select("article")

        for c in cards:
            text = c.get_text(" ", strip=True)
            if text:
                annunci.append({
                    "id": "subito_" + str(hash(text)),
                    "title": text[:120],
                    "price": None,
                    "link": url,
                    "source": "SUBITO"
                })

        browser.close()

    return annunci

# ============================================================
# EBAY
# ============================================================

def fetch_ebay(search):
    q = search["query"].replace(" ", "+")
    url = f"https://www.ebay.it/sch/i.html?_nkw={q}"

    annunci = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, proxy=get_proxy())
        page = browser.new_page()

        page.goto(url, timeout=60000)
        page.wait_for_timeout(5000)

        soup = BeautifulSoup(page.content(), "html.parser")
        items = soup.select("li.s-item")

        for i in items:
            title = i.get_text(" ", strip=True)
            if title:
                annunci.append({
                    "id": "ebay_" + str(hash(title)),
                    "title": title[:120],
                    "price": None,
                    "link": url,
                    "source": "EBAY"
                })

        browser.close()

    return annunci

# ============================================================
# LOOP
# ============================================================

def check_all():
    seen = load_seen()

    for search in SEARCHES:
        results = fetch_subito(search) + fetch_ebay(search)

        for r in results:
            if r["id"] in seen:
                continue

            log.info(f"NUOVO: {r['title']} ({r['source']})")

            send_telegram(
                r["title"],
                r["price"],
                r["link"],
                r["source"],
                search["nome"]
            )

            seen.add(r["id"])
            time.sleep(1)

    save_seen(seen)

# ============================================================
# START
# ============================================================

def main():
    log.info("Bot avviato")

    check_all()
    schedule.every(INTERVALLO_MINUTI).minutes.do(check_all)

    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    main()
