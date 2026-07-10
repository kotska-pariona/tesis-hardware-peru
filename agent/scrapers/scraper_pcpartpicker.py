"""
scraper_pcpartpicker.py
PCPartPicker — Historial de precios USA + precios actuales multi-tienda

Estrategia:
  1. Listado de productos por categoría (JSON interno de PCPartPicker)
  2. Historial de precios por producto (endpoint /api/v0/prices/{part_id})
  3. Comparativa multi-tienda (Amazon, Newegg, BestBuy, etc.)

No requiere API key. Rate limit: 1 req/seg recomendado.
"""

import re
import json
import time
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────
BASE_URL      = "https://pcpartpicker.com"
API_BASE      = f"{BASE_URL}/api/v0"
REQUEST_DELAY = 1.0
TIMEOUT       = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://pcpartpicker.com/",
}

# Categorías de PCPartPicker con sus slugs
CATEGORIES = {
    "cpu":          "/products/cpu/#page=1&s=40",        # sort by reviews
    "video-card":   "/products/video-card/#page=1&s=40",
    "memory":       "/products/memory/#page=1&s=40",
    "internal-hard-drive": "/products/internal-hard-drive/#page=1&s=40",
    "motherboard":  "/products/motherboard/#page=1&s=40",
    "laptop":       "/products/laptop/#page=1&s=40",
    "monitor":      "/products/monitor/#page=1&s=40",
    "case":         "/products/case/#page=1&s=40",
    "power-supply": "/products/power-supply/#page=1&s=40",
    "cpu-cooler":   "/products/cpu-cooler/#page=1&s=40",
}

MAX_PAGES_PER_CATEGORY = 8   # ~20 items/página = 160 productos por categoría


# ──────────────────────────────────────────────
# OBTENER LISTA DE PRODUCTOS POR CATEGORÍA
# ──────────────────────────────────────────────

def _get_products_from_category(category: str, path: str) -> list:
    """
    Extrae la lista de productos de una categoría de PCPartPicker.
    Retorna lista de dicts con {name, url, part_id, price, ratings}.
    """
    products = []
    base_path = path.split("#")[0]

    for page in range(1, MAX_PAGES_PER_CATEGORY + 1):
        url = f"{BASE_URL}{base_path}#page={page}&s=40"
        # PCPartPicker usa JSON en el atributo data-component
        json_url = f"{BASE_URL}{base_path}/fetch?page={page}&s=40"

        try:
            resp = requests.get(json_url, headers=HEADERS, timeout=TIMEOUT)

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    # Intentar extraer de la respuesta JSON
                    html_content = data.get("result", {}).get("html", "")
                    if html_content:
                        soup = BeautifulSoup(html_content, "html.parser")
                    else:
                        soup = BeautifulSoup(resp.text, "html.parser")
                except (json.JSONDecodeError, ValueError):
                    soup = BeautifulSoup(resp.text, "html.parser")
            else:
                # Fallback: scraping HTML directo
                page_url = f"{BASE_URL}{base_path}/?page={page}"
                resp2 = requests.get(page_url, headers=HEADERS, timeout=TIMEOUT)
                resp2.raise_for_status()
                soup = BeautifulSoup(resp2.text, "html.parser")

            # Parsear tabla de productos
            rows = soup.select("tr.tr__product")
            if not rows:
                rows = soup.select("div.productCard")

            if not rows:
                logger.debug(f"  [{category}] Página {page}: sin productos. Fin.")
                break

            for row in rows:
                try:
                    product = _parse_product_row(row, category)
                    if product:
                        products.append(product)
                except Exception as e:
                    logger.debug(f"Error parseando fila: {e}")
                    continue

            logger.debug(f"  [{category}] Página {page}: +{len(rows)} productos")
            time.sleep(REQUEST_DELAY)

        except requests.RequestException as e:
            logger.warning(f"  [{category}] Error en página {page}: {e}")
            time.sleep(2)
            break

    return products


