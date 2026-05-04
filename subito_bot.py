import os
import time
import random
import logging
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import requests

# ================= CONFIG =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

INTERVALLO_MIN = 4
INTERVALLO_MAX = 7

SEARCHES = [
    {"nome": "Nintendo 3DS XL", "query": "nintendo 3ds xl", "prezzo_min": 5, "prezzo_max": 130},
    {"nome": "Nintendo 3DS", "query": "nintendo 3ds", "prezzo_min": 5, "prezzo_max": 70},
]

# ================= LOG =================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

seen_ids = set()

# ================= UTILS =================
def build_url(search):
    q = search["query"].replace(" ", "%20")
    return f"https://www.subito.it/annunci/italia/?q={q}&ps={search['prezzo_min']}&pe={search['prezzo_max']}"

def parse_price(text):
    try:
        return int("".join(filter(str.isdigit, text)))
    except:
        return 0

def send_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}
        )
    except Exception as e:
        log.error(f"Errore Telegram: {e}")

# ================= SCRAPER =================
def scrape(search, page):
    url = build_url(search)
    log.info(f"[{search['nome']}] Scraping: {url}")

    try:
        page.goto(url, timeout=30000)
        page.wait_for_timeout(random.randint(2000, 4000))
        html = page.content()
    except Exception as e:
        log.error(f"Errore scraping: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("article")

    results = []

    for card in cards:
        try:
            link_tag = card.select_one("a[href]")
            if not link_tag:
                continue

            link = link_tag["href"]
            if not link.startswith("http"):
                link = "https://www.subito.it" + link

            ad_id = link.split("-")[-1].rstrip("/")

            title_tag = card.select_one("h2,h3")
            title = title_tag.get_text(strip=True) if title_tag else "Senza titolo"

            price_tag = card.select_one("[class*='price']")
            price_text = price_tag.get_text(strip=True) if price_tag else ""
            price = parse_price(price_text)

            results.append({
                "id": ad_id,
                "title": title,
                "price": price,
                "price_text": price_text,
                "link": link
            })

        except:
            continue

    log.info(f"[{search['nome']}] {len(results)} annunci trovati")
    return results

# ================= MAIN LOOP =================
def run():
    log.info("🚀 Bot avviato")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        while True:
            total_new = 0

            for search in SEARCHES:
                ads = scrape(search, page)

                for ad in ads:
                    if ad["id"] not in seen_ids:
                        seen_ids.add(ad["id"])

                        msg = f"🔥 {search['nome']}\n{ad['title']}\n💰 {ad['price_text']}\n{ad['link']}"
                        send_telegram(msg)

                        total_new += 1

            log.info(f"✔ Check completato — {total_new} nuovi annunci")

            sleep_time = random.randint(INTERVALLO_MIN * 60, INTERVALLO_MAX * 60)
            log.info(f"⏳ Attendo {sleep_time} secondi")
            time.sleep(sleep_time)

# ================= START =================
if __name__ == "__main__":
    run()
