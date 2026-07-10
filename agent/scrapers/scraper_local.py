"""
scraper_local.py
Scraper de tiendas locales Perú — Falabella, Ripley, Hiraoka

Estrategia:
  - Falabella : API interna JSON /s/browse/v1/listing/pe  (~24 items/página)
  - Ripley    : API interna JSON /api/search              (~40 items/página)
  - Hiraoka   : HTML + paginación real                    (~24 items/página)

No requiere credenciales.
"""

import re
import time
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CONFIGURACIÓN GLOBAL
# ──────────────────────────────────────────────
REQUEST_DELAY = 0.8
TIMEOUT       = 20

HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
    "Accept":          "application/json, text/html, */*;q=0.8",
}


# ══════════════════════════════════════════════
# FALABELLA — API JSON interna
# ══════════════════════════════════════════════

FALABELLA_API = "https://www.falabella.com.pe/s/browse/v1/listing/pe"

FALABELLA_CATEGORIES = {
    "laptops":           "cat40062",
    "computadoras":      "cat40063",
    "procesadores":      "cat40064",
    "tarjetas_video":    "cat40065",
    "monitores":         "cat40066",
    "memorias_ram":      "cat40067",
    "discos_duros":      "cat40068",
    "teclados":          "cat40069",
    "mouse":             "cat40070",
    "impresoras":        "cat40071",
    "tablets":           "cat40072",
    "celulares":         "cat10001",
    "televisores":       "cat10002",
    "auriculares":       "cat10003",
    "camaras":           "cat10004",
}

FALABELLA_MAX_PAGES = 50   # 50 × 24 = 1,200 items por categoría


