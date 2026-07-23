#!/usr/bin/env python3
"""
scraper_newegg.py  v2.4
Scraper Newegg USA — catálogo completo de hardware
Método: HTML scraping (requests + BeautifulSoup)
Precios: USD (price_usd) — sin conversión a PEN

Fixes v2.4 (sobre v2.3):
  [N23] ID-22 desambiguado:
        hdd        → ID-22  ✅ (era el correcto desde el inicio)
        motherboard→ ID-280 ✅ (validado 2026-07-23: len=939,864)
        tarjetas_red→ID-175 ✅ (validado 2026-07-23: len=163,292)
        — ID-22 era un pool genérico de Newegg usado como fallback
  [N24] cpu_intel / cpu_amd unificados en cpu_all (ID-343)
        — igual que gpu_all [N20]; dedup global maneja duplicados
        — _fetch_page() no aplicaba filtro de marca en URL (bug silencioso)
  [N25] Lógica empty_pages unificada al final del loop
        — elimina doble incremento cuando raw_items>=MIN pero todos dupes
        — un solo punto de decisión: flag `got_new` controla el contador
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
# [N23] URLs corregidas — IDs validados 2026-07-23
# [N24] cpu_all unificado — cpu_intel/cpu_amd eliminados
# ──────────────────────────────────────────────
NEWEGG_CATEGORIES = {
    # ── Procesadores ──────────────────────────────────────
    # [N24] Unificado — dedup global evita duplicados
    "cpu_all":        "/CPUs-Processors/SubCategory/ID-343",       # ID-343 ✅

    # ── GPUs ──────────────────────────────────────────────
    # [N20] Unificado — _extract_brand() separa NVIDIA/AMD post-scrape
    "gpu_all":        "/GPUs-Video-Graphics-Cards/SubCategory/ID-48",  # ID-48 ✅

    # ── Memoria RAM ───────────────────────────────────────
    "ram":            "/Computer-Memory/SubCategory/ID-147",       # ID-147 ✅

    # ── Almacenamiento ────────────────────────────────────
    "ssd":            "/SSDs/SubCategory/ID-636",                  # ID-636 ✅
    "hdd":            "/Hard-Disk-Drives/SubCategory/ID-22",       # ID-22  ✅

    # ── Motherboards ──────────────────────────────────────
    # [N23] Corregido: ID-22 → ID-280 (validado 2026-07-23: len=939,864)
    "motherboard":    "/Motherboards/SubCategory/ID-280",          # ID-280 ✅

    # ── PSU / Cases / Cooling ─────────────────────────────
    "psu":            "/Power-Supplies/SubCategory/ID-58",         # ID-58  ✅
    "cases":          "/Computer-Cases/SubCategory/ID-7",          # ID-7   ✅
    "cooler":         "/CPU-Coolers/SubCategory/ID-574",           # ID-574 ✅

    # ── Periféricos ───────────────────────────────────────
    "laptops":        "/Laptops-Notebooks/SubCategory/ID-32",      # ID-32  ✅
    "monitores":      "/Monitors/SubCategory/ID-3",                # ID-3   ✅
    "teclados":       "/Keyboards/SubCategory/ID-11",              # ID-11  ✅
    "mouse":          "/Mice/SubCategory/ID-26",                   # ID-26  ✅
    "auriculares":    "/Headsets-Headphones/SubCategory/ID-219",   # ID-219 ✅

    # ── Redes ─────────────────────────────────────────────
    # [N23] Corregido: ID-22 → ID-175 (validado 2026-07-23: len=163,292)
    "tarjetas_red":   "/Network-Cards/SubCategory/ID-175",         # ID-175 ✅
}

# [N9] Mapeo a categorías normalizadas del pipeline
CAT_NORMALIZE = {
    "cpu_all":     "CPU",
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
        sku = "newegg_" + hashlib.md5(title.encode()).hexdigest()[:12]

    # ── Precio actual ──
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

    # ── Reviews ──
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
    [N23] IDs corregidos: mobo→ID-280, tarjetas_red→ID-175.
    [N24] cpu_all unificado — cpu_intel/cpu_amd eliminados.
    [N25] empty_pages: lógica unificada con flag got_new.
    """
    t_start          = time.time()
    all_records      = []
    session          = _make_session()
    seen_skus_global = set()

    logger.info(
        f"[Newegg] Iniciando v2.4 — {len(NEWEGG_CATEGORIES)} categorías"
    )

    try:
        for cat_name, path in NEWEGG_CATEGORIES.items():
            logger.info(f"[Newegg] '{cat_name}' → {path}")
            cat_records = []
            empty_pages = 0   # [N25] único contador

            for page in range(1, MAX_PAGES + 1):
                time.sleep(REQUEST_DELAY + random.uniform(0, 0.8))
                raw_items = _fetch_page(session, path, page)

                # [N25] got_new: flag unificado para controlar empty_pages
                got_new = False

                if len(raw_items) >= MIN_ITEMS_PAGE:
                    new_in_page = 0
                    for item in raw_items:
                        sku = item.get("sku", "")
                        if sku in seen_skus_global:
                            continue
                        seen_skus_global.add(sku)
                        new_in_page += 1
                        got_new = True

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

                    logger.info(
                        f"  [{cat_name}] p{page}: "
                        f"+{len(raw_items)} raw → +{new_in_page} nuevos "
                        f"(cat={len(cat_records)}, "
                        f"global={len(seen_skus_global)})"
                    )
                else:
                    logger.debug(
                        f"  [{cat_name}] p{page}: "
                        f"{len(raw_items)} items < MIN({MIN_ITEMS_PAGE})"
                    )

                # [N25] Un solo punto de control para empty_pages
                if got_new:
                    empty_pages = 0
                else:
                    empty_pages += 1
                    logger.info(
                        f"  [{cat_name}] p{page}: sin nuevos "
                        f"(empty_pages={empty_pages}/{EMPTY_PAGE_LIMIT})"
                    )
                    if empty_pages >= EMPTY_PAGE_LIMIT:
                        logger.info(
                            f"  [{cat_name}] Early-stop p{page}"
                        )
                        break

            logger.info(
                f"  ✅ [{cat_name}]: {len(cat_records):,} registros"
            )
            all_records.extend(cat_records)

    finally:
        session.close()

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
