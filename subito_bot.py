#!/usr/bin/env python3
"""
Bot Telegram — Monitor Subito.it + eBay per Flipping
=====================================================
Usa Webshare Static Residential proxy per bypassare i blocchi.
Monitora ogni 2 minuti su Subito.it ed eBay Italia.
"""

import requests
import schedule
import time
import json
import os
import logging
import warnings
from bs4 import BeautifulSoup
from urllib.parse import quote

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# ============================================================
#  CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# Webshare Static Residential Proxy
PROXY_HOST = os.environ.get("PROXY_HOST", "")
PROXY_PORT = os.environ.get("PROXY_PORT", "")
PROXY_USER = os.environ.get("PROXY_USER", "")
PROXY_PASS = os.environ.get("PROXY_PASS", "")

SEARCHES = [
    {
        "nome":          "Nintendo 3DS XL",
        "query":         "nintendo 3ds xl",
        "prezzo_min":    5,
        "prezzo_max":    130,
        "prezzo_revend": 200,
    },
    {
        "nome":          "Nintendo 3DS",
        "query":         "nintendo 3ds",
        "prezzo_min":    5,
        "prezzo_max":    70,
        "prezzo_revend": 150,
    },
]

TITOLI_ESCLUSI_ESATTI = [
    "solo scatola", "only box", "box only", "solo box",
    "solo manuale", "solo custodia", "solo cover",
    "solo caricatore", "solo alimentatore", "scatola vuota", "empty box",
]

CONDIZIONI_ESCLUSE = [
    "for parts", "not working", "per ricambi",
    "non funzionante", "parts only", "da riparare", "broken",
]

INTERVALLO_MINUTI = 2
SEEN_FILE = "/tmp/seen_ids.json"

# ============================================================
#  Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ============================================================
#  Persistenza
# ============================================================

def load_seen() -> set:
    try:
        if os.path.exists(SEEN_FILE):
            with open(SEEN_FILE, "r") as f:
                return set(json.load(f))
    except Exception:
        pass
    return set()

def save_seen(seen: set):
    try:
        with open(SEEN_FILE, "w") as f:
            json.dump(list(seen), f)
    except Exception as e:
        log.error(f"Errore salvataggio seen: {e}")

# ============================================================
#  Proxy
# ============================================================

def get_proxies():
    proxy_url = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"
    return {"http": proxy_url, "https": proxy_url}

# ============================================================
#  Filtro titoli
# ============================================================

def titolo_escluso(title: str) -> bool:
    title_lower = title.lower()
    for frase in TITOLI_ESCLUSI_ESATTI:
        if frase in title_lower:
            return True
    for cond in CONDIZIONI_ESCLUSE:
        if cond in title_lower:
            return True
    return False

