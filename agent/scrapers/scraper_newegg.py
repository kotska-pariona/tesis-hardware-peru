#!/usr/bin/env python3
"""
scraper_newegg.py  v1.0
Scraper Newegg USA — catálogo completo de hardware
Método: HTML scraping (requests + BeautifulSoup)
Precios: USD (price_usd) — sin conversión a PEN
"""

import re
import time
import random
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
REQUEST_DELAY      = 2.5          # segundos entre requests
TIMEOUT            = 20
MAX_PAGES          = 20           # por categoría
EMPTY_PAGE_LIMIT   = 2            # early-stop: páginas vacías consecutivas
MIN_ITEMS_PAGE     = 2            # mínimo de items para considerar página válida

BASE_URL = "https://www.newegg.com"

# ──────────────────────────────────────────────
# CATEGORÍAS — catálogo completo hardware
# (node_id sacado de las URLs de Newegg)
# ──────────────────────────────────────────────
NEWEGG_CATEGORIES = {
    # Procesadores
    "cpu_intel":        "/p/pl?N=100007671+4814",
    "cpu_amd":          "/p/pl?N=100007671+4812",
    # Tarjetas de video
    "gpu_nvidia":       "/p/pl?N=100007709+4836",
    "gpu_amd":          "/p/pl?N=100007709+4835",
    # Memoria RAM
    "ram_ddr4":         "/p/pl?N=100007611+4702",
    "ram_ddr5":         "/p/pl?N=100007611+601302378",
    # Almacenamiento
    "ssd_nvme":         "/p/pl?N=100167523+601302827",
    "ssd_sata":         "/p/pl?N=100167523+4706",
    "hdd_interno":      "/p/pl?N=100167523+4705",
    # Placas madre
    "mobo_intel":       "/p/pl?N=100007627+4739",
    "mobo_amd":         "/p/pl?N=100007627+4741",
    # Fuentes de poder
    "psu":              "/p/pl?N=100007657+4751",
    # Gabinetes
    "cases":            "/p/pl?N=100007583+4747",
    # Refrigeración
    "cooler_aire":      "/p/pl?N=100007588+4748",
    "cooler_liquido":   "/p/pl?N=100007588+4749",
    # Laptops
    "laptops":          "/p/pl?N=100006740+4131",
    # Monitores
    "monitores":        "/p/pl?N=100007642+4734",
    # Teclados
    "teclados":         "/p/pl?N=100007643+4736",
    # Mouse
    "mouse":            "/p/pl?N=100007644+4737",
    # Auriculares / Headsets
    "auriculares":      "/p/pl?N=100007645+4738",
    # Tarjetas de red
    "tarjetas_red":     "/p/pl?N=100007650+4740",
}

# ──────────────────────────────────────────────
# HEADERS ROTATIVOS — anti-bot básico
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

def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def _get_headers() -> dict:
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": "https://www.newegg.com/",
        "DNT": "1",
    }


# ──────────────────────────────────────────────
# PARSEO DE PRECIO
# ──────────────────────────────────────────────
def _parse_price(text: str) -> Optional[float]:
    """Extrae float de strings como '$1,299.99' o '1299.99'"""
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

def _extract_brand(title: str) -> str:
    if not title:
        return ""
    title_lower = title.lower()
    for brand in _KNOWN_BRANDS:
        if brand.lower() in title_lower:
            return brand
    return title.split()[0] if title else ""


# ──────────────────────────────────────────────
# FETCH DE UNA PÁGINA
# ──────────────────────────────────────────────
def _fetch_page(session: requests.Session, path: str, page: int) -> list:
    """
    Retorna lista de dicts con campos raw de cada producto.
    path: ej. '/p/pl?N=100007671+4814'
    """
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

    # Newegg usa .item-cell como contenedor de cada producto
    cells = soup.select("div.item-cell")
    if not cells:
        cells = soup.select("div.item-container")  # fallback

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

    # ── URL del producto ──
    url = title_el.get("href", "")
    if url and not url.startswith("http"):
        url = BASE_URL + url

    # ── SKU / item number ──
    sku = ""
    item_num = cell.get("data-item-id") or cell.get("data-sku")
    if item_num:
        sku = str(item_num)
    elif url:
        # Extraer de URL: /p/N82E16819113771 → N82E16819113771
        m = re.search(r"/p/([A-Z0-9]+)", url)
        if m:
            sku = m.group(1)
    if not sku:
        sku = f"newegg_{abs(hash(title)) % 10**10}"

    # ── Precio actual ──
    price_el = (
        cell.select_one("li.price-current") or
        cell.select_one(".price-current") or
        cell.select_one("strong.price-current-label")
    )
    price_usd = None
    if price_el:
        # Newegg separa dólares y centavos en <strong> y <sup>
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
        return None  # sin precio = descartado

    # ── Precio original (antes del descuento) ──
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

    # ── Rating (escala Newegg: 0–50 → 0.0–5.0) ──
    rating_el = cell.select_one(".item-rating i.rating")
    rating = None
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
        rv = _parse_price(reviews_el.get_text(strip=True))
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
    """
    Scraper principal de Newegg USA.
    Retorna lista de dicts con campos normalizados.
    Precios en USD (price_usd). price_pen = None (no aplica).
    """
    all_records = []
    now_iso     = datetime.now(timezone.utc).isoformat()
    session     = _make_session()

    logger.info(f"[Newegg] Iniciando — {len(NEWEGG_CATEGORIES)} categorías")

    for cat_name, path in NEWEGG_CATEGORIES.items():
        logger.info(f"[Newegg] '{cat_name}'")
        cat_records = []
        seen_skus   = set()
        empty_pages = 0

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
                if sku in seen_skus:
                    continue
                seen_skus.add(sku)
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

            logger.debug(f"  [{cat_name}] p{page}: +{new_in_page} (total={len(cat_records)})")

            if new_in_page == 0:
                empty_pages += 1
                if empty_pages >= EMPTY_PAGE_LIMIT:
                    break

        logger.info(f"  ✅ [{cat_name}]: {len(cat_records):,} registros")
        all_records.extend(cat_records)

    logger.info(f"[Newegg] Total: {len(all_records):,} registros")
    return all_records


# ──────────────────────────────────────────────
# EJECUCIÓN DIRECTA (test local)
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import json
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    records  = scrape_newegg(batch_id)
    print(f"\nTotal registros: {len(records):,}")
    if records:
        print("\nEjemplo (primer registro):")
        print(json.dumps(records[0], indent=2, ensure_ascii=False))
