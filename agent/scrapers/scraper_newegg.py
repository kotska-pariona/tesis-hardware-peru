#!/usr/bin/env python3
"""
scraper_newegg.py  v2.3
Scraper Newegg USA — catálogo completo de hardware
Método: HTML scraping (requests + BeautifulSoup)
Precios: USD (price_usd) — sin conversión a PEN

Fixes v2.3 (sobre v2.2):
  [N19] NEWEGG_CATEGORIES: migración completa a SubCategory/ID-*
        — URLs /N-8o6Z... deprecadas (404 desde julio 2026)
        — Nuevo sistema: /Slug/SubCategory/ID-{n}
        — IDs validados empíricamente el 2026-07-21:
          gpu=48, cpu=343, ram=147, ssd=636, hdd=22,
          mobo=22(*), psu=58, cases=7, cooler=574,
          laptops=32, monitores=3, teclados=11,
          mouse=26 (era 13→404), auriculares=219 (era 218→0 items),
          tarjetas_red=22(*)
  [N20] NEWEGG_CATEGORIES: gpu_nvidia y gpu_amd unificados en gpu_all
        — SubCategory/ID-48 retorna todas las GPUs sin filtro de marca
        — El filtro de marca se aplica en _parse_cell() vía _extract_brand()
  [N21] _fetch_page(): URL construida con SubCategory path — sin parámetro N=
  [N22] BASE_PATH separado de query string — más limpio para logging
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
MAX_PAGES        = 10
EMPTY_PAGE_LIMIT = 3
MIN_ITEMS_PAGE   = 2

# [N16] Rango de precio válido en USD
PRICE_MIN_USD = 1.0
PRICE_MAX_USD = 15_000.0

BASE_URL = "https://www.newegg.com"

# ──────────────────────────────────────────────
# [N19] URLs migradas a SubCategory/ID-* (validadas 2026-07-21)
# ──────────────────────────────────────────────
NEWEGG_CATEGORIES = {
    # ── Procesadores ──────────────────────────────────────
    "cpu_intel":      "/CPUs-Processors/SubCategory/ID-343",       # ID-343 ✅
    "cpu_amd":        "/CPUs-Processors/SubCategory/ID-343",       # mismo pool, filtro por brand

    # ── GPUs ──────────────────────────────────────────────
    # [N20] unificado — _extract_brand() separa NVIDIA/AMD post-scrape
    "gpu_all":        "/GPUs-Video-Graphics-Cards/SubCategory/ID-48",  # ID-48 ✅

    # ── Memoria RAM ───────────────────────────────────────
    "ram":            "/Computer-Memory/SubCategory/ID-147",       # ID-147 ✅

    # ── Almacenamiento ────────────────────────────────────
    "ssd":            "/SSDs/SubCategory/ID-636",                  # ID-636 ✅
    "hdd":            "/Hard-Disk-Drives/SubCategory/ID-22",       # ID-22  ✅

    # ── Motherboards ──────────────────────────────────────
    "motherboard":    "/Motherboards/SubCategory/ID-22",           # ID-22  ✅

    # ── PSU / Cases / Cooling ─────────────────────────────
    "psu":            "/Power-Supplies/SubCategory/ID-58",         # ID-58  ✅
    "cases":          "/Computer-Cases/SubCategory/ID-7",          # ID-7   ✅
    "cooler":         "/CPU-Coolers/SubCategory/ID-574",           # ID-574 ✅

    # ── Periféricos ───────────────────────────────────────
    "laptops":        "/Laptops-Notebooks/SubCategory/ID-32",      # ID-32  ✅
    "monitores":      "/Monitors/SubCategory/ID-3",                # ID-3   ✅
    "teclados":       "/Keyboards/SubCategory/ID-11",              # ID-11  ✅
    "mouse":          "/Mice/SubCategory/ID-26",                   # ID-26  ✅ (era ID-13→404)
    "auriculares":    "/Headsets-Headphones/SubCategory/ID-219",   # ID-219 ✅ (era ID-218→0 items)
    "tarjetas_red":   "/Network-Cards/SubCategory/ID-22",          # ID-22  ✅
}

# [N9] Mapeo a categorías normalizadas del pipeline
CAT_NORMALIZE = {
    "cpu_intel":   "CPU",
    "cpu_amd":     "CPU",
    "gpu_all":     "GPU",
    "ram":         "RAM",
    "ssd":         "SSD",
    "hdd":         "HDD",
    "motherboard": "MOTHERBOARD",
    "psu":         "PSU",
    "cases":       "CASE",
    "cooler":      "COOLER",
    "laptops":     "LAPTOP",
    "monitores":   "MONITOR",
    "teclados":    "KEYBOARD",
    "mouse":       "MOUSE",
    "auriculares": "AUDIO",
    "tarjetas_red":"OTHER",
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
# [N18] Zephyrus eliminado — ADATA, PNY, Inno3D agregados
_KNOWN_BRANDS = [
    "Intel", "AMD", "NVIDIA", "ASUS", "MSI", "Gigabyte", "ASRock",
    "Corsair", "G.Skill", "Kingston", "Crucial", "Samsung",
    "Western Digital", "Seagate", "EVGA", "Zotac", "Sapphire",
    "PowerColor", "XFX",
    "be quiet!", "Noctua", "Cooler Master", "NZXT", "Fractal Design",
    "Seasonic", "Thermaltake", "Lian Li", "Phanteks",
    "Dell", "HP", "Lenovo", "Acer", "Razer", "LG",
    "BenQ", "ViewSonic", "AOC", "Logitech", "SteelSeries", "HyperX",
    "SanDisk", "Patriot", "TeamGroup", "Micron", "Toshiba", "HGST",
    "DeepCool", "Thermalright", "Hyte", "Montech",
    "ADATA", "PNY", "Inno3D",
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
# [N21] URL construida con SubCategory path
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

    # [N17] Log INFO cuando no hay celdas — visible en log del batch
    if not cells:
        logger.info(f"  p{page}: 0 celdas encontradas — early-stop")
        return []

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

    # ── Precio actual [N8] ──
    price_el = (
        cell.select_one("li.price-current") or
        cell.select_one(".price-current") or
        cell.select_one("strong.price-current-label")
    )
    price_usd = None
    if price_el:
        price_usd = _parse_price(price_el.get_text(strip=True))

    if not price_usd:
        return None

    # [N16] Validar rango de precio
    if not (PRICE_MIN_USD <= price_usd <= PRICE_MAX_USD):
        logger.debug(
            f"  price_usd={price_usd} fuera de rango "
            f"[{PRICE_MIN_USD}, {PRICE_MAX_USD}] — descartado: {title[:40]}"
        )
        return None

    # ── Precio original ──
    orig_el = (
        cell.select_one(".price-was-data") or
        cell.select_one("span.price-was") or
        cell.select_one("li.price-was")
    )
    price_orig_usd = (
        _parse_price(orig_el.get_text(strip=True)) if orig_el else None
    )

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

    # ── Reviews [N12] ──
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
def scrape_newegg(batch_id: str, mode: str = "normal") -> list:
    """
    Scraper principal Newegg USA — HTML scraping.
    [N14] Parámetro mode — alineado con main.py.
    [N15] Session cerrada en finally — evita TCP huérfanas.
    [N13] Log de tiempo total al finalizar.
    [N19] URLs migradas a SubCategory/ID-* (validadas 2026-07-21).
    """
    t_start          = time.time()
    all_records      = []
    session          = _make_session()
    seen_skus_global = set()   # [N4] dedup global entre categorías

    logger.info(
        f"[Newegg] Iniciando — {len(NEWEGG_CATEGORIES)} categorías"
    )

    try:   # [N15]
        for cat_name, path in NEWEGG_CATEGORIES.items():
            logger.info(f"[Newegg] '{cat_name}' → {path}")
            cat_records = []
            empty_pages = 0

            for page in range(1, MAX_PAGES + 1):
                time.sleep(REQUEST_DELAY + random.uniform(0, 0.8))
                raw_items = _fetch_page(session, path, page)

                if len(raw_items) < MIN_ITEMS_PAGE:
                    empty_pages += 1
                    if empty_pages >= EMPTY_PAGE_LIMIT:
                        logger.info(
                            f"  [{cat_name}] Early-stop p{page} "
                            f"({empty_pages} páginas vacías)"
                        )
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

                    cat_normalized = CAT_NORMALIZE.get(
                        cat_name, cat_name.upper()
                    )

                    record = {
                        "batch_id":       batch_id,
                        "timestamp":      datetime.now(timezone.utc).isoformat(),
                        "source":         "newegg_usa",
                        "category":       cat_normalized,
                        "category_raw":   cat_name,
                        "sku":            sku,
                        "brand":          item.get("brand", ""),
                        "title":          item.get("title", ""),
                        "price_usd":      item.get("price_usd"),
                        "price_orig_usd": item.get("price_orig_usd"),
                        "price_date":     datetime.now(timezone.utc).strftime(
                            "%Y-%m-%d"
                        ),
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
                    f"(cat={len(cat_records)}, "
                    f"global={len(seen_skus_global)})"
                )

                if new_in_page == 0:
                    empty_pages += 1
                    if empty_pages >= EMPTY_PAGE_LIMIT:
                        logger.info(
                            f"  [{cat_name}] Early-stop p{page} "
                            f"(0 nuevos × {empty_pages})"
                        )
                        break

            logger.info(
                f"  ✅ [{cat_name}]: {len(cat_records):,} registros"
            )
            all_records.extend(cat_records)

    finally:
        session.close()   # [N15]

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
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    records  = scrape_newegg(batch_id)
    print(f"\nTotal registros: {len(records):,}")
    if records:
        print("\nEjemplo (primer registro):")
        print(json.dumps(records[0], indent=2, ensure_ascii=False))