# ============================================================
#  Subito.it
# ============================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def fetch_subito(search: dict) -> list:
    q = quote(search["query"])
    url = f"https://www.subito.it/annunci/italia/vendita/?q={q}&ps={search['prezzo_min']}&pe={search['prezzo_max']}"
    log.info(f"[{search['nome']}] Subito scraping...")

    try:
        resp = requests.get(url, headers=HEADERS, proxies=get_proxies(), timeout=30, verify=False)
        resp.raise_for_status()
    except Exception as e:
        log.error(f"[{search['nome']}] Errore Subito: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    annunci = []

    cards = soup.select("article[class*='item-card']")
    if not cards:
        cards = soup.select("div[class*='item-list'] article")

    log.info(f"[{search['nome']}] Subito: {len(cards)} card trovate")

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

            if titolo_escluso(title):
                log.info(f"  ↳ [Subito] Escluso: {title}")
                continue

            price_tag = card.select_one("[class*='price']")
            price_text = price_tag.get_text(strip=True) if price_tag else ""
            price = parse_price(price_text)

            link_tag = card.select_one("a[href]")
            link = link_tag["href"] if link_tag else ""
            if link and not link.startswith("http"):
                link = "https://www.subito.it" + link

            location_tag = card.select_one("[class*='town'],[class*='location'],[class*='city']")
            location = location_tag.get_text(strip=True) if location_tag else ""

            annunci.append({
                "id":         f"subito_{ad_id}",
                "title":      title,
                "price":      price,
                "price_text": price_text,
                "link":       link,
                "location":   location,
                "source":     "SUBITO",
                "condition":  "",
            })
        except Exception as e:
            log.warning(f"Errore parsing Subito: {e}")

    return annunci

# ============================================================
#  eBay Italia
# ============================================================

def fetch_ebay(search: dict) -> list:
    log.info(f"[{search['nome']}] eBay scraping...")

    q = quote(search["query"])
    url = (
        f"https://www.ebay.it/sch/i.html?_nkw={q}"
        f"&_udlo={search['prezzo_min']}&_udhi={search['prezzo_max']}"
        f"&LH_ItemCondition=3000"
        f"&LH_PrefLoc=1"
        f"&LH_BAP=y"
        f"&_sop=10"
    )

    try:
        resp = requests.get(url, headers=HEADERS, proxies=get_proxies(), timeout=30, verify=False)
        resp.raise_for_status()
    except Exception as e:
        log.error(f"[{search['nome']}] Errore eBay: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    annunci = []
    items = soup.select("li.s-item")
    log.info(f"[{search['nome']}] eBay: {len(items)} annunci trovati (pre-filtro)")

    for item in items:
        try:
            title_tag = item.select_one(".s-item__title")
            title = title_tag.get_text(strip=True) if title_tag else ""

            if not title or "shop on ebay" in title.lower() or "new listing" in title.lower():
                continue

            if titolo_escluso(title):
                log.info(f"  ↳ [eBay] Escluso: {title}")
                continue

            link_tag = item.select_one("a.s-item__link")
            link = link_tag["href"] if link_tag else ""

            price_tag = item.select_one(".s-item__price")
            price_text = price_tag.get_text(strip=True) if price_tag else ""
            price = parse_price(price_text)

            location_tag = item.select_one(".s-item__location")
            location = location_tag.get_text(strip=True).replace("Da ", "") if location_tag else "Italia"

            condition_tag = item.select_one(".SECONDARY_INFO")
            condition = condition_tag.get_text(strip=True) if condition_tag else ""

            if any(c in condition.lower() for c in CONDIZIONI_ESCLUSE):
                continue

            ad_id = link.split("itm/")[-1].split("?")[0] if "itm/" in link else title[:30]

            annunci.append({
                "id":         f"ebay_{ad_id}",
                "title":      title,
                "price":      price,
                "price_text": price_text,
                "link":       link,
                "location":   location,
                "source":     "EBAY",
                "condition":  condition,
            })
        except Exception as e:
            log.warning(f"Errore parsing eBay: {e}")

    log.info(f"[{search['nome']}] eBay: {len(annunci)} annunci dopo filtri")
    return annunci

# ============================================================
#  Utilità
# ============================================================

def parse_price(text: str):
    try:
        cleaned = str(text).replace(".", "").replace(",", ".").replace("€", "").strip()
        num = "".join(c for c in cleaned if c.isdigit() or c == ".")
        return float(num) if num else None
    except Exception:
        return None

def passes_filter(annuncio: dict, search: dict) -> bool:
    price = annuncio["price"]
    if price is None:
        return True
    if search.get("prezzo_max") is not None and price > search["prezzo_max"]:
        return False
    if search.get("prezzo_min") is not None and price < search["prezzo_min"]:
        return False
    return True

def calcola_margine(price, prezzo_revend):
    if price is None or prezzo_revend is None:
        return None
    return prezzo_revend - price

def valuta_affare(margine, prezzo_revend):
    if margine is None or prezzo_revend is None:
        return "❓"
    percentuale = (margine / prezzo_revend) * 100
    if percentuale >= 60:
        return "🔥 OTTIMO AFFARE"
    elif percentuale >= 40:
        return "✅ BUON AFFARE"
    elif percentuale >= 20:
        return "👍 DISCRETO"
    else:
        return "⚠️ MARGINE BASSO"

# ============================================================
#  Telegram
# ============================================================

def escape_md(text: str) -> str:
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in str(text))

def send_telegram(annuncio: dict, search: dict):
    price       = annuncio["price"]
    prezzo_txt  = annuncio["price_text"] or "Prezzo non indicato"
    luogo       = annuncio["location"] or "—"
    source      = annuncio["source"]
    condition   = annuncio.get("condition", "")
    margine     = calcola_margine(price, search.get("prezzo_revend"))
    valutazione = valuta_affare(margine, search.get("prezzo_revend"))

    if margine is not None:
        margine_txt = f"💰 Margine stimato: ~{int(margine)}€ \\(rivendi a ~{search['prezzo_revend']}€\\)"
    else:
        margine_txt = "💰 Margine: non calcolabile"

    condition_txt = f"\n🔧 {escape_md(condition)}" if condition else ""

    text = (
        f"{valutazione}\n"
        f"🔔 *{escape_md(search['nome'])}* — {source}\n\n"
        f"📦 *{escape_md(annuncio['title'])}*\n"
        f"💶 Prezzo: {escape_md(prezzo_txt)}\n"
        f"{margine_txt}\n"
        f"📍 {escape_md(luogo)}"
        f"{condition_txt}\n\n"
        f"[👉 Vedi annuncio]({annuncio['link']})"
    )

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "MarkdownV2"},
            timeout=10
        )
        resp.raise_for_status()
        log.info(f"✅ [{source}] Notifica: {annuncio['title']} — margine ~{margine}€")
    except Exception as e:
        log.error(f"❌ Errore Telegram: {e}")

