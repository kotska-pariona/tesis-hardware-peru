#!/usr/bin/env python3
"""
scraper_pcpartpicker.py  v3.0
PCPartPicker — Precios actuales multi-tienda + historial USA

Fixes v3.0 (sobre v2.0):
  - [P1] _make_session() agregado — Session + Retry para todas las requests
         (era requests.get() directo sin retry — único scraper del proyecto sin Session)
  - [P2] _get_price_history: detecta Cloudflare en respuesta 200 con HTML
  - [P3] UA rotativo via fake_useragent — consistente con scrapers v3.0+
  - [P4] __main__: datetime.now(timezone.utc)
"""

import re
import json
import time
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
BASE_URL      = "https://pcpartpicker.com"
API_BASE      = f"{BASE_URL}/api/v0"
REQUEST_DELAY = 1.5
TIMEOUT       = 20
MAX_PAGES_PER_CATEGORY = 5

# [P3] UA rotativo — consistente con scraper_camel v3.0 y scraper_local v3.5
try:
    from fake_useragent import UserAgent as _UA
    _ua_gen = _UA()
except ImportError:
    _ua_gen = None

_UA_FALLBACK = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

def _get_ua() -> str:
    return _ua_gen.random if _ua_gen else _UA_FALLBACK

def _make_headers() -> dict:
    return {
        "User-Agent":      _get_ua(),
        "Accept":          "application/json, text/html, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         "https://pcpartpicker.com/",
    }

CATEGORIES = {
    "cpu":                 "/products/cpu/",
    "video-card":          "/products/video-card/",
    "memory":              "/products/memory/",
    "internal-hard-drive": "/products/internal-hard-drive/",
    "motherboard":         "/products/motherboard/",
    "laptop":              "/products/laptop/",
    "monitor":             "/products/monitor/",
    "case":                "/products/case/",
    "power-supply":        "/products/power-supply/",
    "cpu-cooler":          "/products/cpu-cooler/",
}


# ──────────────────────────────────────────────
# [P1] Session con Retry — igual que todos los scrapers del proyecto
# ──────────────────────────────────────────────
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


# ──────────────────────────────────────────────
# Detección de Cloudflare
# ──────────────────────────────────────────────
def _is_cloudflare_block(resp: requests.Response) -> bool:
    """
    Detecta challenge de Cloudflare.
    [P2] También detecta cuando status=200 pero el body es HTML de Cloudflare.
    """
    content = resp.text.lower()
    return any(k in content for k in [
        "cloudflare", "cf-ray", "just a moment", "checking your browser"
    ])


# ──────────────────────────────────────────────
# LISTA DE PRODUCTOS POR CATEGORÍA
# ──────────────────────────────────────────────
def _get_products_from_category(
    session: requests.Session, category: str, base_path: str
) -> list:
    """
    [P1] Recibe session como parámetro — usa session.get() en lugar de requests.get().
    """
    products  = []
    base_path = base_path.rstrip("/")

    for page in range(1, MAX_PAGES_PER_CATEGORY + 1):
        fetch_url = f"{BASE_URL}{base_path}/fetch?page={page}&s=40"
        page_url  = f"{BASE_URL}{base_path}/?page={page}"
        soup      = None

        try:
            resp = session.get(fetch_url, headers=_make_headers(), timeout=TIMEOUT)

            # Cloudflare en cualquier status (incluido 200)
            if _is_cloudflare_block(resp):
                logger.warning(
                    f"  [{category}] Cloudflare block p{page} "
                    f"— esperando {REQUEST_DELAY * 3:.0f}s"
                )
                time.sleep(REQUEST_DELAY * 3)
                break

            if resp.status_code == 200:
                try:
                    data         = resp.json()
                    html_content = data.get("result", {}).get("html", "")
                    soup = BeautifulSoup(
                        html_content if html_content else resp.text,
                        "html.parser"
                    )
                except (json.JSONDecodeError, ValueError):
                    soup = BeautifulSoup(resp.text, "html.parser")
            else:
                # Fallback: HTML directo
                resp2 = session.get(page_url, headers=_make_headers(), timeout=TIMEOUT)
                if _is_cloudflare_block(resp2):
                    logger.warning(f"  [{category}] Cloudflare block (fallback)")
                    break
                resp2.raise_for_status()
                soup = BeautifulSoup(resp2.text, "html.parser")

        except requests.RequestException as e:
            logger.warning(f"  [{category}] Error p{page}: {e}")
            time.sleep(2)
            break

        if soup is None:
            break

        rows = (
            soup.select("tr.tr__product") or
            soup.select("div.productCard") or
            soup.select("li.product__wrap")
        )

        if not rows:
            if page == 1:
                logger.warning(
                    f"  [{category}] Página 1 sin productos — "
                    f"¿selector CSS cambió? Probados: "
                    f"tr.tr__product, div.productCard, li.product__wrap"
                )
            else:
                logger.debug(f"  [{category}] p{page}: sin productos. Fin.")
            break

        for row in rows:
            try:
                product = _parse_product_row(row, category)
                if product:
                    products.append(product)
            except Exception as e:
                logger.debug(f"Error parseando fila: {e}")
                continue

        logger.debug(f"  [{category}] p{page}: +{len(rows)} productos")
        time.sleep(REQUEST_DELAY)

    return products


