#!/usr/bin/env python3
"""
Bot Telegram — Monitor Subito.it per Flipping
==============================================
Usa il feed RSS ufficiale di Subito.it per evitare blocchi 403.
Monitora ogni 2 minuti e invia notifiche Telegram con margine stimato.
"""

import requests
import schedule
import time
import json
import os
import logging
import random
import xml.etree.ElementTree as ET
from urllib.parse import quote

# ============================================================
#  ⚙️  CONFIG
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
#  Fetch RSS Subito.it
# ============================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RSS reader)",
    "Accept": "application/rss+xml, application/xml, text/xml",
}

def build_rss_url(search: dict) -> str:
    q = quote(search["query"])
    url = f"https://www.subito.it/annunci/italia/vendita/?q={q}&ps={search['prezzo_min']}&pe={search['prezzo_max']}&output=rss"
    return url

def fetch_rss(search: dict) -> list:
    url = build_rss_url(search)
    log.info(f"[{search['nome']}] RSS: {url}")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error(f"[{search['nome']}] Errore RSS: {e}")
        return []

    annunci = []
    try:
        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            log.warning(f"[{search['nome']}] Nessun channel nel RSS")
            return []

        items = channel.findall("item")
        log.info(f"[{search['nome']}] Trovati {len(items)} annunci nel RSS")

        for item in items:
            try:
                title    = item.findtext("title", "").strip()
                link     = item.findtext("link", "").strip()
                desc     = item.findtext("description", "").strip()
                pub_date = item.findtext("pubDate", "").strip()
                guid     = item.findtext("guid", link).strip()

                # Estrai ID univoco dal link o guid
                ad_id = guid.split("-")[-1].rstrip("/") if guid else link

                # Estrai prezzo dalla descrizione o dal titolo
                price, price_text = extract_price(desc + " " + title)

                # Estrai città dalla descrizione
                location = extract_location(desc)

                annunci.append({
                    "id":         ad_id,
                    "title":      title,
                    "price":      price,
                    "price_text": price_text,
                    "link":       link,
                    "location":   location,
                    "date":       pub_date,
                })
            except Exception as e:
                log.warning(f"Errore parsing item RSS: {e}")

    except ET.ParseError as e:
        log.error(f"[{search['nome']}] Errore parsing XML: {e}")

    return annunci

def extract_price(text: str):
    """Estrae il prezzo da una stringa di testo."""
    import re
    # Cerca pattern tipo "80 €", "80€", "€ 80", "80,00 €"
    patterns = [
        r'(\d{1,4}(?:[.,]\d{1,3})?)\s*€',
        r'€\s*(\d{1,4}(?:[.,]\d{1,3})?)',
        r'Prezzo[:\s]+(\d{1,4}(?:[.,]\d{1,3})?)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw = match.group(1).replace(".", "").replace(",", ".")
            try:
                price = float(raw)
                return price, f"{int(price)} €"
            except ValueError:
                pass
    return None, ""

def extract_location(desc: str) -> str:
    """Tenta di estrarre la città dalla descrizione HTML."""
    import re
    # Spesso nella descrizione c'è qualcosa tipo "Milano (MI)"
    match = re.search(r'([A-Z][a-zàèéìòù]+(?:\s[A-Z][a-zàèéìòù]+)?)\s*\([A-Z]{2}\)', desc)
    if match:
        return match.group(0)
    return ""

# ============================================================
#  Filtro
# ============================================================

def passes_filter(annuncio: dict, search: dict) -> bool:
    price = annuncio["price"]
    if price is None:
        return True  # senza prezzo lo notifichiamo comunque
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
        f"🤖 *Bot Subito\\.it aggiornato\\!*\n\n"
        f"🎮 Monitorando ogni *{INTERVALLO_MINUTI} minuti* via RSS:\n"
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
        annunci = fetch_rss(search)
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
        time.sleep(random.uniform(1.5, 3.0))

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
    log.info("🎮 Bot Subito.it Flipping avviato (RSS)")
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
