"""
scraper_pcpartpicker.py  v2.0
PCPartPicker — Precios actuales multi-tienda + historial USA

Fixes v2.0:
  - [FIX-1] /api/v0/prices/: log de warning para 403/401/500 (no solo 404)
  - [FIX-2] URL fallback normalizada con rstrip('/') — evita doble slash
  - [FIX-3] Variable 'url' muerta eliminada del loop
  - [FIX-4] CATEGORIES: paths sin fragment # — limpieza explícita
  - [FIX-5] REQUEST_DELAY aumentado a 1.5s + detección de Cloudflare
  - [FIX-6] MAX_PAGES_PER_CATEGORY reducido a 5 (era 8)
  - [FIX-7] Deduplicación de part_id — evita historial duplicado
  - [FIX-8] Log por categoría corregido (registros de la cat, no acumulado)
  - [FIX-9] Warning cuando rows=[] en página 1
  - [FIX-10] Regex de precio simplificado
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
REQUEST_DELAY = 1.5    # FIX-5: aumentado de 1.0 → 1.5s
TIMEOUT       = 20

# FIX-6: reducido de 8 → 5 páginas (~100 productos/categoría)
MAX_PAGES_PER_CATEGORY = 5

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

# FIX-4: paths sin fragment # — solo la ruta base
CATEGORIES = {
    "cpu":                   "/products/cpu/",
    "video-card":            "/products/video-card/",
    "memory":                "/products/memory/",
    "internal-hard-drive":   "/products/internal-hard-drive/",
    "motherboard":           "/products/motherboard/",
    "laptop":                "/products/laptop/",
    "monitor":               "/products/monitor/",
    "case":                  "/products/case/",
    "power-supply":          "/products/power-supply/",
    "cpu-cooler":            "/products/cpu-cooler/",
}


# ──────────────────────────────────────────────
# FIX-5: Detección de Cloudflare
# ──────────────────────────────────────────────

def _is_cloudflare_block(resp: requests.Response) -> bool:
    """Detecta si la respuesta es una página de challenge de Cloudflare."""
    if resp.status_code in (403, 503):
        content = resp.text.lower()
        return any(k in content for k in [
            "cloudflare", "cf-ray", "just a moment", "checking your browser"
        ])
    return False


# ──────────────────────────────────────────────
# OBTENER LISTA DE PRODUCTOS POR CATEGORÍA
# ──────────────────────────────────────────────

def _get_products_from_category(category: str, base_path: str) -> list:
    """
    Extrae la lista de productos de una categoría de PCPartPicker.
    FIX-2: URL normalizada. FIX-3: variable 'url' muerta eliminada.
    FIX-9: warning cuando rows=[] en página 1.
    """
    products  = []
    # FIX-2: normalizar path — eliminar slash final para evitar doble slash
    base_path = base_path.rstrip("/")

    for page in range(1, MAX_PAGES_PER_CATEGORY + 1):
        # FIX-2: URL limpia sin doble slash
        fetch_url = f"{BASE_URL}{base_path}/fetch?page={page}&s=40"
        page_url  = f"{BASE_URL}{base_path}/?page={page}"

        soup = None
        try:
            resp = requests.get(fetch_url, headers=HEADERS, timeout=TIMEOUT)

            # FIX-5: Detectar Cloudflare
            if _is_cloudflare_block(resp):
                logger.warning(
                    f"  [{category}] Cloudflare block en página {page} "
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
                # Fallback: HTML directo con URL limpia
                resp2 = requests.get(page_url, headers=HEADERS, timeout=TIMEOUT)
                if _is_cloudflare_block(resp2):
                    logger.warning(f"  [{category}] Cloudflare block (fallback)")
                    break
                resp2.raise_for_status()
                soup = BeautifulSoup(resp2.text, "html.parser")

        except requests.RequestException as e:
            logger.warning(f"  [{category}] Error en página {page}: {e}")
            time.sleep(2)
            break

        if soup is None:
            break

        # Parsear filas de productos
        rows = (
            soup.select("tr.tr__product") or
            soup.select("div.productCard") or
            soup.select("li.product__wrap")
        )

        # FIX-9: Warning si página 1 no tiene productos
        if not rows:
            if page == 1:
                logger.warning(
                    f"  [{category}] Página 1 sin productos — "
                    f"¿selector CSS cambió? Selectores probados: "
                    f"tr.tr__product, div.productCard, li.product__wrap"
                )
            else:
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

    return products


def _parse_product_row(row, category: str) -> Optional[dict]:
    """
    Parsea una fila/card de producto de PCPartPicker.
    FIX-10: regex de precio simplificado.
    """
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

    # Extraer part_id de la URL
    part_id_match = re.search(r"/product/([^/]+)/", href)
    part_id = part_id_match.group(1) if part_id_match else ""

    # FIX-10: regex simplificado — coma ya eliminada antes
    price = None
    price_tag = (
        row.select_one("td.td__price a") or
        row.select_one(".productCard__price") or
        row.select_one("td.td__finalPrice")
    )
    if price_tag:
        price_text  = price_tag.text.strip().replace(",", "")
        price_match = re.search(r"\d+\.?\d*", price_text)   # FIX-10: sin coma
        if price_match:
            try:
                price = float(price_match.group())
            except ValueError:
                pass

    # Rating
    rating = None
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

    # Reviews
    reviews = None
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
# OBTENER HISTORIAL DE PRECIOS
# ──────────────────────────────────────────────

def _get_price_history(part_id: str) -> list:
    """
    Obtiene historial de precios de un producto.
    NOTA: /api/v0/prices/ no es una API pública documentada.
    FIX-1: log de warning para códigos != 200 y != 404.
    """
    if not part_id:
        return []

    url     = f"{API_BASE}/prices/{part_id}"
    history = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)

        # FIX-1: Manejar todos los códigos de error, no solo 404
        if resp.status_code == 404:
            return []
        if resp.status_code in (401, 403):
            logger.warning(
                f"  [PCPartPicker] API /api/v0/prices/ retornó {resp.status_code} "
                f"para {part_id} — endpoint puede requerir autenticación"
            )
            return []
        if resp.status_code >= 500:
            logger.warning(
                f"  [PCPartPicker] API error {resp.status_code} para {part_id}"
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
    """
    Scraper principal de PCPartPicker.
    FIX-7: Deduplicación de part_id.
    FIX-8: Log por categoría corregido.
    """
    all_records  = []
    seen_part_ids = set()   # FIX-7
    now_iso      = datetime.now(timezone.utc).isoformat()

    for category, path in CATEGORIES.items():
        logger.info(f"[PCPartPicker] Categoría: {category}")
        cat_records_before = len(all_records)   # FIX-8

        products = _get_products_from_category(category, path)
        logger.info(f"  Productos encontrados: {len(products)}")

        for product in products:
            part_id = product.get("part_id", "")

            # Precio actual
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

            # FIX-7: Historial solo si part_id no fue procesado antes
            if part_id and part_id not in seen_part_ids:
                seen_part_ids.add(part_id)
                history = _get_price_history(part_id)
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
                logger.debug(f"  [PCPartPicker] part_id {part_id} ya procesado — skip historial")

        # FIX-8: Log con registros de ESTA categoría, no el acumulado global
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
    test_batch = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results    = scrape_pcpartpicker(test_batch)
    print(f"\nTotal registros: {len(results)}")
    if results:
        print("Ejemplo:", results[0])