def _parse_product_row(row, category: str) -> Optional[dict]:
    name_tag = (
        row.select_one("p.td__name a") or
        row.select_one(".productCard__title a") or
        row.select_one("p.td__title a")
    )
    if not name_tag:
        return None

    name = name_tag.text.strip()
    href = name_tag.get("href", "")
    url  = f"{BASE_URL}{href}" if href.startswith("/") else href

    part_id_match = re.search(r"/product/([^/]+)/", href)
    part_id       = part_id_match.group(1) if part_id_match else ""

    price     = None
    price_tag = (
        row.select_one("td.td__price a") or
        row.select_one(".productCard__price") or
        row.select_one("td.td__finalPrice")
    )
    if price_tag:
        price_text  = price_tag.text.strip().replace(",", "")
        price_match = re.search(r"\d+\.?\d*", price_text)
        if price_match:
            try:
                price = float(price_match.group())
            except ValueError:
                pass

    rating     = None
    rating_tag = (
        row.select_one("td.td__rating") or
        row.select_one(".productCard__rating")
    )
    if rating_tag:
        rating_match = re.search(r"([\d.]+)", rating_tag.text)
        if rating_match:
            try:
                rating = float(rating_match.group(1))
            except ValueError:
                pass

    reviews     = None
    reviews_tag = row.select_one("td.td__reviews")
    if reviews_tag:
        reviews_match = re.search(r"(\d+)", reviews_tag.text.replace(",", ""))
        if reviews_match:
            try:
                reviews = int(reviews_match.group(1))
            except ValueError:
                pass

    return {
        "name":     name,
        "url":      url,
        "part_id":  part_id,
        "category": category,
        "price":    price,
        "rating":   rating,
        "reviews":  reviews,
    }