def _falabella_fetch_page(category_id: str, page: int) -> list:
    """Llama a la API JSON de Falabella y retorna lista de productos crudos."""
    params = {
        "categoryId": category_id,
        "page":       page,
        "pageSize":   24,
        "sortBy":     "TOP_SELLERS",
        "zones":      "15",          # Lima
        "channel":    "web",
        "locale":     "es_PE",
        "country":    "PE",
    }
    headers = {
        **HEADERS_BROWSER,
        "Referer": "https://www.falabella.com.pe/",
    }
    try:
        resp = requests.get(
            FALABELLA_API, params=params, headers=headers, timeout=TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()
        return (
            data
            .get("data", {})
            .get("results", [])
        )
    except requests.RequestException as e:
        logger.warning(f"  [Falabella] Error página {page} cat {category_id}: {e}")
        return []
    except (ValueError, KeyError) as e:
        logger.warning(f"  [Falabella] Error JSON página {page}: {e}")
        return []


def _falabella_parse(raw: dict, category: str, batch_id: str) -> Optional[dict]:
    """Normaliza un producto crudo de Falabella."""
    try:
        # Precios
        prices     = raw.get("prices", [{}])
        price_info = prices[0] if prices else {}
        price      = price_info.get("originalPrice") or price_info.get("price")
        price_sale = price_info.get("specialPrice") or price_info.get("salePrice")

        if not price and not price_sale:
            return None

        final_price = float(price_sale or price)
        if final_price <= 0:
            return None

        # Marca y nombre
        brand = raw.get("brand", "")
        name  = raw.get("displayName", raw.get("name", ""))

        return {
            "batch_id":     batch_id,
            "timestamp":    datetime.now(timezone.utc).isoformat(),
            "source":       "falabella_pe",
            "category":     category,
            "sku":          str(raw.get("skuId", raw.get("id", ""))),
            "brand":        brand,
            "title":        f"{brand} {name}".strip(),
            "price_pen":    final_price,
            "price_orig_pen": float(price) if price else final_price,
            "discount_pct": round(
                (1 - final_price / float(price)) * 100, 1
            ) if price and float(price) > 0 else 0,
            "rating":       raw.get("rating"),
            "reviews":      raw.get("totalReviews", raw.get("reviewCount")),
            "url": (
                "https://www.falabella.com.pe"
                + raw.get("url", "")
            ),
        }
    except (TypeError, ValueError, KeyError, ZeroDivisionError) as e:
        logger.debug(f"  [Falabella] Error parseando producto: {e}")
        return None


def scrape_falabella(batch_id: str) -> list:
    """Scraper principal de Falabella PE."""
    all_records = []

    for cat_name, cat_id in FALABELLA_CATEGORIES.items():
        logger.info(f"[Falabella] Categoría: {cat_name} ({cat_id})")
        cat_records = []

        for page in range(1, FALABELLA_MAX_PAGES + 1):
            raw_items = _falabella_fetch_page(cat_id, page)

            if not raw_items:
                logger.debug(f"  Página {page}: sin items. Fin.")
                break

            for raw in raw_items:
                record = _falabella_parse(raw, cat_name, batch_id)
                if record:
                    cat_records.append(record)

            logger.debug(f"  Página {page}: +{len(raw_items)} items")
            time.sleep(REQUEST_DELAY)

        all_records.extend(cat_records)
        logger.info(f"  ✅ {cat_name}: {len(cat_records)} registros")

    logger.info(f"[Falabella] TOTAL: {len(all_records)} registros")
    return all_records


# ══════════════════════════════════════════════
# RIPLEY — API JSON interna
# ══════════════════════════════════════════════

RIPLEY_API = "https://simple.ripley.com.pe/api/search"

RIPLEY_QUERIES = [
    "laptop",
    "computadora desktop",
    "procesador intel",
    "procesador amd",
    "tarjeta de video nvidia",
    "tarjeta de video amd",
    "memoria ram ddr4",
    "memoria ram ddr5",
    "disco duro ssd",
    "disco duro nvme",
    "monitor gaming",
    "monitor 4k",
    "teclado mecanico",
    "mouse gaming",
    "tablet",
    "celular samsung",
    "celular xiaomi",
    "impresora",
    "auriculares bluetooth",
    "camara fotografica",
]

RIPLEY_MAX_PAGES = 10   # 10 × 40 = 400 items por query


def _ripley_fetch_page(query: str, page: int) -> dict:
    """Llama a la API de búsqueda de Ripley."""
    params = {
        "q":        query,
        "page":     page,
        "pageSize": 40,
        "country":  "PE",
        "channel":  "ripley",
    }
    headers = {
        **HEADERS_BROWSER,
        "Referer": "https://simple.ripley.com.pe/",
        "Origin":  "https://simple.ripley.com.pe",
    }
    try:
        resp = requests.get(
            RIPLEY_API, params=params, headers=headers, timeout=TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.warning(f"  [Ripley] Error página {page} query '{query}': {e}")
        return {}
    except ValueError as e:
        logger.warning(f"  [Ripley] Error JSON: {e}")
        return {}


def _ripley_parse(raw: dict, query: str, batch_id: str) -> Optional[dict]:
    """Normaliza un producto crudo de Ripley."""
    try:
        # Precio
        price_info = raw.get("prices", {})
        price      = (
            price_info.get("normalPrice")
            or price_info.get("offerPrice")
            or raw.get("price")
        )
        price_offer = price_info.get("offerPrice") or price_info.get("salePrice")

        if not price:
            return None

        final_price = float(price_offer or price)
        if final_price <= 0:
            return None

        brand = raw.get("brand", "")
        name  = raw.get("displayName", raw.get("name", ""))
        slug  = raw.get("slug", raw.get("url", ""))

        return {
            "batch_id":       batch_id,
            "timestamp":      datetime.now(timezone.utc).isoformat(),
            "source":         "ripley_pe",
            "category":       query,
            "sku":            str(raw.get("partNumber", raw.get("id", ""))),
            "brand":          brand,
            "title":          f"{brand} {name}".strip(),
            "price_pen":      final_price,
            "price_orig_pen": float(price),
            "discount_pct":   round(
                (1 - final_price / float(price)) * 100, 1
            ) if float(price) > 0 else 0,
            "rating":         raw.get("rating", {}).get("average") if isinstance(raw.get("rating"), dict) else raw.get("rating"),
            "reviews":        raw.get("rating", {}).get("count") if isinstance(raw.get("rating"), dict) else None,
            "url": (
                f"https://simple.ripley.com.pe/{slug}"
                if not slug.startswith("http") else slug
            ),
        }
    except (TypeError, ValueError, KeyError, ZeroDivisionError) as e:
        logger.debug(f"  [Ripley] Error parseando producto: {e}")
        return None


def scrape_ripley(batch_id: str) -> list:
    """Scraper principal de Ripley PE."""
    all_records = []

    for query in RIPLEY_QUERIES:
        logger.info(f"[Ripley] Query: '{query}'")
        query_records = []

        for page in range(1, RIPLEY_MAX_PAGES + 1):
            data      = _ripley_fetch_page(query, page)
            raw_items = (
                data.get("products", [])
                or data.get("results", [])
                or data.get("items", [])
            )
            total = data.get("total", data.get("totalCount", 0))

            if not raw_items:
                break

            for raw in raw_items:
                record = _ripley_parse(raw, query, batch_id)
                if record:
                    query_records.append(record)

            logger.debug(f"  Página {page}: +{len(raw_items)} (total: {total})")

            if len(query_records) >= total:
                break

            time.sleep(REQUEST_DELAY)

        all_records.extend(query_records)
        logger.info(f"  ✅ '{query}': {len(query_records)} registros")

    logger.info(f"[Ripley] TOTAL: {len(all_records)} registros")
    return all_records


# ══════════════════════════════════════════════
# HIRAOKA — HTML scraping con paginación real
# ══════════════════════════════════════════════

HIRAOKA_BASE = "https://www.hiraoka.com.pe"

HIRAOKA_CATEGORIES = {
    "laptops":        "/laptops-y-accesorios/laptops",
    "computadoras":   "/laptops-y-accesorios/computadoras-de-escritorio",
    "monitores":      "/laptops-y-accesorios/monitores",
    "impresoras":     "/impresoras-y-accesorios/impresoras",
    "tablets":        "/celulares-y-tablets/tablets",
    "celulares":      "/celulares-y-tablets/celulares",
    "televisores":    "/television-y-video/televisores",
    "auriculares":    "/audio/audifonos",
    "camaras":        "/camaras-y-accesorios/camaras-digitales",
    "videojuegos":    "/videojuegos/consolas",
}

HIRAOKA_MAX_PAGES = 30   # 30 × 24 = 720 items por categoría


def _hiraoka_fetch_page(category: str, path: str, page: int) -> list:
    """Descarga y parsea una página de categoría de Hiraoka."""
    # URL con paginación real: ?p=2, ?p=3, etc.
    url = f"{HIRAOKA_BASE}{path}?p={page}"
    headers = {
        **HEADERS_BROWSER,
        "Referer": f"{HIRAOKA_BASE}{path}",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Detectar si llegamos a una página vacía
        no_results = soup.find("div", class_="message empty")
        if no_results:
            return []

        # Selector principal de productos
        products = (
            soup.select("li.product-item")
            or soup.select("div.product-item-info")
            or soup.select("article.product-item")
        )
        return products

    except requests.RequestException as e:
        logger.warning(f"  [Hiraoka] Error página {page} {category}: {e}")
        return []


def _hiraoka_parse(item, category: str, batch_id: str) -> Optional[dict]:
    """Parsea un elemento de producto de Hiraoka."""
    try:
        # Nombre
        name_tag = (
            item.select_one("a.product-item-link")
            or item.select_one(".product-item-name a")
            or item.select_one("strong.product-item-name a")
        )
        if not name_tag:
            return None
        title = name_tag.get_text(strip=True)
        url   = name_tag.get("href", "")

        # Precio especial (oferta)
        price_special = item.select_one(
            "span.price-wrapper[data-price-type='finalPrice'] span.price"
            ", .special-price .price"
        )
        # Precio regular
        price_regular = item.select_one(
            "span.price-wrapper[data-price-type='regularPrice'] span.price"
            ", .old-price .price"
            ", .regular-price .price"
        )

        def clean_price(tag) -> Optional[float]:
            if not tag:
                return None
            text = tag.get_text(strip=True)
            text = re.sub(r"[^\d.,]", "", text).replace(",", "")
            try:
                return float(text) if text else None
            except ValueError:
                return None

        final_price = clean_price(price_special) or clean_price(price_regular)
        orig_price  = clean_price(price_regular) or final_price

        if not final_price or final_price <= 0:
            return None

        # Rating
        rating_tag = item.select_one(".rating-result") or item.select_one(".rating-summary")
        rating = None
        if rating_tag:
            style = rating_tag.get("style", "")
            pct_match = re.search(r"width:\s*([\d.]+)%", style)
            if pct_match:
                rating = round(float(pct_match.group(1)) / 20, 1)  # % → escala 5

        # SKU desde data attributes
        sku = (
            item.get("data-product-id", "")
            or item.select_one("[data-product-id]", {}).get("data-product-id", "")
            if item.select_one("[data-product-id]") else ""
        )

        return {
            "batch_id":       batch_id,
            "timestamp":      datetime.now(timezone.utc).isoformat(),
            "source":         "hiraoka_pe",
            "category":       category,
            "sku":            str(sku),
            "brand":          "",   # Hiraoka no expone brand en listing
            "title":          title,
            "price_pen":      final_price,
            "price_orig_pen": orig_price,
            "discount_pct":   round(
                (1 - final_price / orig_price) * 100, 1
            ) if orig_price and orig_price > 0 else 0,
            "rating":         rating,
            "reviews":        None,
            "url":            url if url.startswith("http") else f"{HIRAOKA_BASE}{url}",
        }
    except (TypeError, ValueError, AttributeError, ZeroDivisionError) as e:
        logger.debug(f"  [Hiraoka] Error parseando item: {e}")
        return None


def scrape_hiraoka(batch_id: str) -> list:
    """Scraper principal de Hiraoka PE."""
    all_records = []

    for cat_name, cat_path in HIRAOKA_CATEGORIES.items():
        logger.info(f"[Hiraoka] Categoría: {cat_name}")
        cat_records = []

        for page in range(1, HIRAOKA_MAX_PAGES + 1):
            items = _hiraoka_fetch_page(cat_name, cat_path, page)

            if not items:
                logger.debug(f"  Página {page}: sin items. Fin.")
                break

            for item in items:
                record = _hiraoka_parse(item, cat_name, batch_id)
                if record:
                    cat_records.append(record)

            logger.debug(f"  Página {page}: +{len(items)} items")
            time.sleep(REQUEST_DELAY)

        all_records.extend(cat_records)
        logger.info(f"  ✅ {cat_name}: {len(cat_records)} registros")

    logger.info(f"[Hiraoka] TOTAL: {len(all_records)} registros")
    return all_records


# ══════════════════════════════════════════════
# SCRAPER UNIFICADO
# ══════════════════════════════════════════════

def scrape_local(batch_id: str) -> list:
    """
    Ejecuta los 3 scrapers locales en secuencia.
    Retorna todos los registros combinados.
    """
    all_records = []

    logger.info("═" * 50)
    logger.info("  SCRAPING TIENDAS LOCALES PERÚ")
    logger.info("═" * 50)

    # Falabella
    try:
        records = scrape_falabella(batch_id)
        all_records.extend(records)
    except Exception as e:
        logger.error(f"[Falabella] Error fatal: {e}")

    # Ripley
    try:
        records = scrape_ripley(batch_id)
        all_records.extend(records)
    except Exception as e:
        logger.error(f"[Ripley] Error fatal: {e}")

    # Hiraoka
    try:
        records = scrape_hiraoka(batch_id)
        all_records.extend(records)
    except Exception as e:
        logger.error(f"[Hiraoka] Error fatal: {e}")

    logger.info(f"\n[LOCAL PE] TOTAL COMBINADO: {len(all_records)} registros")
    return all_records


# ──────────────────────────────────────────────
# EJECUCIÓN STANDALONE
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_batch = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results = scrape_local(test_batch)
    print(f"\nTotal registros: {len(results)}")
    if results:
        import json
        print("Ejemplo Falabella:", next((r for r in results if r["source"] == "falabella_pe"), None))
        print("Ejemplo Ripley:   ", next((r for r in results if r["source"] == "ripley_pe"), None))
        print("Ejemplo Hiraoka:  ", next((r for r in results if r["source"] == "hiraoka_pe"), None))
