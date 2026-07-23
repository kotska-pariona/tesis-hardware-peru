#!/usr/bin/env python3
# scraper_newegg.py  v2.5  —  reconstruido limpio 2026-07-23
import re, time, random, hashlib, logging, json
from datetime import datetime, timezone
from typing import Optional
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

REQUEST_DELAY   = 2.5
TIMEOUT         = 20
MAX_PAGES       = 10
EMPTY_PAGE_LIMIT= 3
MIN_ITEMS_PAGE  = 2
PRICE_MIN_USD   = 1.0
PRICE_MAX_USD   = 15000.0
BASE_URL        = "https://www.newegg.com"

CATEGORIES = {
    "cpu"         : 343,
    "gpu"         : 48,
    "ram"         : 147,
    "ssd"         : 636,
    "motherboard" : 280,
    "psu"         : 58,
    "case"        : 42,
    "cooler"      : 574,
}

HEADERS = {
    "User-Agent"     : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept"         : "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer"        : "https://www.newegg.com/",
}

def _make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1.5,
                  status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update(HEADERS)
    return s

def _parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    clean = re.sub(r"[^0-9.]", "", text.replace(",", ""))
    # elimina puntos extra (ej: "1.999.00" -> toma el ultimo segmento)
    parts = clean.split(".")
    if len(parts) > 2:
        clean = parts[0] + "." + parts[-1]
    try:
        v = float(clean)
        return v if v > 0 else None
    except Exception:
        return None

def _parse_cell(cell, category: str) -> Optional[dict]:
    try:
        # --- titulo ---
        te = (cell.select_one("a.item-title")
              or cell.select_one(".item-info a")
              or cell.select_one("a[title]"))
        if not te:
            return None
        title = te.get_text(strip=True)
        if not title or len(title) < 5:
            return None

        # --- url ---
        item_url = te.get("href", "")

        # --- sku ---
        sku = cell.get("data-item-id") or cell.get("data-sku") or ""
        if not sku and item_url:
            m = re.search(r"/p/([A-Z0-9\-]+)", item_url)
            if m:
                sku = m.group(1)
        if not sku:
            sku = "newegg_" + hashlib.md5(title.encode()).hexdigest()[:12]

        # --- precio ---
        pe = (cell.select_one("li.price-current")
              or cell.select_one(".price-current"))
        if not pe:
            return None
        price_text = pe.get_text(strip=True)
        price_usd  = _parse_price(price_text)
        if not price_usd:
            return None
        if not (PRICE_MIN_USD <= price_usd <= PRICE_MAX_USD):
            return None

        # --- imagen ---
        img_el  = cell.select_one("a.item-img img") or cell.select_one("img")
        img_url = img_el.get("src", "") if img_el else ""

        # --- rating ---
        rating_el = cell.select_one(".item-rating-num")
        rating_txt= rating_el.get_text(strip=True).strip("()") if rating_el else ""
        try:
            rating = int(rating_txt)
        except Exception:
            rating = 0

        return {
            "sku"         : sku,
            "titulo"      : title,
            "precio_usd"  : price_usd,
            "moneda"      : "USD",
            "categoria"   : category,
            "fuente"      : "newegg_usa",
            "url"         : item_url,
            "imagen_url"  : img_url,
            "rating_count": rating,
            "fecha_scrape": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
    except Exception as e:
        logger.debug(f"_parse_cell error: {e}")
        return None

def _fetch_page(session: requests.Session, cat_id: int, page: int) -> list[dict]:
    url = f"{BASE_URL}/CPUs-Processors/SubCategory/ID-{cat_id}?PageSize=96&Page={page}"
    try:
        r = session.get(url, timeout=TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        logger.warning(f"  p{page}: request error — {e}")
        return []

    soup  = BeautifulSoup(r.text, "html.parser")
    cells = soup.select("div.item-cell") or soup.select("div.item-container")
    logger.info(f"  p{page}: {len(cells)} celdas detectadas")
    if not cells:
        logger.info(f"  p{page}: 0 celdas — early-stop")
        return []
    return cells

def scrape_category(cat_name: str, cat_id: int) -> list[dict]:
    logger.info(f"[Newegg] Iniciando categoria {cat_name.upper()} (ID {cat_id})")
    session      = _make_session()
    all_items    = []
    empty_streak = 0

    for page in range(1, MAX_PAGES + 1):
        time.sleep(REQUEST_DELAY + random.uniform(0, 1.0))
        cells = _fetch_page(session, cat_id, page)

        if not cells:
            empty_streak += 1
            logger.info(f"  p{page}: streak vacio {empty_streak}/{EMPTY_PAGE_LIMIT}")
            if empty_streak >= EMPTY_PAGE_LIMIT:
                break
            continue

        page_items = []
        for cell in cells:
            item = _parse_cell(cell, cat_name)
            if item:
                page_items.append(item)

        logger.info(f"  p{page}: {len(page_items)}/{len(cells)} items validos")

        if len(page_items) < MIN_ITEMS_PAGE:
            empty_streak += 1
            logger.info(f"  p{page}: pocos items — streak {empty_streak}/{EMPTY_PAGE_LIMIT}")
            if empty_streak >= EMPTY_PAGE_LIMIT:
                break
        else:
            empty_streak = 0
            all_items.extend(page_items)

    logger.info(f"[Newegg] {cat_name.upper()}: {len(all_items)} items totales")
    return all_items

def scrape_all() -> list[dict]:
    all_items = []
    for cat_name, cat_id in CATEGORIES.items():
        items = scrape_category(cat_name, cat_id)
        all_items.extend(items)
        time.sleep(random.uniform(3.0, 6.0))
    logger.info(f"[Newegg] TOTAL GLOBAL: {len(all_items)} items")
    return all_items

if __name__ == "__main__":
    # Prueba rapida: solo CPU, 2 paginas
    items = scrape_category("cpu", 343)
    print(f"\n{'='*60}")
    print(f"Items obtenidos: {len(items)}")
    if items:
        print(json.dumps(items[:2], indent=2, ensure_ascii=False))
    else:
        print("[]")