def _parse_product_row(row, category: str) -> Optional[dict]:
    """Parsea una fila/card de producto de PCPartPicker."""
    # Nombre y URL
    name_tag = row.select_one("p.td__name a") or row.select_one(".productCard__title a")
    if not name_tag:
        return None

    name = name_tag.text.strip()
    href = name_tag.get("href", "")
    url  = f"{BASE_URL}{href}" if href.startswith("/") else href

    # Extraer part_id de la URL (/product/XXXXX/...)
    part_id_match = re.search(r"/product/([^/]+)/", href)
    part_id = part_id_match.group(1) if part_id_match else ""

    # Precio
    price_tag = row.select_one("td.td__price a") or row.select_one(".productCard__price")
    price = None
    if price_tag:
        price_text = price_tag.text.strip()
        price_match = re.search(r"[\d,]+\.?\d*", price_text.replace(",", ""))
        if price_match:
            try:
                price = float(price_match.group())
            except ValueError:
                pass

    # Rating
    rating_tag = row.select_one("td.td__rating") or row.select_one(".productCard__rating")
    rating = None
    if rating_tag:
        rating_match = re.search(r"([\d.]+)", rating_tag.text)
        if rating_match:
            try:
                rating = float(rating_match.group(1))
            except ValueError:
                pass

    # Reviews count
    reviews_tag = row.select_one("td.td__reviews")
    reviews = None
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
# OBTENER HISTORIAL DE PRECIOS POR PRODUCTO
# ──────────────────────────────────────────────

def _get_price_history(part_id: str) -> list:
    """
    Obtiene el historial de precios de un producto específico.
    PCPartPicker expone esto en /api/v0/prices/{part_id}
    """
    if not part_id:
        return []

    url = f"{API_BASE}/prices/{part_id}"
    history = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()

        # Estructura: { "prices": { "amazon": [[timestamp, price], ...], ... } }
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
                                    "retailer":   retailer,
                                    "timestamp":  ts,
                                    "date":       datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
                                    "price_usd":  price,
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
    """
    Scraper principal de PCPartPicker.
    Retorna lista de registros con precio actual + historial por retailer.
    """
    all_records = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for category, path in CATEGORIES.items():
        logger.info(f"[PCPartPicker] Categoría: {category}")
        products = _get_products_from_category(category, path)
        logger.info(f"  Productos encontrados: {len(products)}")

        for product in products:
            part_id = product.get("part_id", "")

            # Registro del precio actual
            if product.get("price"):
                all_records.append({
                    "batch_id":      batch_id,
                    "timestamp":     now_iso,
                    "source":        "pcpartpicker_current",
                    "category":      category,
                    "part_id":       part_id,
                    "name":          product["name"],
                    "price_usd":     product["price"],
                    "price_date":    now_iso[:10],
                    "retailer":      "pcpartpicker_best",
                    "rating":        product.get("rating"),
                    "reviews":       product.get("reviews"),
                    "url":           product["url"],
                })

            # Historial de precios (por retailer)
            if part_id:
                history = _get_price_history(part_id)
                for point in history:
                    all_records.append({
                        "batch_id":      batch_id,
                        "timestamp":     now_iso,
                        "source":        "pcpartpicker_history",
                        "category":      category,
                        "part_id":       part_id,
                        "name":          product["name"],
                        "price_usd":     point["price_usd"],
                        "price_date":    point["date"],
                        "retailer":      point["retailer"],
                        "rating":        product.get("rating"),
                        "reviews":       product.get("reviews"),
                        "url":           product["url"],
                    })
                time.sleep(REQUEST_DELAY * 0.5)

        logger.info(
            f"  ✅ {category}: {len(all_records)} registros acumulados"
        )
        time.sleep(REQUEST_DELAY)

    logger.info(f"[PCPartPicker] TOTAL: {len(all_records)} registros")
    return all_records


# ──────────────────────────────────────────────
# EJECUCIÓN STANDALONE
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_batch = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results = scrape_pcpartpicker(test_batch)
    print(f"\nTotal registros: {len(results)}")
    if results:
        print("Ejemplo:", results[0])
