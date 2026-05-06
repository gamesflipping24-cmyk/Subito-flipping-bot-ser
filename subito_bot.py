#!/usr/bin/env python3
"""
Bot Telegram — Monitor Subito.it + eBay (Railway stable version)
"""

import os
import time
import json
import random
import logging
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ============================================================
# CONFIG TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ============================================================
# SEARCH CONFIG
# ============================================================

SEARCHES = [
    {
        "nome": "Nintendo 3DS XL",
        "query": "nintendo 3ds xl",
    },
    {
        "nome": "Nintendo 3DS",
        "query": "nintendo 3ds",
    },
]

INTERVALLO = 120  # secondi
SEEN_FILE = "/tmp/seen.json"

# ============================================================
# PROXY
# ============================================================

PROXY_LIST = [
    "46.203.30.114:6115:wkkpqehe:guk722z85qd4",
    "62.164.246.128:7853:wkkpqehe:guk722z85qd4",
    "103.210.12.201:6129:wkkpqehe:guk722z85qd4",
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ============================================================
# STORAGE
# ============================================================

def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(title, link, source):
    text = f"""🔥 NUOVO AFFARE
📦 {source}

🛒 {title}

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
# SCRAPERS
# ============================================================

def fetch_subito(search):
    q = search["query"].replace(" ", "%20")
    url = f"https://www.subito.it/annunci-italia/vendita/usato/?q={q}"

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            proxy=get_proxy()
        )
        page = browser.new_page()

        page.goto(url, timeout=60000)
        page.wait_for_timeout(4000)

        soup = BeautifulSoup(page.content(), "html.parser")
        cards = soup.select("article")

        for c in cards:
            title = c.get_text(" ", strip=True)
            if title:
                results.append({
                    "id": "subito_" + str(hash(title)),
                    "title": title[:120],
                    "link": url,
                    "source": "SUBITO"
                })

        browser.close()

    return results


def fetch_ebay(search):
    q = search["query"].replace(" ", "+")
    url = f"https://www.ebay.it/sch/i.html?_nkw={q}"

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            proxy=get_proxy()
        )
        page = browser.new_page()

        page.goto(url, timeout=60000)
        page.wait_for_timeout(4000)

        soup = BeautifulSoup(page.content(), "html.parser")
        items = soup.select("li.s-item")

        for i in items:
            title = i.get_text(" ", strip=True)
            if title:
                results.append({
                    "id": "ebay_" + str(hash(title)),
                    "title": title[:120],
                    "link": url,
                    "source": "EBAY"
                })

        browser.close()

    return results

# ============================================================
# CHECK
# ============================================================

def check_all():
    log.info("CHECK_ALL START")

    seen = load_seen()

    for search in SEARCHES:
        log.info(f"Fetching: {search['nome']}")

        results = fetch_subito(search) + fetch_ebay(search)

        for r in results:
            if r["id"] in seen:
                continue

            log.info(f"NUOVO: {r['title']}")

            send_telegram(r["title"], r["link"], r["source"])

            seen.add(r["id"])

    save_seen(seen)

# ============================================================
# MAIN LOOP STABILE
# ============================================================

def main():
    log.info("BOT STARTED")

    while True:
        try:
            check_all()
        except Exception as e:
            log.error(f"ERROR LOOP: {e}")

        time.sleep(INTERVALLO)

# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
