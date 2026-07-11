#!/usr/bin/env python3
"""
scraper_newegg.py  v2.1
Scraper Newegg USA — catálogo completo de hardware
Método: HTML scraping (requests + BeautifulSoup)
Precios: USD (price_usd) — sin conversión a PEN

Fixes v2.1 (sobre v2.0):
  - [N6]  NEWEGG_CATEGORIES: URLs actualizadas al sistema 2025-2026
  - [N7]  USER_AGENTS: Chrome 125 → Chrome 136 (julio 2026)
  - [N8]  _parse_cell precio: usa _parse_price(texto completo) — evita
          error con <sup>.</sup><sup>99</sup> en HTML de Newegg
  - [N9]  category: nombre interno → categoría normalizada via CAT_NORMALIZE
          ("cpu_intel" → "CPU", "gpu_nvidia" → "GPU", etc.)
  - [N10] timestamp: por record (no fijo al inicio del scrape)
  - [N11] MAX_PAGES: 20 → 10 (Newegg máx 10-12 páginas reales)
  - [N12] reviews: parser dedicado int (no _parse_price float)
  - [N13] Log de tiempo total al finalizar
  - [M20] EMPTY_PAGE_LIMIT: 2 → 3 (menos agresivo)
  - [M22] _KNOWN_BRANDS: +DeepCool, +Thermalright, +Hyte, +Zephyrus
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
MAX_PAGES        = 10             # [N11] era 20
EMPTY_PAGE_LIMIT = 3              # [M20] era 2
MIN_ITEMS_PAGE   = 2

BASE_URL = "https://www.newegg.com"

# [N6] URLs actualizadas al sistema de filtros 2025-2026
NEWEGG_CATEGORIES = {
    "cpu_intel":      "/CPUs-Processors/Intel/_/N-8o6Z50g8r",
    "cpu_amd":        "/CPUs-Processors/AMD/_/N-8o6Z4saZ50g8r",
    "gpu_nvidia":     "/Video-Cards-Video-Devices/NVIDIA/_/N-8o6Z4k6Z50g8r",
    "gpu_amd":        "/Video-Cards-Video-Devices/AMD/_/N-8o6Z4saZ4k6Z50g8r",
    "ram_ddr4":       "/RAM-Memory/DDR4/_/N-8o6Z50g8rZ4702",
    "ram_ddr5":       "/RAM-Memory/DDR5/_/N-8o6Z50g8rZ601302378",
    "ssd_nvme":       "/Hard-Drives-Storage/SSD-Solid-State-Drives/NVMe/_/N-8o6Z50g8rZ601302827",
    "ssd_sata":       "/Hard-Drives-Storage/SSD-Solid-State-Drives/SATA/_/N-8o6Z50g8rZ4706",
    "hdd_interno":    "/Hard-Drives-Storage/Internal-Hard-Drives/_/N-8o6Z50g8rZ4705",
    "mobo_intel":     "/Motherboards/Intel/_/N-8o6Z50g8rZ4739",
    "mobo_amd":       "/Motherboards/AMD/_/N-8o6Z50g8rZ4741",
    "psu":            "/Power-Supplies/_/N-8o6Z50g8rZ4751",
    "cases":          "/Computer-Cases/_/N-8o6Z50g8rZ4747",
    "cooler_aire":    "/Cooling-Systems/Air-Cooling/_/N-8o6Z50g8rZ4748",
    "cooler_liquido": "/Cooling-Systems/Liquid-Cooling/_/N-8o6Z50g8rZ4749",
    "laptops":        "/Laptops-Notebooks/_/N-8o6Z50g8rZ4131",
    "monitores":      "/Monitors/_/N-8o6Z50g8rZ4734",
    "teclados":       "/Keyboards/_/N-8o6Z50g8rZ4736",
    "mouse":          "/Mouse/_/N-8o6Z50g8rZ4737",
    "auriculares":    "/Headsets-Headphones/_/N-8o6Z50g8rZ4738",
    "tarjetas_red":   "/Networking-Adapters/_/N-8o6Z50g8rZ4740",
}

# [N9] Mapeo a categorías normalizadas del pipeline
CAT_NORMALIZE = {
    "cpu_intel":      "CPU",
    "cpu_amd":        "CPU",
    "gpu_nvidia":     "GPU",
    "gpu_amd":        "GPU",
    "ram_ddr4":       "RAM",
    "ram_ddr5":       "RAM",
    "ssd_nvme":       "SSD",
    "ssd_sata":       "SSD",
    "hdd_interno":    "SSD",
    "mobo_intel":     "MOTHERBOARD",
    "mobo_amd":       "MOTHERBOARD",
    "psu":            "PSU",
    "cases":          "CASE",
    "cooler_aire":    "COOLER",
    "cooler_liquido": "COOLER",
    "laptops":        "LAPTOP",
    "monitores":      "MONITOR",
    "teclados":       "KEYBOARD",
    "mouse":          "MOUSE",
    "auriculares":    "AUDIO",
    "tarjetas_red":   "OTHER",
}

# ──────────────────────────────────────────────
# HEADERS ROTATIVOS
# ──────────────────────────────────────────────
# [N7] Chrome 136 — julio 2026
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) "
    "Gecko/20100101 Firefox/138.0",
]

# [N1] Retry con allowed_methods + raise_on_status
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
# [M22] Marcas 2025-2026 agregadas
_KNOWN_BRANDS = [
    "Intel", "AMD", "NVIDIA", "ASUS", "MSI", "Gigabyte", "ASRock",
    "Corsair", "G.Skill", "Kingston", "Crucial", "Samsung", "Western Digital",
    "Seagate", "EVGA", "Zotac", "Sapphire", "PowerColor", "XFX",
    "be quiet!", "Noctua", "Cooler Master", "NZXT", "Fractal Design",
    "Seasonic", "Thermaltake", "Lian Li", "Phanteks",
    "Dell", "HP", "Lenovo", "Acer", "Razer", "LG",
    "BenQ", "ViewSonic", "AOC", "Logitech", "SteelSeries", "HyperX",
    "SanDisk", "Patriot", "TeamGroup", "Micron", "Toshiba", "HGST",
    "DeepCool", "Thermalright", "Hyte", "Montech",   # [M22] nuevas
]

_NEWEGG_TITLE_PREFIXES = re.compile(
    r"^(Refurbished|Open Box|Combo|Renewed|Used)[:\s]+",
    re.IGNORECASE,
)

def _extract_brand(title: str) -> str:
    if not title:
        return ""
    clean_title = _NEWEGG_TITLE_PREFIXES.sub("", title).strip()
    title_lower = clean_title.lower()
    for brand in _KNOWN_BRANDS:
        if brand.lower() in title_lower:
            return brand
    return ""


# ──────────────────────────────────────────────
# FETCH DE UNA PÁGINA
# ──────────────────────────────────────────────
def _fetch_page(session: requests.Session, path: str, page: int) -> list:
    url = f"{BASE_URL}{path}?PageSize=96&Page={page}"
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
        m = re.search(r"/p/([A-Z0-9\-]+)", url)
        if m:
            sku = m.group(1)
    if not sku:
        # [N3] hashlib.md5 — determinístico entre runs
        sku = "newegg_" + hashlib.md5(title.encode()).hexdigest()[:12]

    # ── Precio actual [N8] — texto completo evita error con <sup>.</sup> ──
    price_el = (
        cell.select_one("li.price-current") or
        cell.select_one(".price-current") or
        cell.select_one("strong.price-current-label")
    )
    price_usd = None
    if price_el:
        # [N8] _parse_price sobre texto completo — robusto ante variantes HTML
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

    # ── Rating ──
    rating_el = cell.select_one(".item-rating i.rating")
    rating    = None
    if rating_el:
        for c in rating_el.get("class", []):
            m = re.search(r"rating-(\d+)", c)
            if m:
                rating = int(m.group(1)) / 10
                break

    # ── Reviews [N12] — parser int dedicado ──
    reviews_el = (
        cell.select_one(".item-rating span") or
        cell.select_one("span.item-rating-num")
    )
    reviews = None
    if reviews_el:
        raw_rev = re.sub(r"[^\d]", "", reviews_el.get_text(strip=True))
        reviews = int(raw_rev) if raw_rev else None

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
    t_start     = time.time()   # [N13]
    all_records = []
    session     = _make_session()
    # [N4] seen_skus GLOBAL — evita duplicados entre categorías
    seen_skus_global = set()

    logger.info(f"[Newegg] Iniciando — {len(NEWEGG_CATEGORIES)} categorías")

    for cat_name, path in NEWEGG_CATEGORIES.items():
        logger.info(f"[Newegg] '{cat_name}'")
        cat_records = []
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
                if sku in seen_skus_global:
                    continue
                seen_skus_global.add(sku)
                new_in_page += 1

                # [N9] categoría normalizada
                cat_normalized = CAT_NORMALIZE.get(cat_name, cat_name.upper())

                # [N10] timestamp por record — no fijo al inicio
                record = {
                    "batch_id":       batch_id,
                    "timestamp":      datetime.now(timezone.utc).isoformat(),
                    "source":         "newegg_usa",
                    "category":       cat_normalized,          # [N9]
                    "category_raw":   cat_name,                # debug
                    "sku":            sku,
                    "brand":          item.get("brand", ""),
                    "title":          item.get("title", ""),
                    "price_usd":      item.get("price_usd"),
                    "price_orig_usd": item.get("price_orig_usd"),
                    "price_date":     datetime.now(timezone.utc).strftime("%Y-%m-%d"),
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

    # [N13] Log de tiempo total
    elapsed = time.time() - t_start
    logger.info(
        f"[Newegg] Total: {len(all_records):,} registros únicos "
        f"— ⏱ {elapsed/60:.1f} min"
    )
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
