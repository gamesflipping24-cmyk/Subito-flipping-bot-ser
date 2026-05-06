#!/usr/bin/env python3
"""
Bot Telegram — Monitor eBay Italia per Flipping
================================================
- eBay Italia → richiesta diretta, nessun proxy necessario
- Solo venditori privati, solo Italia, solo usato buono+
- Monitora ogni 20 minuti
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

# Frasi esatte che indicano vendita solo scatola/accessori
TITOLI_ESCLUSI_ESATTI = [
    "solo scatola", "only box", "box only", "solo box",
    "solo manuale", "solo custodia", "solo cover",
    "solo caricatore", "solo alimentatore", "scatola vuota", "empty box",
]

# Condizioni non accettate
CONDIZIONI_ESCLUSE = [
    "for parts", "not working", "per ricambi",
    "non funzionante", "parts only", "da riparare", "broken",
]

INTERVALLO_MINUTI = 20
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
    for frase in TITOLI_ESCLUSI_ESATTI:
        if frase in title_lower:
            return True
    for cond in CONDIZIONI_ESCLUSE:
        if cond in title_lower:
            return True
    return False

# ============================================================
#  eBay Italia — richiesta diretta
# ============================================================

EBAY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def fetch_ebay(search: dict) -> list:
    log.info(f"[{search['nome']}] eBay scraping...")

    q = quote(search["query"])
    url = (
        f"https://www.ebay.it/sch/i.html?_nkw={q}"
        f"&_udlo={search['prezzo_min']}&_udhi={search['prezzo_max']}"
        f"&LH_ItemCondition=3000"   # Usato
        f"&LH_PrefLoc=1"            # Solo Italia
        f"&LH_BAP=y"                # Solo privati
        f"&_sop=10"                 # Più recenti prima
    )

    try:
        resp = requests.get(url, headers=EBAY_HEADERS, timeout=20)
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
                log.info(f"  ↳ [eBay] Escluso per condizione: {title}")
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
            log.warning(f"Errore parsing eBay item: {e}")

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
        f"🔔 *{escape_md(search['nome'])}* — EBAY 🛒\n\n"
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
        log.info(f"✅ Notifica: {annuncio['title']} — margine ~{margine}€")
    except Exception as e:
        log.error(f"❌ Errore Telegram: {e}")

def send_startup_message():
    lines = "\n".join(
        f"• {s['nome']} \\(max {s['prezzo_max']}€ → rivendi ~{s['prezzo_revend']}€\\)"
        for s in SEARCHES
    )
    text = (
        f"🤖 *Bot Flipping aggiornato\\!*\n\n"
        f"🛒 Monitorando eBay Italia ogni *{INTERVALLO_MINUTI} minuti*\n"
        f"\\(solo privati, solo usato, solo Italia\\)\n\n"
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
        annunci = fetch_ebay(search)

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

if __name__ == "__main__":
    log.info("=" * 50)
    log.info("🎮 Bot Flipping avviato — eBay Italia")
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
