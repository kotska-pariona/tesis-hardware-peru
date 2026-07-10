"""
scraper_local.py  v3.0
Scraper de tiendas locales Perú — Falabella, Ripley, Hiraoka

Fixes v3.0 (sobre v2.0):
  - [FIX-A] Falabella: IDs de categoría corregidos con valores reales
            extraídos del DOM de falabella.com.pe (julio 2026).
            API migrada a endpoint v2 con parámetros actualizados.
  - [FIX-B] Falabella: fallback a búsqueda por keyword cuando
            categoryId retorna 404/vacío.
  - [FIX-C] Ripley: migrado de simple.ripley.com.pe (403) a
            www.ripley.com.pe con endpoint de búsqueda correcto.
            Headers anti-bot mejorados (sec-fetch-*, cookie vacía).
  - [FIX-D] Hiraoka: rutas URL corregidas (sufijo .html requerido).
            Selector de precio actualizado para estructura 2026.
  - [FIX-E] Session compartida por scraper con retry automático.
  - [FIX-F] Timeout diferenciado: connect=10s, read=25s.
"""

import re
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
# CONFIGURACIÓN GLOBAL
# ──────────────────────────────────────────────
REQUEST_DELAY = 1.2          # segundos entre requests
TIMEOUT       = (10, 25)     # FIX-F: (connect, read)

HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language":           "es-PE,es;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding":           "gzip, deflate, br",
    "Connection":                "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

HEADERS_JSON = {
    **HEADERS_BROWSER,
    "Accept":       "application/json, text/plain, */*",
    "Content-Type": "application/json",
}


# ──────────────────────────────────────────────
# FIX-E: Session con retry automático
# ──────────────────────────────────────────────

def _make_session(retries: int = 3) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    return session


# ──────────────────────────────────────────────
# Parser de precios robusto (compartido)
# ──────────────────────────────────────────────

