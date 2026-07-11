#!/usr/bin/env python3
"""
scraper_newegg.py  v2.0
Scraper Newegg USA — catálogo completo de hardware
Método: HTML scraping (requests + BeautifulSoup)
Precios: USD (price_usd) — sin conversión a PEN

Fixes v2.0 (sobre v1.0):
  - [N1] _make_session: allowed_methods=['GET'] + raise_on_status=False
  - [N2] _extract_brand: fallback '' + limpieza de prefijos Newegg
         (Refurbished, Open Box, Combo)
  - [N3] _parse_cell: SKU fallback usa hashlib.md5 (determinístico)
         hash() de Python NO es determinístico entre runs → duplicados en MASTER
  - [N4] scrape_newegg: seen_skus global (no local por categoría)
  - [N5] __main__: datetime.now(timezone.utc)
"""

import re
import time
import random
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────
REQUEST_DELAY    = 2.5
TIMEOUT          = 20
MAX_PAGES        = 20
EMPTY_PAGE_LIMIT = 2
MIN_ITEMS_PAGE   = 2

BASE_URL = "https://www.newegg.com"

NEWEGG_CATEGORIES = {
    "cpu_intel":      "/p/pl?N=100007671+4814",
    "cpu_amd":        "/p/pl?N=100007671+4812",
    "gpu_nvidia":     "/p/pl?N=100007709+4836",
    "gpu_amd":        "/p/pl?N=100007709+4835",
    "ram_ddr4":       "/p/pl?N=100007611+4702",
    "ram_ddr5":       "/p/pl?N=100007611+601302378",
    "ssd_nvme":       "/p/pl?N=100167523+601302827",
    "ssd_sata":       "/p/pl?N=100167523+4706",
    "hdd_interno":    "/p/pl?N=100167523+4705",
    "mobo_intel":     "/p/pl?N=100007627+4739",
    "mobo_amd":       "/p/pl?N=100007627+4741",
    "psu":            "/p/pl?N=100007657+4751",
    "cases":          "/p/pl?N=100007583+4747",
    "cooler_aire":    "/p/pl?N=100007588+4748",
    "cooler_liquido": "/p/pl?N=100007588+4749",
    "laptops":        "/p/pl?N=100006740+4131",
    "monitores":      "/p/pl?N=100007642+4734",
    "teclados":       "/p/pl?N=100007643+4736",
    "mouse":          "/p/pl?N=100007644+4737",
    "auriculares":    "/p/pl?N=100007645+4738",
    "tarjetas_red":   "/p/pl?N=100007650+4740",
}

# ──────────────────────────────────────────────
# HEADERS ROTATIVOS
# ──────────────────────────────────────────────
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

# [N1] Retry con allowed_methods + raise_on_status — consistente con el proyecto
def _make_session() -> requests.Session:
    session = requests.Session()
    retry   = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    return session

def _get_headers() -> dict:
    return {
        "User-Agent":      random.choice(_USER_AGENTS),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "Referer":         "https://www.newegg.com/",
        "DNT":             "1",
    }


# ──────────────────────────────────────────────
# PARSEO DE PRECIO
# ──────────────────────────────────────────────
def _parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    clean = re.sub(r"[^0-9.]", "", text.replace(",", ""))
    try:
        val = float(clean)
        return val if val > 0 else None
    except (ValueError, TypeError):
        return None


# ──────────────────────────────────────────────
# EXTRACCIÓN DE MARCA
# ──────────────────────────────────────────────
_KNOWN_BRANDS = [
    "Intel", "AMD", "NVIDIA", "ASUS", "MSI", "Gigabyte", "ASRock",
    "Corsair", "G.Skill", "Kingston", "Crucial", "Samsung", "Western Digital",
    "Seagate", "EVGA", "Zotac", "Sapphire", "PowerColor", "XFX",
    "be quiet!", "Noctua", "Cooler Master", "NZXT", "Fractal Design",
    "Seasonic", "Thermaltake", "Lian Li", "Phanteks",
    "Dell", "HP", "Lenovo", "Acer", "Razer", "LG",
    "BenQ", "ViewSonic", "AOC", "Logitech", "SteelSeries", "HyperX",
    "SanDisk", "Patriot", "TeamGroup", "Micron", "Toshiba", "HGST",
]