# ──────────────────────────────────────────────
# HISTORIAL DE PRECIOS
# ──────────────────────────────────────────────
def _get_price_history(session: requests.Session, part_id: str) -> list:
    """
    [P1] Recibe session — usa session.get() en lugar de requests.get().
    [P2] Detecta Cloudflare en respuesta 200 con HTML.
    NOTA: /api/v0/prices/ no es API pública documentada — puede cambiar.
    """
    if not part_id:
        return []

    url     = f"{API_BASE}/prices/{part_id}"
    history = []

    try:
        resp = session.get(url, headers=_make_headers(), timeout=TIMEOUT)

        if resp.status_code == 404:
            return []
        if resp.status_code in (401, 403):
            logger.warning(
                f"  [PCPartPicker] API /api/v0/prices/ → {resp.status_code} "
                f"para {part_id} — puede requerir autenticación"
            )
            return []
        if resp.status_code >= 500:
            logger.warning(
                f"  [PCPartPicker] API error {resp.status_code} para {part_id}"
            )
            return []

        # [P2] Detectar Cloudflare aunque status=200
        if _is_cloudflare_block(resp):
            logger.warning(
                f"  [PCPartPicker] Cloudflare en historial {part_id} "
                f"(status={resp.status_code}) — historial no disponible"
            )
            return []

        resp.raise_for_status()
        data        = resp.json()
        prices_data = data.get("prices", {})

        for retailer, price_points in prices_data.items():
            if isinstance(price_points, list):
                for point in price_points:
                    if isinstance(point, (list, tuple)) and len(point) >= 2:
                        try:
                            ts    = int(point[0])
                            price = float(point[1])
                            if price > 0:
                                history.append({
                                    "retailer":  retailer,
                                    "timestamp": ts,
                                    "date":      datetime.fromtimestamp(
                                        ts, tz=timezone.utc
                                    ).strftime("%Y-%m-%d"),
                                    "price_usd": price,
                                })
                        except (ValueError, TypeError):
                            continue

    except requests.RequestException as e:
        logger.debug(f"  [PCPartPicker] Error historial {part_id}: {e}")
    except (json.JSONDecodeError, KeyError) as e:
        logger.debug(f"  [PCPartPicker] Error JSON {part_id}: {e}")

    return history


# ──────────────────────────────────────────────
# SCRAPER PRINCIPAL
# ──────────────────────────────────────────────
def scrape_pcpartpicker(batch_id: str) -> list:
    all_records   = []
    seen_part_ids = set()
    now_iso       = datetime.now(timezone.utc).isoformat()
    # [P1] Session única para todo el scraper
    session       = _make_session()

    for category, path in CATEGORIES.items():
        logger.info(f"[PCPartPicker] Categoría: {category}")
        cat_records_before = len(all_records)

        # [P1] Pasar session a las funciones
        products = _get_products_from_category(session, category, path)
        logger.info(f"  Productos encontrados: {len(products)}")

        for product in products:
            part_id = product.get("part_id", "")

            if product.get("price"):
                all_records.append({
                    "batch_id":   batch_id,
                    "timestamp":  now_iso,
                    "source":     "pcpartpicker_current",
                    "category":   category,
                    "part_id":    part_id,
                    "name":       product["name"],
                    "price_usd":  product["price"],
                    "price_date": now_iso[:10],
                    "retailer":   "pcpartpicker_best",
                    "rating":     product.get("rating"),
                    "reviews":    product.get("reviews"),
                    "url":        product["url"],
                })

            if part_id and part_id not in seen_part_ids:
                seen_part_ids.add(part_id)
                # [P1] Pasar session al historial
                history = _get_price_history(session, part_id)
                for point in history:
                    all_records.append({
                        "batch_id":   batch_id,
                        "timestamp":  now_iso,
                        "source":     "pcpartpicker_history",
                        "category":   category,
                        "part_id":    part_id,
                        "name":       product["name"],
                        "price_usd":  point["price_usd"],
                        "price_date": point["date"],
                        "retailer":   point["retailer"],
                        "rating":     product.get("rating"),
                        "reviews":    product.get("reviews"),
                        "url":        product["url"],
                    })
                time.sleep(REQUEST_DELAY * 0.5)
            elif part_id in seen_part_ids:
                logger.debug(f"  part_id {part_id} ya procesado — skip historial")

        cat_records_added = len(all_records) - cat_records_before
        logger.info(f"  ✅ {category}: +{cat_records_added} registros")
        time.sleep(REQUEST_DELAY)

    logger.info(f"[PCPartPicker] TOTAL: {len(all_records)} registros")
    return all_records


# ──────────────────────────────────────────────
# STANDALONE
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # [P4] datetime con timezone explícita
    test_batch = f"test_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    results    = scrape_pcpartpicker(test_batch)
    print(f"\nTotal registros: {len(results)}")
    if results:
        print("Ejemplo:", results[0])
