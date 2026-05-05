#!/usr/bin/env python3
"""
Bot Telegram — Monitor Subito.it + eBay per Flipping
=====================================================
Usa ScraperAPI per bypassare i blocchi di Subito.it ed eBay.
Monitora ogni 5 minuti e invia notifiche Telegram con margine stimato.
"""

import requests
import schedule
import time
import json
import os
import logging
from bs4 import BeautifulSoup
from urllib.parse import quote

# ============================================================
#  CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
SCRAPER_API_KEY    = os.environ.get("SCRAPER_API_KEY", "")

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

# Frasi ESATTE che indicano che vendono SOLO la scatola/accessori senza console
# Usiamo frasi intere per evitare falsi positivi
TITOLI_ESCLUSI_ESATTI = [
    "solo scatola",
    "only box",
    "box only",
    "solo box",
    "solo manuale",
    "solo custodia",
    "solo cover",
    "solo caricatore",
    "solo alimentatore",
    "scatola vuota",
    "empty box",
]

# Parole che da SOLE indicano "per ricambi" o non funzionante
CONDIZIONI_ESCLUSE = [
    "for parts",
    "not working",
    "per ricambi",
    "non funzionante",
    "parts only",
    "da riparare",
    "broken",
]

INTERVALLO_MINUTI = 5
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
#  Filtro titoli
# ============================================================

def titolo_escluso(title: str) -> bool:
    title_lower = title.lower()

    # Controlla frasi esatte (solo scatola, box only, ecc.)
    for frase in TITOLI_ESCLUSI_ESATTI:
        if frase in title_lower:
            return True

    # Controlla condizioni non funzionante
    for cond in CONDIZIONI_ESCLUSE:
        if cond in title_lower:
            return True

    return False

# ============================================================
#  ScraperAPI — fetch generico per Subito
# ============================================================

def scraper_get(url: str):
    proxy_url = f"http://scraperapi:{SCRAPER_API_KEY}@proxy-server.scraperapi.com:8001"
    try:
        resp = requests.get(
            url,
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=60,
            verify=False
        )
        resp.raise_for_status()
        return resp
    except Exception as e:
        log.error(f"ScraperAPI error: {e}")
        return None

# ============================================================
#  Subito.it scraping via ScraperAPI
# ============================================================

def fetch_subito(search: dict) -> list:
    q = quote(search["query"])
    url = f"https://www.subito.it/annunci/italia/vendita/?q={q}&ps={search['prezzo_min']}&pe={search['prezzo_max']}"
    log.info(f"[{search['nome']}] Subito scraping: {url}")

    resp = scraper_get(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    annunci = []

    cards = soup.select("article[class*='item-card']")
    if not cards:
        cards = soup.select("div[class*='item-list'] article")

    log.info(f"[{search['nome']}] Subito: trovate {len(cards)} card")

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

            # Filtro titolo anche su Subito
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
                "id":          f"subito_{ad_id}",
                "title":       title,
                "price":       price,
                "price_text":  price_text,
                "link":        link,
                "location":    location,
                "source":      "SUBITO",
                "condition":   "",
                "seller_type": "private",
            })
        except Exception as e:
            log.warning(f"Errore parsing card Subito: {e}")

    return annunci

# ============================================================
#  eBay.it scraping via ScraperAPI structured endpoint
# ============================================================