def send_startup_message():
    lines = "\n".join(
        f"• {s['nome']} \\(max {s['prezzo_max']}€ → rivendi ~{s['prezzo_revend']}€\\)"
        for s in SEARCHES
    )
    text = (
        f"🤖 *Bot Flipping avviato\\!*\n\n"
        f"🎮 Monitorando ogni *{INTERVALLO_MINUTI} minuti*:\n"
        f"📦 Subito\\.it\n"
        f"🛒 eBay Italia\n\n"
        f"{lines}\n\n"
        f"Ti avviserò non appena trovo un affare\\! 🔥"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "MarkdownV2"},
            timeout=10
        )
    except Exception as e:
        log.error(f"Errore messaggio avvio: {e}")

# ============================================================
#  Loop principale
# ============================================================

def check_all():
    seen = load_seen()
    new_count = 0

    for search in SEARCHES:
        annunci = fetch_subito(search) + fetch_ebay(search)

        for ann in annunci:
            ad_id = f"{search['nome']}_{ann['id']}"
            if ad_id in seen:
                continue
            if not passes_filter(ann, search):
                seen.add(ad_id)
                continue
            log.info(f"  ✨ NUOVO [{ann['source']}]: {ann['title']} — {ann['price_text']}")
            send_telegram(ann, search)
            seen.add(ad_id)
            new_count += 1
            time.sleep(1)

        time.sleep(2)

    save_seen(seen)
    log.info(f"✔ Check completato — {new_count} nuovi annunci notificati")

def validate_config():
    if not TELEGRAM_BOT_TOKEN:
        log.error("❌ TELEGRAM_BOT_TOKEN non impostato!")
        exit(1)
    if not TELEGRAM_CHAT_ID:
        log.error("❌ TELEGRAM_CHAT_ID non impostato!")
        exit(1)
    if not PROXY_HOST:
        log.error("❌ PROXY_HOST non impostato!")
        exit(1)

if __name__ == "__main__":
    log.info("=" * 50)
    log.info("🎮 Bot Flipping avviato — Subito + eBay via Webshare")
    validate_config()
    log.info(f"Proxy: {PROXY_HOST}:{PROXY_PORT}")
    log.info(f"Ricerche: {[s['nome'] for s in SEARCHES]}")
    log.info(f"Intervallo: ogni {INTERVALLO_MINUTI} minuti")
    log.info("=" * 50)

    send_startup_message()
    check_all()

    schedule.every(INTERVALLO_MINUTI).minutes.do(check_all)
    while True:
        schedule.run_pending()
        time.sleep(30)