# [N2] Prefijos Newegg que NO son marcas
_NEWEGG_TITLE_PREFIXES = re.compile(
    r"^(Refurbished|Open Box|Combo|Renewed|Used)[:\s]+",
    re.IGNORECASE,
)

def _extract_brand(title: str) -> str:
    if not title:
        return ""
    # [N2] Limpiar prefijos antes de buscar la marca
    clean_title = _NEWEGG_TITLE_PREFIXES.sub("", title).strip()
    title_lower = clean_title.lower()
    for brand in _KNOWN_BRANDS:
        if brand.lower() in title_lower:
            return brand
    # [N2] Fallback '' — evita 'Refurbished', 'Open', 'Combo' como brand
    return ""


# ──────────────────────────────────────────────
# FETCH DE UNA PÁGINA
# ──────────────────────────────────────────────
def _fetch_page(session: requests.Session, path: str, page: int) -> list:
    url = f"{BASE_URL}{path}&PageSize=96&Page={page}"
    try:
        resp = session.get(url, headers=_get_headers(), timeout=TIMEOUT)
        if resp.status_code == 404:
            logger.debug(f"  404: {url}")
            return []
        if resp.status_code != 200:
            logger.warning(f"  HTTP {resp.status_code}: {url}")
            return []
    except requests.RequestException as e:
        logger.warning(f"  Request error p{page}: {e}")
        return []

    soup  = BeautifulSoup(resp.text, "html.parser")
    items = []
    cells = soup.select("div.item-cell")
    if not cells:
        cells = soup.select("div.item-container")

    for cell in cells:
        try:
            item = _parse_cell(cell)
            if item:
                items.append(item)
        except Exception as e:
            logger.debug(f"  Error parseando celda: {e}")
            continue

    logger.debug(f"  p{page}: {len(items)} items — {url}")
    return items


# ──────────────────────────────────────────────
# PARSEO DE CELDA DE PRODUCTO
# ──────────────────────────────────────────────
def _parse_cell(cell) -> Optional[dict]:
    # ── Título ──
    title_el = (
        cell.select_one("a.item-title") or
        cell.select_one(".item-info a") or
        cell.select_one("a[title]")
    )
    if not title_el:
        return None
    title = title_el.get_text(strip=True)
    if not title or len(title) < 5:
        return None

    # ── URL ──
    url = title_el.get("href", "")
    if url and not url.startswith("http"):
        url = BASE_URL + url

    # ── SKU ──
    sku      = ""
    item_num = cell.get("data-item-id") or cell.get("data-sku")
    if item_num:
        sku = str(item_num)
    elif url:
        m = re.search(r"/p/([A-Z0-9]+)", url)
        if m:
            sku = m.group(1)
    if not sku:
        # [N3] hashlib.md5 — DETERMINÍSTICO entre runs (hash() no lo es)
        sku = "newegg_" + hashlib.md5(title.encode()).hexdigest()[:12]

    # ── Precio actual ──
    price_el = (
        cell.select_one("li.price-current") or
        cell.select_one(".price-current") or
        cell.select_one("strong.price-current-label")
    )
    price_usd = None
    if price_el:
        dollars = price_el.select_one("strong")
        cents   = price_el.select_one("sup:last-child")
        if dollars:
            d_text = dollars.get_text(strip=True).replace(",", "").replace("$", "")
            c_text = cents.get_text(strip=True).replace(".", "") if cents else "00"
            try:
                price_usd = float(f"{d_text}.{c_text}")
            except ValueError:
                price_usd = _parse_price(price_el.get_text(strip=True))
        else:
            price_usd = _parse_price(price_el.get_text(strip=True))

    if not price_usd:
        return None

    # ── Precio original ──
    orig_el = (
        cell.select_one(".price-was-data") or
        cell.select_one("span.price-was") or
        cell.select_one("li.price-was")
    )
    price_orig_usd = _parse_price(orig_el.get_text(strip=True)) if orig_el else None

    # ── Descuento ──
    discount_pct = None
    if price_orig_usd and price_orig_usd > price_usd:
        discount_pct = round((1 - price_usd / price_orig_usd) * 100, 1)

    # ── Rating (Newegg: clase CSS rating-50 → 5.0) ──
    rating_el = cell.select_one(".item-rating i.rating")
    rating    = None
    if rating_el:
        for c in rating_el.get("class", []):
            m = re.search(r"rating-(\d+)", c)
            if m:
                rating = int(m.group(1)) / 10
                break

    # ── Reviews ──
    reviews_el = (
        cell.select_one(".item-rating span") or
        cell.select_one("span.item-rating-num")
    )
    reviews = None
    if reviews_el:
        rv      = _parse_price(reviews_el.get_text(strip=True))
        reviews = int(rv) if rv else None

    # ── Marca ──
    brand = _extract_brand(title)

    return {
        "sku":            sku,
        "title":          title,
        "brand":          brand,
        "price_usd":      price_usd,
        "price_orig_usd": price_orig_usd,
        "discount_pct":   discount_pct,
        "rating":         rating,
        "reviews":        reviews,
        "url":            url,
        "price_currency": "USD",
    }