def fetch_ebay(search: dict) -> list:
    log.info(f"[{search['nome']}] eBay scraping...")

    try:
        resp = requests.get(
            "https://api.scraperapi.com/structured/ebay/search",
            params={
                "api_key":      SCRAPER_API_KEY,
                "query":        search["query"],
                "country_code": "it",
                "tld":          "it",
                "sort":         "newly_listed",
                "condition":    "used",
                "pricing_min":  search["prezzo_min"],
                "pricing_max":  search["prezzo_max"],
            },
            timeout=60
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.error(f"[{search['nome']}] Errore eBay ScraperAPI: {e}")
        return []

    items = data if isinstance(data, list) else data.get("results", data.get("organic_results", []))
    log.info(f"[{search['nome']}] eBay: trovati {len(items)} annunci (pre-filtro)")

    annunci = []
    for item in items:
        try:
            title      = item.get("product_title") or item.get("title") or "Senza titolo"
            link       = item.get("product_url") or item.get("link") or ""
            condition  = (item.get("condition") or "").lower()
            location   = item.get("item_location") or item.get("location") or ""
            price_data = item.get("item_price") or {}

            if isinstance(price_data, dict):
                price = float(price_data.get("value") or price_data.get("from", {}).get("value") or 0)
            elif isinstance(price_data, (int, float)):
                price = float(price_data)
            else:
                price = parse_price(str(price_data))

            price_text = f"{int(price)} €" if price else "Prezzo non indicato"
            ad_id = link.split("/")[-1] if link else title[:30]

            # Filtro titolo (solo scatola, per ricambi, ecc.)
            if titolo_escluso(title):
                log.info(f"  ↳ [eBay] Escluso per titolo: {title}")
                continue

            # Filtro condizione
            if any(c in condition for c in CONDIZIONI_ESCLUSE):
                log.info(f"  ↳ [eBay] Escluso per condizione '{condition}': {title}")
                continue

            # Filtro: solo Italia
            if location and not location_is_italy(location):
                log.info(f"  ↳ [eBay] Escluso per posizione '{location}': {title}")
                continue

            # Filtro venditore professionale
            seller_type = detect_seller_type(item)
            if seller_type == "professional":
                log.info(f"  ↳ [eBay] Escluso venditore pro: {title}")
                continue

            annunci.append({
                "id":          f"ebay_{ad_id}",
                "title":       title,
                "price":       price if price else None,
                "price_text":  price_text,
                "link":        link,
                "location":    location or "eBay Italia",
                "source":      "EBAY",
                "condition":   condition,
                "seller_type": seller_type,
            })
        except Exception as e:
            log.warning(f"Errore parsing item eBay: {e}")

    log.info(f"[{search['nome']}] eBay: {len(annunci)} annunci dopo filtri")
    return annunci

def location_is_italy(location: str) -> bool:
    italian_indicators = [
        "italy", "italia", "milan", "milano", "roma", "rome", "napoli",
        "torino", "bologna", "firenze", "venezia", "genova", "palermo",
        "bari", "catania", "sicilia", "sardegna", "it",
    ]
    loc_lower = location.lower()
    return any(ind in loc_lower for ind in italian_indicators)

def detect_seller_type(item: dict) -> str:
    seller_rating = item.get("seller_rating_count", 0) or 0
    if isinstance(seller_rating, (int, float)) and seller_rating > 500:
        return "professional"
    return "private"

# ============================================================
#  Utilità prezzi
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
    seller_tag  = "👤 Privato" if annuncio.get("seller_type") == "private" else "🏪 Venditore"

    if margine is not None:
        margine_txt = f"💰 Margine stimato: ~{int(margine)}€ \\(rivendi a ~{search['prezzo_revend']}€\\)"
    else:
        margine_txt = "💰 Margine: non calcolabile"

    condition_txt = f"\n🔧 Condizione: {escape_md(condition)}" if condition else ""

    text = (
        f"{valutazione}\n"
        f"🔔 *{escape_md(search['nome'])}* — {source}\n\n"
        f"📦 *{escape_md(annuncio['title'])}*\n"
        f"💶 Prezzo: {escape_md(prezzo_txt)}\n"
        f"{margine_txt}\n"
        f"📍 {escape_md(luogo)}\n"
        f"{seller_tag}{condition_txt}\n\n"
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
        f"🤖 *Bot Flipping aggiornato\\!*\n\n"
        f"🎮 Monitorando ogni *{INTERVALLO_MINUTI} minuti* su:\n"
        f"📦 Subito\\.it\n"
        f"🛒 eBay Italia \\(solo privati, solo usato buono\\+\\)\n\n"
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
    if not SCRAPER_API_KEY:
        log.error("❌ SCRAPER_API_KEY non impostato!")
        exit(1)

if __name__ == "__main__":
    log.info("=" * 50)
    log.info("🎮 Bot Flipping avviato — Subito + eBay")
    validate_config()
    log.info(f"Ricerche: {[s['nome'] for s in SEARCHES]}")
    log.info(f"Intervallo: ogni {INTERVALLO_MINUTI} minuti")
    log.info("=" * 50)

    send_startup_message()
    check_all()

    schedule.every(INTERVALLO_MINUTI).minutes.do(check_all)
    while True:
        schedule.run_pending()
        time.sleep(30)