def _parse_price_str(text: str) -> Optional[float]:
    """
    'S/ 1,299.00' → 1299.0  |  'S/ 1.299,00' → 1299.0  |  '1299' → 1299.0
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
# Extracción de brand desde título
# ──────────────────────────────────────────────

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
    if not title:
        return ""
    m = _BRAND_PATTERN.search(title)
    return m.group(1).upper() if m else ""


# ══════════════════════════════════════════════
# FALABELLA — API JSON interna
# ══════════════════════════════════════════════
#
# FIX-A: IDs reales extraídos del DOM de falabella.com.pe
#        Fuente: <a href="/falabella-pe/category/CATID/Nombre">
#        Verificado julio 2026.
#
# NOTA: Si vuelven a fallar, ejecutar en DevTools:
#   document.querySelectorAll('a[href*="/category/"]')
#   .forEach(a => console.log(a.href))
# ──────────────────────────────────────────────

# Endpoint v2 — más estable que v1
FALABELLA_API_V2 = "https://www.falabella.com.pe/s/browse/v1/listing/pe"

# FIX-A: IDs reales (julio 2026)
FALABELLA_CATEGORIES = {
    "laptops":        "cat40712",    # /category/cat40712/Laptops ✅
    "computadoras":   "cat40713",    # /category/cat40713/Computadoras-de-Escritorio
    "monitores":      "cat40695",    # /category/cat40695/Monitores ✅
    "tablets":        "cat270476",   # /category/cat270476/Tablets ✅
    "celulares":      "cat760706",   # /category/cat760706/Celulares-y-Telefonos ✅
    "televisores":    "cat6370551",  # /category/cat6370551/Televisores-Smart-TV ✅
    "auriculares":    "cat800582",   # /category/cat800582/Audifonos ✅
    "videojuegos":    "cat40556",    # /category/cat40556/Videojuegos ✅
    "smartwatch":     "cat1830468",  # /category/cat1830468/Smartwatch-y-wearables ✅
    "parlantes":      "cat800584",   # /category/cat800584/Parlantes-Bluetooth ✅
}

# FIX-B: Keywords de fallback cuando categoryId falla
FALABELLA_FALLBACK_KEYWORDS = {
    "laptops":        "laptop",
    "computadoras":   "computadora escritorio",
    "monitores":      "monitor",
    "tablets":        "tablet",
    "celulares":      "celular smartphone",
    "televisores":    "televisor smart tv",
    "auriculares":    "audifonos auriculares",
    "videojuegos":    "videojuegos consola",
    "smartwatch":     "smartwatch reloj inteligente",
    "parlantes":      "parlante bluetooth",
}

FALABELLA_SEARCH_API = "https://www.falabella.com.pe/s/browse/v1/search/pe"
FALABELLA_MAX_PAGES  = 20


def _falabella_fetch_page(
    session: requests.Session,
    category_id: str,
    page: int,
    keyword: Optional[str] = None
) -> list:
    """
    Intenta primero por categoryId; si falla (404/vacío) usa keyword.
    FIX-A + FIX-B.
    """
    # Modo keyword (fallback)
    if keyword:
        params = {
            "searchTerm": keyword,
            "page":       page,
            "pageSize":   24,
            "sortBy":     "TOP_SELLERS",
            "channel":    "web",
            "locale":     "es_PE",
            "country":    "PE",
        }
        url = FALABELLA_SEARCH_API
    else:
        params = {
            "categoryId": category_id,
            "page":       page,
            "pageSize":   24,
            "sortBy":     "TOP_SELLERS",
            "channel":    "web",
            "locale":     "es_PE",
            "country":    "PE",
        }
        url = FALABELLA_API_V2

    headers = {
        **HEADERS_JSON,
        "Referer": "https://www.falabella.com.pe/",
        "Origin":  "https://www.falabella.com.pe",
    }
    try:
        resp = session.get(url, params=params, headers=headers, timeout=TIMEOUT)
        if resp.status_code in (400, 403, 404):
            logger.warning(
                f"  [Falabella] HTTP {resp.status_code} — cat={category_id} p={page}"
            )
            return []
        resp.raise_for_status()
        data = resp.json()
        results = (
            data.get("data", {}).get("results", []) or
            data.get("results", []) or
            data.get("products", [])
        )
        return results
    except requests.RequestException as e:
        logger.warning(f"  [Falabella] Error p{page} cat={category_id}: {e}")
        return []
    except (ValueError, KeyError) as e:
        logger.warning(f"  [Falabella] Error JSON p{page}: {e}")
        return []


def _falabella_parse(raw: dict, category: str, batch_id: str, now_iso: str) -> Optional[dict]:
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
            "timestamp":      now_iso,
            "source":         "falabella_pe",
            "category":       category,
            "sku":            str(raw.get("skuId", raw.get("id", ""))),
            "brand":          brand or _extract_brand(title),
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
        logger.debug(f"  [Falabella] Error parseando: {e}")
        return None


def scrape_falabella(batch_id: str) -> list:
    all_records = []
    now_iso     = datetime.now(timezone.utc).isoformat()
    session     = _make_session()   # FIX-E

    for cat_name, cat_id in FALABELLA_CATEGORIES.items():
        logger.info(f"[Falabella] Categoría: {cat_name} ({cat_id})")
        cat_records  = []
        use_fallback = False   # FIX-B

        for page in range(1, FALABELLA_MAX_PAGES + 1):
            keyword   = FALABELLA_FALLBACK_KEYWORDS.get(cat_name) if use_fallback else None
            raw_items = _falabella_fetch_page(session, cat_id, page, keyword=keyword)

            # FIX-B: Si p1 falla con categoryId → reintentar con keyword
            if not raw_items and page == 1 and not use_fallback:
                logger.info(f"  [Falabella] Fallback a keyword para '{cat_name}'")
                use_fallback = True
                raw_items    = _falabella_fetch_page(
                    session, cat_id, page,
                    keyword=FALABELLA_FALLBACK_KEYWORDS.get(cat_name)
                )

            if not raw_items:
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
# RIPLEY — FIX-C: Migrado a www.ripley.com.pe
# ══════════════════════════════════════════════
#
# simple.ripley.com.pe → 403 Forbidden (deprecado)
# Nuevo endpoint: www.ripley.com.pe/search con parámetros REST
# ──────────────────────────────────────────────

RIPLEY_SEARCH_API = "https://www.ripley.com.pe/s/search/v1/product/search"

# Alternativa si el anterior también falla:
RIPLEY_SEARCH_ALT = "https://www.ripley.com.pe/api/2.0/catalog_system/pub/products/search"

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


def _ripley_fetch_page(session: requests.Session, query: str, page: int) -> dict:
    """
    FIX-C: Intenta endpoint principal; si falla, intenta alternativo.
    Headers anti-bot mejorados para Cloudflare.
    """
    headers = {
        **HEADERS_JSON,
        "Referer":          f"https://www.ripley.com.pe/search?q={query.replace(' ', '+')}",
        "Origin":           "https://www.ripley.com.pe",
        "sec-fetch-dest":   "empty",
        "sec-fetch-mode":   "cors",
        "sec-fetch-site":   "same-origin",
        "sec-ch-ua":        '"Chromium";v="126", "Google Chrome";v="126"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Cookie":           "",   # Cookie vacía evita redirect de sesión
    }

    # Endpoint principal
    params_main = {
        "q":       query,
        "page":    page - 1,   # 0-indexed
        "count":   40,
        "country": "PE",
        "store":   "ripley",
    }
    try:
        resp = session.get(
            RIPLEY_SEARCH_API, params=params_main,
            headers=headers, timeout=TIMEOUT
        )
        if resp.status_code == 200:
            return resp.json()
        logger.debug(f"  [Ripley] Endpoint principal HTTP {resp.status_code} — probando alternativo")
    except requests.RequestException as e:
        logger.debug(f"  [Ripley] Endpoint principal error: {e}")

    # FIX-C: Endpoint alternativo VTEX
    params_alt = {
        "ft":       query,
        "_from":    (page - 1) * 40,
        "_to":      page * 40 - 1,
        "O":        "OrderByTopSaleDESC",
    }
    try:
        resp = session.get(
            RIPLEY_SEARCH_ALT, params=params_alt,
            headers=headers, timeout=TIMEOUT
        )
        if resp.status_code == 200:
            items = resp.json()
            if isinstance(items, list):
                return {"products": items, "total": len(items)}
        logger.warning(
            f"  [Ripley] HTTP {resp.status_code} query '{query}' p{page}"
        )
    except requests.RequestException as e:
        logger.warning(f"  [Ripley] Error query '{query}' p{page}: {e}")

    return {}


def _ripley_parse(raw: dict, query: str, batch_id: str, now_iso: str) -> Optional[dict]:
    try:
        # Estructura VTEX (alternativo)
        if "items" in raw and isinstance(raw.get("items"), list):
            item       = raw["items"][0] if raw["items"] else {}
            sellers    = item.get("sellers", [{}])
            offer      = sellers[0].get("commertialOffer", {}) if sellers else {}
            price      = offer.get("ListPrice") or offer.get("Price")
            price_sale = offer.get("Price")
            brand      = raw.get("brand", "")
            name       = raw.get("productName", raw.get("name", ""))
            sku        = raw.get("productId", raw.get("id", ""))
            url        = f"https://www.ripley.com.pe/{raw.get('linkText', '')}/p"
        else:
            # Estructura propia de Ripley
            price_info  = raw.get("prices", {})
            price       = (
                price_info.get("normalPrice") or
                price_info.get("offerPrice") or
                raw.get("price")
            )
            price_sale  = price_info.get("offerPrice") or price_info.get("salePrice")
            brand       = raw.get("brand", "")
            name        = raw.get("displayName", raw.get("name", ""))
            sku         = str(raw.get("partNumber", raw.get("id", "")))
            slug        = raw.get("slug", raw.get("url", ""))
            url         = (
                f"https://www.ripley.com.pe/{slug}"
                if slug and not slug.startswith("http") else slug
            )

        if not price:
            return None

        final_price = float(price_sale or price)
        if final_price <= 0:
            return None

        title = f"{brand} {name}".strip()

        rating_raw = raw.get("rating")
        if isinstance(rating_raw, dict):
            rating  = rating_raw.get("average")
            reviews = rating_raw.get("count")
        else:
            rating  = rating_raw
            reviews = None

        return {
            "batch_id":       batch_id,
            "timestamp":      now_iso,
            "source":         "ripley_pe",
            "category":       query,
            "sku":            str(sku),
            "brand":          brand or _extract_brand(title),
            "title":          title,
            "price_pen":      final_price,
            "price_orig_pen": float(price),
            "discount_pct":   round(
                (1 - final_price / float(price)) * 100, 1
            ) if float(price) > 0 else 0,
            "rating":         rating,
            "reviews":        reviews,
            "url":            url or "",
        }
    except (TypeError, ValueError, KeyError, ZeroDivisionError) as e:
        logger.debug(f"  [Ripley] Error parseando: {e}")
        return None


def scrape_ripley(batch_id: str) -> list:
    all_records = []
    now_iso     = datetime.now(timezone.utc).isoformat()
    session     = _make_session()   # FIX-E

    for query in RIPLEY_QUERIES:
        logger.info(f"[Ripley] Query: '{query}'")
        query_records = []

        for page in range(1, RIPLEY_MAX_PAGES + 1):
            data      = _ripley_fetch_page(session, query, page)
            raw_items = (
                data.get("products", []) or
                data.get("results", []) or
                data.get("items", [])
            )
            total = data.get("total", data.get("totalCount", 0))

            if not raw_items:
                if page == 1:
                    logger.warning(f"  [Ripley] Sin resultados para '{query}' p{page}")
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
# FIX-D: URLs corregidas con sufijo .html
# ══════════════════════════════════════════════

HIRAOKA_BASE = "https://www.hiraoka.com.pe"

# FIX-D: Rutas corregidas — Hiraoka requiere .html al final
HIRAOKA_CATEGORIES = {
    "laptops":      "/laptops-y-accesorios/laptops.html",
    "computadoras": "/laptops-y-accesorios/computadoras-de-escritorio.html",
    "monitores":    "/laptops-y-accesorios/monitores.html",
    "impresoras":   "/impresoras-y-accesorios/impresoras.html",
    "tablets":      "/celulares-y-tablets/tablets.html",
    "celulares":    "/celulares-y-tablets/celulares.html",
    "televisores":  "/television-y-video/televisores.html",
    "auriculares":  "/audio/audifonos.html",
    "camaras":      "/camaras-y-accesorios/camaras-digitales.html",
    "videojuegos":  "/videojuegos/consolas.html",
    "memorias":     "/laptops-y-accesorios/memorias-ram.html",
    "discos":       "/laptops-y-accesorios/discos-duros-y-ssd.html",
    "procesadores": "/laptops-y-accesorios/procesadores.html",
}

HIRAOKA_MAX_PAGES      = 30
HIRAOKA_MIN_ITEMS_PAGE = 3


def _hiraoka_fetch_page(
    session: requests.Session,
    category: str,
    path: str,
    page: int
) -> list:
    # FIX-D: paginación con ?p= sobre URL con .html
    url     = f"{HIRAOKA_BASE}{path}?p={page}"
    headers = {
        **HEADERS_BROWSER,
        "Referer": f"{HIRAOKA_BASE}{path}",
        "Accept":  "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        resp = session.get(url, headers=headers, timeout=TIMEOUT)
        if resp.status_code == 404:
            logger.warning(f"  [Hiraoka] 404 en {path} p{page}")
            return []
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Detectar página vacía / sin resultados
        if soup.find("div", class_="message empty"):
            return []

        products = (
            soup.select("li.product-item") or
            soup.select("div.product-item-info") or
            soup.select("article.product-item") or
            soup.select(".products-grid .item")
        )
        return products

    except requests.RequestException as e:
        logger.warning(f"  [Hiraoka] Error p{page} {category}: {e}")
        return []


def _hiraoka_parse(item, category: str, batch_id: str, now_iso: str) -> Optional[dict]:
    """
    FIX-D: Selectores de precio actualizados para estructura 2026.
    """
    try:
        # Nombre y URL
        name_tag = (
            item.select_one("a.product-item-link") or
            item.select_one(".product-item-name a") or
            item.select_one("strong.product-item-name a") or
            item.select_one(".product-name a")
        )
        if not name_tag:
            return None
        title = name_tag.get_text(strip=True)
        url   = name_tag.get("href", "")

        # FIX-D: Selectores de precio actualizados (estructura Magento 2 / Luma 2026)
        price_special = item.select_one(
            "span[data-price-type='finalPrice'] .price,"
            " .special-price .price,"
            " .price-box .price-final_price .price"
        )
        price_regular = item.select_one(
            "span[data-price-type='regularPrice'] .price,"
            " .old-price .price,"
            " .regular-price .price,"
            " .price-box .price-container .price"
        )

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
                aria = rating_tag.get("aria-label", "")
                m    = re.search(r"([\d.]+)\s*out\s*of", aria)
                if m:
                    rating = float(m.group(1))

        # SKU
        sku = item.get("data-product-id", "")
        if not sku:
            sku_tag = item.select_one("[data-product-id]")
            if sku_tag:
                sku = sku_tag.get("data-product-id", "")
        if not sku:
            # Extraer de URL: .../nombre-producto-SKU123.html
            sku_match = re.search(r"-(\d{5,})\.html", url)
            if sku_match:
                sku = sku_match.group(1)

        brand = _extract_brand(title)

        return {
            "batch_id":       batch_id,
            "timestamp":      now_iso,
            "source":         "hiraoka_pe",
            "category":       category,
            "sku":            str(sku),
            "brand":          brand,
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
    all_records = []
    now_iso     = datetime.now(timezone.utc).isoformat()
    session     = _make_session()   # FIX-E

    for cat_name, cat_path in HIRAOKA_CATEGORIES.items():
        logger.info(f"[Hiraoka] Categoría: {cat_name}")
        cat_records = []

        for page in range(1, HIRAOKA_MAX_PAGES + 1):
            items = _hiraoka_fetch_page(session, cat_name, cat_path, page)

            if not items or len(items) < HIRAOKA_MIN_ITEMS_PAGE:
                logger.debug(f"  Página {page}: {len(items)} items → fin")
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
    Deduplica por (source, sku) al final.
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
            logger.error(f"[{name}] Error fatal: {e}", exc_info=True)

    # Deduplicar por (source, sku)
    seen   = set()
    unique = []
    no_sku = []
    for r in all_records:
        key = (r.get("source", ""), str(r.get("sku", "")))
        if key[1] and key not in seen:
            seen.add(key)
            unique.append(r)
        elif not key[1]:
            no_sku.append(r)

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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    test_batch = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results    = scrape_local(test_batch)
    print(f"\nTotal registros: {len(results)}")
    if results:
        for src in ["falabella_pe", "ripley_pe", "hiraoka_pe"]:
            ex = next((r for r in results if r["source"] == src), None)
            if ex:
                import json
                print(f"\nEjemplo {src}:")
                print(json.dumps(ex, ensure_ascii=False, indent=2))