# ──────────────────────────────────────────────
# SCRAPER PRINCIPAL
# ──────────────────────────────────────────────
def scrape_newegg(batch_id: str) -> list:
    all_records = []
    now_iso     = datetime.now(timezone.utc).isoformat()
    session     = _make_session()
    # [N4] seen_skus GLOBAL — evita duplicados entre categorías
    seen_skus_global = set()

    logger.info(f"[Newegg] Iniciando — {len(NEWEGG_CATEGORIES)} categorías")

    for cat_name, path in NEWEGG_CATEGORIES.items():
        logger.info(f"[Newegg] '{cat_name}'")
        cat_records = []
        # [N4] seen_skus local solo para early-stop dentro de la categoría
        seen_skus_cat = set()
        empty_pages   = 0

        for page in range(1, MAX_PAGES + 1):
            time.sleep(REQUEST_DELAY + random.uniform(0, 0.8))
            raw_items = _fetch_page(session, path, page)

            if len(raw_items) < MIN_ITEMS_PAGE:
                empty_pages += 1
                if empty_pages >= EMPTY_PAGE_LIMIT:
                    logger.debug(f"  [{cat_name}] Early-stop p{page}")
                    break
                continue

            empty_pages = 0
            new_in_page = 0

            for item in raw_items:
                sku = item.get("sku", "")
                # [N4] Dedup global — evita mismo item en cpu_intel y cpu_amd
                if sku in seen_skus_global:
                    continue
                seen_skus_global.add(sku)
                seen_skus_cat.add(sku)
                new_in_page += 1

                record = {
                    "batch_id":       batch_id,
                    "timestamp":      now_iso,
                    "source":         "newegg_usa",
                    "category":       cat_name,
                    "sku":            sku,
                    "brand":          item.get("brand", ""),
                    "title":          item.get("title", ""),
                    "price_usd":      item.get("price_usd"),
                    "price_orig_usd": item.get("price_orig_usd"),
                    "price_pen":      None,
                    "price_orig_pen": None,
                    "price_date":     now_iso[:10],
                    "price_currency": "USD",
                    "discount_pct":   item.get("discount_pct"),
                    "rating":         item.get("rating"),
                    "reviews":        item.get("reviews"),
                    "retailer":       "Newegg",
                    "url":            item.get("url", ""),
                }
                cat_records.append(record)

            logger.debug(
                f"  [{cat_name}] p{page}: +{new_in_page} "
                f"(cat={len(cat_records)}, global={len(seen_skus_global)})"
            )

            if new_in_page == 0:
                empty_pages += 1
                if empty_pages >= EMPTY_PAGE_LIMIT:
                    break

        logger.info(f"  ✅ [{cat_name}]: {len(cat_records):,} registros")
        all_records.extend(cat_records)

    logger.info(f"[Newegg] Total: {len(all_records):,} registros únicos")
    return all_records


# ──────────────────────────────────────────────
# EJECUCIÓN DIRECTA
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import json
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    # [N5] datetime con timezone explícita
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    records  = scrape_newegg(batch_id)
    print(f"\nTotal registros: {len(records):,}")
    if records:
        print("\nEjemplo (primer registro):")
        print(json.dumps(records[0], indent=2, ensure_ascii=False))
