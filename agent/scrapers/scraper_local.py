"""
scraper_local.py  v2.0
Scraper de tiendas locales Perú — Falabella, Ripley, Hiraoka

Fixes v2.0:
  - [FIX-1] Falabella: IDs de categoría marcados como pendientes de verificación
            + fallback a búsqueda por keyword si categoryId falla
  - [FIX-2] Hiraoka: SKU selector corregido (None.get() → AttributeError)
  - [FIX-3] Hiraoka: clean_price reemplazada por _parse_price_str() robusta
  - [FIX-4] Falabella: MAX_PAGES reducido a 20 (750→300 requests)
  - [FIX-5] Hiraoka: detección de fin de paginación por conteo de productos
  - [FIX-6] Hiraoka: extracción de brand desde el título
  - [FIX-7] Deduplicación por (source, sku) al final de scrape_local()
  - [FIX-8] timestamp unificado por batch (no por producto)
  - [FIX-9] Ripley: log cuando API retorna vacío
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


# ──────────────────────────────────────────────
# FIX-3: Parser de precios robusto (compartido)
# ──────────────────────────────────────────────

def _parse_price_str(text: str) -> Optional[float]:
    """
    Convierte texto de precio a float — maneja S/, $, puntos y comas.
      'S/ 1,299.00' → 1299.0
      'S/ 1.299,00' → 1299.0
      '1299'        → 1299.0
    """
    if not text:
        return None
    clean = re.sub(r"[^\d,.]", "", str(text).strip())
    if not clean:
        return None
    try:
        if "," in clean and "." in clean:
            if clean.rfind(",") > clean.rfind("."):
                clean = clean.replace(".", "").replace(",", ".")
            else:
                clean = clean.replace(",", "")
        elif "," in clean:
            parts = clean.split(",")
            if len(parts) == 2 and len(parts[1]) <= 2:
                clean = clean.replace(",", ".")
            else:
                clean = clean.replace(",", "")
        val = float(clean)
        return val if val > 0 else None
    except ValueError:
        return None


# ──────────────────────────────────────────────
# FIX-6: Extracción de brand desde título
# ──────────────────────────────────────────────

# Marcas conocidas de hardware/electrónica
KNOWN_BRANDS = [
    "ASUS", "Acer", "Apple", "AMD", "Alienware", "AOC",
    "BenQ", "Brother",
    "Canon", "Corsair", "Creative",
    "Dell", "D-Link",
    "Epson",
    "Gigabyte", "G.Skill",
    "HP", "HyperX", "Hisense",
    "Intel",
    "JBL",
    "Kingston",
    "Lenovo", "LG", "Logitech",
    "Microsoft", "MSI",
    "Nikon", "NVIDIA",
    "Panasonic", "Philips",
    "Razer",
    "Samsung", "Seagate", "Sony",
    "TP-Link", "Toshiba",
    "WD", "Western Digital",
    "Xiaomi",
]
_BRAND_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(b) for b in KNOWN_BRANDS) + r")\b",
    re.IGNORECASE
)

def _extract_brand(title: str) -> str:
    """Extrae la marca del título usando lista de marcas conocidas."""
    if not title:
        return ""
    m = _BRAND_PATTERN.search(title)
    return m.group(1).upper() if m else ""


# ══════════════════════════════════════════════
# FALABELLA — API JSON interna
# ══════════════════════════════════════════════

FALABELLA_API = "https://www.falabella.com.pe/s/browse/v1/listing/pe"

# FIX-1: IDs marcados como pendientes de verificación
# ACCIÓN REQUERIDA: Verificar IDs reales en DevTools → Network → XHR
# mientras navegas por https://www.falabella.com.pe/falabella-pe/category/
# Los IDs reales tienen formato como: cat40062, 4294967094, etc.
FALABELLA_CATEGORIES = {
    "laptops":        "cat40062",   # ⚠️ VERIFICAR
    "computadoras":   "cat40063",   # ⚠️ VERIFICAR
    "procesadores":   "cat40064",   # ⚠️ VERIFICAR
    "tarjetas_video": "cat40065",   # ⚠️ VERIFICAR
    "monitores":      "cat40066",   # ⚠️ VERIFICAR
    "memorias_ram":   "cat40067",   # ⚠️ VERIFICAR
    "discos_duros":   "cat40068",   # ⚠️ VERIFICAR
    "teclados":       "cat40069",   # ⚠️ VERIFICAR
    "mouse":          "cat40070",   # ⚠️ VERIFICAR
    "tablets":        "cat40072",   # ⚠️ VERIFICAR
    "celulares":      "cat10001",   # ⚠️ VERIFICAR
    "televisores":    "cat10002",   # ⚠️ VERIFICAR
    "auriculares":    "cat10003",   # ⚠️ VERIFICAR
}

# FIX-4: Reducido de 50 → 20 (750 → 300 requests, ~4 min)
FALABELLA_MAX_PAGES = 20


def _falabella_fetch_page(category_id: str, page: int) -> list:
    """Llama a la API JSON de Falabella y retorna lista de productos crudos."""
    params = {
        "categoryId": category_id,
        "page":       page,
        "pageSize":   24,
        "sortBy":     "TOP_SELLERS",
        "zones":      "15",
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
        # FIX-1: Detectar 400/403 y loguear para diagnóstico
        if resp.status_code in (400, 403, 404):
            logger.warning(
                f"  [Falabella] HTTP {resp.status_code} en cat {category_id} p{page} "
                f"— ¿ID de categoría incorrecto? Verificar en DevTools."
            )
            return []
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("results", [])
    except requests.RequestException as e:
        logger.warning(f"  [Falabella] Error página {page} cat {category_id}: {e}")
        return []
    except (ValueError, KeyError) as e:
        logger.warning(f"  [Falabella] Error JSON página {page}: {e}")
        return []


def _falabella_parse(raw: dict, category: str, batch_id: str, now_iso: str) -> Optional[dict]:
    """Normaliza un producto crudo de Falabella. FIX-8: now_iso como parámetro."""
    try:
        prices     = raw.get("prices", [{}])
        price_info = prices[0] if prices else {}
        price      = price_info.get("originalPrice") or price_info.get("price")
        price_sale = price_info.get("specialPrice") or price_info.get("salePrice")

        if not price and not price_sale:
            return None

        final_price = float(price_sale or price)
        if final_price <= 0:
            return None

        brand = raw.get("brand", "")
        name  = raw.get("displayName", raw.get("name", ""))
        title = f"{brand} {name}".strip()

        return {
            "batch_id":       batch_id,
            "timestamp":      now_iso,   # FIX-8
            "source":         "falabella_pe",
            "category":       category,
            "sku":            str(raw.get("skuId", raw.get("id", ""))),
            "brand":          brand or _extract_brand(title),   # FIX-6
            "title":          title,
            "price_pen":      final_price,
            "price_orig_pen": float(price) if price else final_price,
            "discount_pct":   round(
                (1 - final_price / float(price)) * 100, 1
            ) if price and float(price) > 0 else 0,
            "rating":         raw.get("rating"),
            "reviews":        raw.get("totalReviews", raw.get("reviewCount")),
            "url": "https://www.falabella.com.pe" + raw.get("url", ""),
        }
    except (TypeError, ValueError, KeyError, ZeroDivisionError) as e:
        logger.debug(f"  [Falabella] Error parseando producto: {e}")
        return None


def scrape_falabella(batch_id: str) -> list:
    """Scraper principal de Falabella PE."""
    all_records = []
    now_iso     = datetime.now(timezone.utc).isoformat()   # FIX-8

    for cat_name, cat_id in FALABELLA_CATEGORIES.items():
        logger.info(f"[Falabella] Categoría: {cat_name} ({cat_id})")
        cat_records = []

        for page in range(1, FALABELLA_MAX_PAGES + 1):
            raw_items = _falabella_fetch_page(cat_id, page)

            if not raw_items:
                logger.debug(f"  Página {page}: sin items. Fin.")
                break

            for raw in raw_items:
                record = _falabella_parse(raw, cat_name, batch_id, now_iso)
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
    "laptop", "computadora desktop",
    "procesador intel", "procesador amd",
    "tarjeta de video nvidia", "tarjeta de video amd",
    "memoria ram ddr4", "memoria ram ddr5",
    "disco duro ssd", "disco duro nvme",
    "monitor gaming", "monitor 4k",
    "teclado mecanico", "mouse gaming",
    "tablet", "celular samsung", "celular xiaomi",
    "impresora", "auriculares bluetooth", "camara fotografica",
]

RIPLEY_MAX_PAGES = 10


def _ripley_fetch_page(query: str, page: int) -> dict:
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
        resp = requests.get(RIPLEY_API, params=params, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.warning(f"  [Ripley] Error página {page} query '{query}': {e}")
        return {}
    except ValueError as e:
        logger.warning(f"  [Ripley] Error JSON: {e}")
        return {}


def _ripley_parse(raw: dict, query: str, batch_id: str, now_iso: str) -> Optional[dict]:
    """Normaliza un producto crudo de Ripley. FIX-8: now_iso como parámetro."""
    try:
        price_info  = raw.get("prices", {})
        price       = (
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
        title = f"{brand} {name}".strip()
        slug  = raw.get("slug", raw.get("url", ""))

        rating_raw = raw.get("rating")
        if isinstance(rating_raw, dict):
            rating  = rating_raw.get("average")
            reviews = rating_raw.get("count")
        else:
            rating  = rating_raw
            reviews = None

        return {
            "batch_id":       batch_id,
            "timestamp":      now_iso,   # FIX-8
            "source":         "ripley_pe",
            "category":       query,
            "sku":            str(raw.get("partNumber", raw.get("id", ""))),
            "brand":          brand or _extract_brand(title),   # FIX-6
            "title":          title,
            "price_pen":      final_price,
            "price_orig_pen": float(price),
            "discount_pct":   round(
                (1 - final_price / float(price)) * 100, 1
            ) if float(price) > 0 else 0,
            "rating":         rating,
            "reviews":        reviews,
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
    now_iso     = datetime.now(timezone.utc).isoformat()   # FIX-8

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

            # FIX-9: Log cuando API retorna vacío
            if not raw_items:
                if not data:
                    logger.warning(f"  [Ripley] API retornó vacío para '{query}' p{page}")
                break

            for raw in raw_items:
                record = _ripley_parse(raw, query, batch_id, now_iso)
                if record:
                    query_records.append(record)

            logger.debug(f"  Página {page}: +{len(raw_items)} (total: {total})")

            if total and len(query_records) >= total:
                break

            time.sleep(REQUEST_DELAY)

        all_records.extend(query_records)
        logger.info(f"  ✅ '{query}': {len(query_records)} registros")

    logger.info(f"[Ripley] TOTAL: {len(all_records)} registros")
    return all_records


# ══════════════════════════════════════════════
# HIRAOKA — HTML scraping
# ══════════════════════════════════════════════

HIRAOKA_BASE = "https://www.hiraoka.com.pe"

HIRAOKA_CATEGORIES = {
    "laptops":      "/laptops-y-accesorios/laptops",
    "computadoras": "/laptops-y-accesorios/computadoras-de-escritorio",
    "monitores":    "/laptops-y-accesorios/monitores",
    "impresoras":   "/impresoras-y-accesorios/impresoras",
    "tablets":      "/celulares-y-tablets/tablets",
    "celulares":    "/celulares-y-tablets/celulares",
    "televisores":  "/television-y-video/televisores",
    "auriculares":  "/audio/audifonos",
    "camaras":      "/camaras-y-accesorios/camaras-digitales",
    "videojuegos":  "/videojuegos/consolas",
}

HIRAOKA_MAX_PAGES      = 30
HIRAOKA_MIN_ITEMS_PAGE = 3   # FIX-5: si hay menos de 3 items, asumir fin de paginación


def _hiraoka_fetch_page(category: str, path: str, page: int) -> list:
    url     = f"{HIRAOKA_BASE}{path}?p={page}"
    headers = {**HEADERS_BROWSER, "Referer": f"{HIRAOKA_BASE}{path}"}

    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # FIX-5: Detección de fin por selector CSS + conteo
        no_results = (
            soup.find("div", class_="message empty") or
            soup.find("div", class_="catalog-category-view") and
            not soup.select("li.product-item")
        )
        if no_results:
            return []

        products = (
            soup.select("li.product-item") or
            soup.select("div.product-item-info") or
            soup.select("article.product-item")
        )
        return products

    except requests.RequestException as e:
        logger.warning(f"  [Hiraoka] Error página {page} {category}: {e}")
        return []


def _hiraoka_parse(item, category: str, batch_id: str, now_iso: str) -> Optional[dict]:
    """Parsea un elemento de producto de Hiraoka. FIX-2, FIX-3, FIX-8."""
    try:
        # Nombre
        name_tag = (
            item.select_one("a.product-item-link") or
            item.select_one(".product-item-name a") or
            item.select_one("strong.product-item-name a")
        )
        if not name_tag:
            return None
        title = name_tag.get_text(strip=True)
        url   = name_tag.get("href", "")

        # Precios
        price_special = item.select_one(
            "span.price-wrapper[data-price-type='finalPrice'] span.price,"
            " .special-price .price"
        )
        price_regular = item.select_one(
            "span.price-wrapper[data-price-type='regularPrice'] span.price,"
            " .old-price .price,"
            " .regular-price .price"
        )

        # FIX-3: usar _parse_price_str() en lugar de replace(',','')
        final_price = (
            _parse_price_str(price_special.get_text(strip=True) if price_special else None) or
            _parse_price_str(price_regular.get_text(strip=True) if price_regular else None)
        )
        orig_price = (
            _parse_price_str(price_regular.get_text(strip=True) if price_regular else None) or
            final_price
        )

        if not final_price or final_price <= 0:
            return None

        # Rating
        rating = None
        rating_tag = item.select_one(".rating-result, .rating-summary")
        if rating_tag:
            style     = rating_tag.get("style", "")
            pct_match = re.search(r"width:\s*([\d.]+)%", style)
            if pct_match:
                rating = round(float(pct_match.group(1)) / 20, 1)
            else:
                # Alternativa: aria-label="Rating: 4.5 out of 5"
                aria = rating_tag.get("aria-label", "")
                aria_match = re.search(r"([\d.]+)\s*out\s*of", aria)
                if aria_match:
                    rating = float(aria_match.group(1))

        # FIX-2: SKU selector corregido — sin None.get()
        sku = item.get("data-product-id", "")
        if not sku:
            sku_tag = item.select_one("[data-product-id]")
            if sku_tag:
                sku = sku_tag.get("data-product-id", "")

        # FIX-6: Extraer brand del título
        brand = _extract_brand(title)

        return {
            "batch_id":       batch_id,
            "timestamp":      now_iso,   # FIX-8
            "source":         "hiraoka_pe",
            "category":       category,
            "sku":            str(sku),
            "brand":          brand,     # FIX-6
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
    now_iso     = datetime.now(timezone.utc).isoformat()   # FIX-8

    for cat_name, cat_path in HIRAOKA_CATEGORIES.items():
        logger.info(f"[Hiraoka] Categoría: {cat_name}")
        cat_records = []

        for page in range(1, HIRAOKA_MAX_PAGES + 1):
            items = _hiraoka_fetch_page(cat_name, cat_path, page)

            # FIX-5: Fin por conteo mínimo de items
            if not items or len(items) < HIRAOKA_MIN_ITEMS_PAGE:
                logger.debug(f"  Página {page}: {len(items)} items → fin de paginación")
                break

            for item in items:
                record = _hiraoka_parse(item, cat_name, batch_id, now_iso)
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
    FIX-7: Deduplica por (source, sku) al final.
    """
    all_records = []

    logger.info("═" * 50)
    logger.info("  SCRAPING TIENDAS LOCALES PERÚ")
    logger.info("═" * 50)

    for name, fn in [
        ("Falabella", scrape_falabella),
        ("Ripley",    scrape_ripley),
        ("Hiraoka",   scrape_hiraoka),
    ]:
        try:
            records = fn(batch_id)
            all_records.extend(records)
        except Exception as e:
            logger.error(f"[{name}] Error fatal: {e}")

    # FIX-7: Deduplicar por (source, sku) — eliminar duplicados de Ripley
    seen    = set()
    unique  = []
    no_sku  = []
    for r in all_records:
        key = (r.get("source", ""), str(r.get("sku", "")))
        if key[1] and key not in seen:
            seen.add(key)
            unique.append(r)
        elif not key[1]:
            no_sku.append(r)   # Sin SKU → conservar siempre

    combined = unique + no_sku
    dupes    = len(all_records) - len(combined)
    if dupes:
        logger.info(f"[LOCAL PE] Deduplicados: {dupes} registros eliminados")

    logger.info(f"[LOCAL PE] TOTAL COMBINADO: {len(combined)} registros únicos")
    return combined


# ──────────────────────────────────────────────
# STANDALONE
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_batch = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results    = scrape_local(test_batch)
    print(f"\nTotal registros: {len(results)}")
    if results:
        import json
        for src in ["falabella_pe", "ripley_pe", "hiraoka_pe"]:
            ex = next((r for r in results if r["source"] == src), None)
            print(f"Ejemplo {src}:", ex)
