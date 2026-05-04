def fetch_via_apify(search: dict) -> list:
    log.info(f"[{search['nome']}] Avvio run Apify...")

    actor = "santamaria-automations~subito-it-scraper"

    # STEP 1 — Avvia run
    run_url = f"https://api.apify.com/v2/acts/{actor}/runs"
    params = {"token": APIFY_API_KEY}
    payload = {
        "startUrls": [{"url": search["url"]}],
        "maxItems": 50,
    }

    try:
        run_resp = requests.post(run_url, params=params, json=payload, timeout=30)
        run_resp.raise_for_status()
        run_data = run_resp.json()
    except Exception as e:
        log.error(f"[{search['nome']}] Errore avvio run: {e}")
        return []

    run_id = run_data["data"]["id"]
    log.info(f"[{search['nome']}] Run avviato: {run_id}")

    # STEP 2 — Attendi completamento
    status_url = f"https://api.apify.com/v2/actor-runs/{run_id}"
    
    for _ in range(20):  # max ~100 secondi
        try:
            status_resp = requests.get(status_url, params=params, timeout=10)
            status_resp.raise_for_status()
            status = status_resp.json()["data"]["status"]

            if status == "SUCCEEDED":
                dataset_id = status_resp.json()["data"]["defaultDatasetId"]
                break
            elif status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                log.error(f"[{search['nome']}] Run fallito: {status}")
                return []

            time.sleep(5)
        except Exception as e:
            log.warning(f"Errore polling run: {e}")
            time.sleep(5)
    else:
        log.error(f"[{search['nome']}] Timeout run")
        return []

    # STEP 3 — Recupera dataset
    dataset_url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"

    try:
        data_resp = requests.get(dataset_url, params=params, timeout=30)
        data_resp.raise_for_status()
        items = data_resp.json()
    except Exception as e:
        log.error(f"[{search['nome']}] Errore fetch dataset: {e}")
        return []

    log.info(f"[{search['nome']}] Trovati {len(items)} annunci")

    annunci = []
    for item in items:
        try:
            title = item.get("title") or item.get("name") or "Senza titolo"
            link = item.get("url") or item.get("link") or ""
            price = item.get("price") or item.get("priceValue")

            if isinstance(price, str):
                price = parse_price(price)
            elif isinstance(price, (int, float)):
                price = float(price)

            price_text = f"{int(price)} €" if price else item.get("priceText", "Prezzo non indicato")

            location = item.get("location") or item.get("city") or ""
            date_str = item.get("date") or item.get("publishedAt") or ""

            ad_id = link.split("-")[-1].rstrip("/") if link else title

            annunci.append({
                "id": ad_id,
                "title": title,
                "price": price,
                "price_text": price_text,
                "link": link,
                "location": location,
                "date": date_str,
            })
        except Exception as e:
            log.warning(f"Errore parsing item: {e}")

    return annunci
