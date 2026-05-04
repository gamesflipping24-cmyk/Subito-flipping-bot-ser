#!/usr/bin/env python3
"""
Bot Telegram — Monitor Subito.it per Flipping via Apify
========================================================
Usa Apify per bypassare i blocchi di Subito.it.
Monitora ogni 5 minuti e invia notifiche Telegram con margine stimato.
"""

import requests
import schedule
import time
import json
import os
import logging

# ============================================================
#  CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
APIFY_API_KEY      = os.environ.get("APIFY_API_KEY", "")

SEARCHES = [
    {
        "nome":          "Nintendo 3DS XL",
        "url":           "https://www.subito.it/annunci/italia/vendita/?q=nintendo+3ds+xl&ps=5&pe=130",
        "prezzo_min":    5,
        "prezzo_max":    130,
        "prezzo_revend": 200,
    },
    {
        "nome":          "Nintendo 3DS",
        "url":           "https://www.subito.it/annunci/italia/vendita/?q=nintendo+3ds&ps=5&pe=70",
        "prezzo_min":    5,
        "prezzo_max":    70,
        "prezzo_revend": 150,
    },
]

INTERVALLO_MINUTI = 5
SEEN_FILE = "/tmp/seen_ids.json"

# Apify actor per Subito.it
APIFY_ACTOR = "santamaria-automations/subito-it-scraper"

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
#  Apify scraper
# ============================================================

def fetch_via_apify(search: dict) -> list:
    log.info(f"[{search['nome']}] Chiamata Apify...")

    # Avvia il run dell'actor
    run_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items"
    params  = {"token": APIFY_API_KEY}
    payload = {
        "startUrls": [search["url"]],
        "maxItems":  50,
    }

    try:
        resp = requests.post(run_url, params=params, json=payload, timeout=120)
        resp.raise_for_status()
        items = resp.json()
    except requests.RequestException as e:
        log.error(f"[{search['nome']}] Errore Apify: {e}")
        return []

    log.info(f"[{search['nome']}] Apify ha restituito {len(items)} annunci")

    annunci = []
    for item in items:
        try:
            # Estrai i campi dal JSON di Apify
            title      = item.get("title") or item.get("name") or "Senza titolo"
            link       = item.get("url") or item.get("link") or ""
            price      = item.get("price") or item.get("priceValue") or None
            price_text = f"{int(price)} €" if price else item.get("priceText", "Prezzo non indicato")
            location   = item.get("location") or item.get("city") or ""
            date_str   = item.get("date") or item.get("publishedAt") or ""

            # ID univoco dall'URL
            ad_id = link.split("-")[-1].rstrip("/") if link else title

            # Converti prezzo in float se stringa
            if isinstance(price, str):
                price = parse_price(price)
            elif isinstance(price, (int, float)):
                price = float(price)

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
            log.warning(f"Errore parsing item Apify: {e}")

    return annunci

def parse_price(text: str):
    try:
        cleaned = str(text).replace(".", "").replace(",", ".").replace("€", "").strip()
        num = "".join(c for c in cleaned if c.isdigit() or c == ".")
        return float(num) if num else None
    except Exception:
        return None

# ============================================================
#  Filtro
# ============================================================

def passes_filter(annuncio: dict, search: dict) -> bool:
    price = annuncio["price"]
    if price is None:
        return True
    if search.get("prezzo_max") is not None and price > search["prezzo_max"]:
        return False
    if search.get("prezzo_min") is not None and price < search["prezzo_min"]:
        return False
    return True

# ============================================================
#  Margine
# ============================================================

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
    data        = annuncio["date"] or "—"
    margine     = calcola_margine(price, search.get("prezzo_revend"))
    valutazione = valuta_affare(margine, search.get("prezzo_revend"))

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

def send_startup_message():
    lines = "\n".join(
        f"• {s['nome']} \\(max {s['prezzo_max']}€ → rivendi ~{s['prezzo_revend']}€\\)"
        for s in SEARCHES
    )
    text = (
        f"🤖 *Bot Subito\\.it riavviato con Apify\\!*\n\n"
        f"🎮 Monitorando ogni *{INTERVALLO_MINUTI} minuti*:\n"
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
        annunci = fetch_via_apify(search)
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

    save_seen(seen)
    log.info(f"✔ Check completato — {new_count} nuovi annunci notificati")

def validate_config():
    if not TELEGRAM_BOT_TOKEN:
        log.error("❌ TELEGRAM_BOT_TOKEN non impostato!")
        exit(1)
    if not TELEGRAM_CHAT_ID:
        log.error("❌ TELEGRAM_CHAT_ID non impostato!")
        exit(1)
    if not APIFY_API_KEY:
        log.error("❌ APIFY_API_KEY non impostato!")
        exit(1)

if __name__ == "__main__":
    log.info("=" * 50)
    log.info("🎮 Bot Subito.it Flipping avviato con Apify")
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
