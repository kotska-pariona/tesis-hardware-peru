#!/usr/bin/env python3
# scraper_newegg.py  v2.5  —  rebuilt clean 2026-07-23
"""
Scraper para Newegg.com
Categorías: CPU, GPU, RAM, SSD, Motherboard, PSU, Case, Cooler
Retorna lista de dicts compatibles con el pipeline principal.
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

# ── Configuración ──────────────────────────────────────────────────────────────
REQUEST_DELAY   = 2.5
TIMEOUT         = 20
MAX_PAGES       = 10
EMPTY_PAGE_LIMIT = 3
MIN_ITEMS_PAGE  = 2
PRICE_MIN_USD   = 1.0
PRICE_MAX_USD   = 15000.0
BASE_URL        = "https://www.newegg.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.newegg.com/",
    "Connection": "keep-alive",
    "DNT": "1",
}

# subcategory_id -> (nombre_categoria, slug)
CATEGORIES = {
    "343":  ("CPU",         "Desktop-CPU-Processor"),
    "48":   ("GPU",         "Video-Cards-Video-Devices"),
    "147":  ("RAM",         "Desktop-Memory"),
    "636":  ("SSD",         "Solid-State-Drives"),
    "280":  ("Motherboard", "Motherboards"),
    "58":   ("PSU",         "Power-Supplies"),
    "42":   ("Case",        "Computer-Cases"),
    "574":  ("Cooler",      "CPU-Cooling"),
}


# ── Session ────────────────────────────────────────────────────────────────────
def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    session.headers.update(HEADERS)
    return session


# ── Parseo de precio ───────────────────────────────────────────────────────────
def _parse_price(text: str) -> Optional[float]:
    """Extrae el primer número decimal válido de un string de precio."""
    if not text:
        return None
    # Elimina todo excepto dígitos y punto
    clean = re.sub(r"[^0-9.]", "", text.replace(",", ""))
    # Si hay múltiples puntos, queda solo el primero
    parts = clean.split(".")
    if len(parts) > 2:
        clean = parts[0] + "." + "".join(parts[1:])
    try:
        v = float(clean)
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


# ── Parseo de celda ────────────────────────────────────────────────────────────
def _parse_cell(cell, category_name: str) -> Optional[dict]:
    """
    Extrae título, URL, SKU y precio de un div.item-cell.
    Retorna None si algún campo crítico falta o el precio está fuera de rango.
    """
    try:
        # ── Título ──
        te = (
            cell.select_one("a.item-title")
            or cell.select_one(".item-info a")
            or cell.select_one("a[title]")
        )
        if not te:
            return None
        title = te.get_text(strip=True)
        if not title or len(title) < 5:
            return None

        # ── URL ──
        url = te.get("href", "").strip()
        if not url:
            return None
        if not url.startswith("http"):
            url = BASE_URL + url

        # ── SKU ──
        sku = (
            cell.get("data-item-id", "")
            or cell.get("data-sku", "")
            or ""
        )
        if not sku:
            # Extrae de la URL: .../p/N82E16819113940
            m = re.search(r"/p/([A-Z0-9\-]+)", url)
            if m:
                sku = m.group(1)
        if not sku:
            sku = "newegg_" + hashlib.md5(title.encode()).hexdigest()[:12]

        # ── Precio ──
        pe = (
            cell.select_one("li.price-current")
            or cell.select_one(".price-current")
            or cell.select_one("strong.price-current-label")
        )
        if not pe:
            return None

        price_text = pe.get_text(strip=True)
        price_usd  = _parse_price(price_text)

        if not price_usd:
            return None
        if not (PRICE_MIN_USD <= price_usd <= PRICE_MAX_USD):
            logger.debug(f"  precio fuera de rango: {price_usd} — {title[:50]}")
            return None

        # ── Imagen ──
        img_el = cell.select_one("a.item-img img") or cell.select_one("img")
        image_url = img_el.get("src", "") if img_el else ""

        # ── Rating ──
        rating_el = cell.select_one(".item-rating-num")
        rating_text = rating_el.get_text(strip=True) if rating_el else ""
        rating_m = re.search(r"[\d.]+", rating_text)
        rating = float(rating_m.group()) if rating_m else None

        return {
            "sku":          sku,
            "titulo":       title,
            "precio_usd":   price_usd,
            "categoria":    category_name,
            "tienda":       "Newegg",
            "url":          url,
            "imagen_url":   image_url,
            "rating":       rating,
            "moneda":       "USD",
            "fecha_scrape": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as exc:
        logger.warning(f"  _parse_cell error: {exc}")
        return None


# ── Fetch de página ────────────────────────────────────────────────────────────
def _fetch_page(session: requests.Session, cat_id: str, cat_slug: str, page: int) -> list[dict]:
    """Descarga y parsea una página de listado de Newegg."""
    url = (
        f"{BASE_URL}/{cat_slug}/SubCategory/ID-{cat_id}"
        f"?PageSize=96&Page={page}"
    )
    try:
        resp = session.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning(f"  p{page}: request error — {exc}")
        return []

    soup  = BeautifulSoup(resp.text, "html.parser")
    cells = soup.select("div.item-cell") or soup.select("div.item-container")

    if not cells:
        logger.info(f"  p{page}: 0 celdas — early-stop")
        return []

    logger.info(f"  p{page}: {len(cells)} celdas encontradas")
    items = []
    for cell in cells:
        item = _parse_cell(cell, "")   # categoria se rellena en scrape_category
        if item:
            items.append(item)

    logger.info(f"  p{page}: {len(items)} items válidos")
    return items


# ── Scraper de categoría ───────────────────────────────────────────────────────
def scrape_category(cat_id: str, max_pages: int = MAX_PAGES) -> list[dict]:
    """Scrapea todas las páginas de una categoría y retorna la lista de items."""
    if cat_id not in CATEGORIES:
        logger.error(f"Categoría desconocida: {cat_id}")
        return []

    cat_name, cat_slug = CATEGORIES[cat_id]
    logger.info(f"[Newegg] Iniciando categoría {cat_name} (ID {cat_id})")

    session     = _make_session()
    all_items   = []
    empty_streak = 0

    for page in range(1, max_pages + 1):
        items = _fetch_page(session, cat_id, cat_slug, page)

        # Inyecta nombre de categoría
        for item in items:
            item["categoria"] = cat_name

        if len(items) < MIN_ITEMS_PAGE:
            empty_streak += 1
            logger.info(f"  p{page}: streak vacío {empty_streak}/{EMPTY_PAGE_LIMIT}")
            if empty_streak >= EMPTY_PAGE_LIMIT:
                logger.info(f"  Deteniendo — {EMPTY_PAGE_LIMIT} páginas vacías consecutivas")
                break
        else:
            empty_streak = 0
            all_items.extend(items)

        if page < max_pages:
            delay = REQUEST_DELAY + random.uniform(0.5, 1.5)
            time.sleep(delay)

    logger.info(f"[Newegg] {cat_name}: {len(all_items)} items totales")
    return all_items


# ── Punto de entrada principal ─────────────────────────────────────────────────
def scrape_all(max_pages: int = MAX_PAGES) -> list[dict]:
    """Scrapea todas las categorías configuradas."""
    all_results = []
    for cat_id in CATEGORIES:
        results = scrape_category(cat_id, max_pages=max_pages)
        all_results.extend(results)
        # Pausa entre categorías
        time.sleep(random.uniform(3.0, 6.0))
    logger.info(f"[Newegg] TOTAL: {len(all_results)} items en todas las categorías")
    return all_results


# ── CLI de prueba ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Prueba rápida: solo CPUs, 2 páginas
    results = scrape_category("343", max_pages=2)
    print(f"\n{'='*60}")
    print(f"Items obtenidos: {len(results)}")
    if results:
        print("\nPrimeros 3 items:")
        for item in results[:3]:
            print(f"  SKU   : {item['sku']}")
            print(f"  Título: {item['titulo'][:70]}")
            print(f"  Precio: USD {item['precio_usd']}")
            print(f"  URL   : {item['url'][:60]}")
            print()
    print(json.dumps(results[:2], indent=2, ensure_ascii=False))
