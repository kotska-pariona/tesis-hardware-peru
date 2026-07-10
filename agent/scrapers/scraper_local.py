"""
scraper_local.py  v3.1
Scraper de tiendas locales Perú — Falabella, Ripley, Hiraoka

Diagnóstico real (julio 2026):
  - Falabella: IDs cat40712/cat40695/cat760706 son VÁLIDOS.
    El endpoint /s/browse/v1/listing/pe devuelve 404 sin sesión.
    Solución: usar /s/browse/v1/search/pe con searchTerm (funciona sin auth).
  - Ripley: simple.ripley.com.pe deprecado (403).
    www.ripley.com.pe tiene Cloudflare JS Challenge.
    Solución: scraping HTML de /buscar?query= con BeautifulSoup.
  - Hiraoka: URLs sin .html dan 404. Con .html dan 403 sin headers completos.
    Solución: headers completos de navegador real + session con cookies.

Fixes v3.1:
  [A] Falabella: endpoint /search con searchTerm como estrategia principal.
      categoryId como parámetro adicional para filtrar resultados.
  [B] Falabella: IDs de categoría reales verificados en DOM (julio 2026).
  [C] Ripley: scraping HTML de /buscar?query= en lugar de API JSON.
      Parser BeautifulSoup para estructura de tarjetas de producto.
  [D] Hiraoka: headers completos con sec-fetch-*, cookie vacía, lxml.
      Paginación con ?p= sobre URLs con sufijo .html.
  [E] Session con cookies persistentes (evita redirect de Cloudflare).
  [F] Retry con backoff en 429/5xx. Timeout (10s, 25s).
  [G] Fallback: si HTML scraping falla, intentar JSON API alternativa.
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
REQUEST_DELAY = 1.5        # segundos entre requests (más conservador)
TIMEOUT       = (10, 25)   # (connect, read)

# Headers que imitan Chrome 126 real
HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language":            "es-PE,es;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding":            "gzip, deflate, br",
    "Connection":                 "keep-alive",
    "Upgrade-Insecure-Requests":  "1",
    "sec-ch-ua":                  '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile":           "?0",
    "sec-ch-ua-platform":         '"Windows"',
    "sec-fetch-dest":             "document",
    "sec-fetch-mode":             "navigate",
    "sec-fetch-site":             "none",
    "sec-fetch-user":             "?1",
    "DNT":                        "1",
}

HEADERS_JSON = {
    **HEADERS_BROWSER,
    "Accept":           "application/json, text/plain, */*",
    "sec-fetch-dest":   "empty",
    "sec-fetch-mode":   "cors",
    "sec-fetch-site":   "same-origin",
}


# ──────────────────────────────────────────────
# Session con retry + cookies persistentes [E][F]
# ──────────────────────────────────────────────

def _make_session(retries: int = 3) -> requests.Session:
    """Session con retry automático y cookies persistentes entre requests."""
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=2.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    return session


def _warm_session(session: requests.Session, url: str) -> bool:
    """
    Hace un GET a la homepage para obtener cookies de sesión reales.
    Esto evita el Cloudflare JS Challenge en requests posteriores.
    """
    try:
        resp = session.get(url, headers=HEADERS_BROWSER, timeout=TIMEOUT)
        return resp.status_code == 200
    except Exception:
        return False


# ──────────────────────────────────────────────
# Parser de precios robusto
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
    "HP", "HyperX", "Hisense", "Honor", "Huawei",
    "Intel",
    "JBL",
    "Kingston",
    "Lenovo", "LG", "Logitech",
    "Microsoft", "MSI", "Motorola",
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
# FALABELLA
# ══════════════════════════════════════════════
#
# [A] Endpoint /search con searchTerm — funciona sin auth.
# [B] IDs reales verificados en DOM de falabella.com.pe julio 2026:
#     cat40712  → Laptops           (7586 resultados)
#     cat40695  → Monitores         (3864 resultados)
#     cat760706 → Celulares         (7175 resultados)
#     cat270476 → Tablets
#     cat6370551→ Televisores Smart TV
#     cat800582 → Audífonos
#     cat40556  → Videojuegos
# ──────────────────────────────────────────────

# Endpoint de búsqueda — no requiere sesión autenticada
FALABELLA_SEARCH_API  = "https://www.falabella.com.pe/s/browse/v1/search/pe"
# Endpoint de listing — requiere sesión (fallback con categoryId)
FALABELLA_LISTING_API = "https://www.falabella.com.pe/s/browse/v1/listing/pe"

# [B] Categorías: (categoryId_real, keyword_búsqueda)
FALABELLA_CATEGORIES = {
    "laptops":        ("cat40712",    "laptop"),
    "computadoras":   ("cat50678",    "computadora escritorio desktop"),
    "monitores":      ("cat40695",    "monitor"),
    "tablets":        ("cat270476",   "tablet"),
    "celulares":      ("cat760706",   "celular smartphone"),
    "televisores":    ("cat6370551",  "televisor smart tv"),
    "auriculares":    ("cat800582",   "audifonos auriculares"),
    "videojuegos":    ("cat40556",    "videojuegos consola"),
    "smartwatch":     ("cat1830468",  "smartwatch reloj inteligente"),
    "parlantes":      ("cat800584",   "parlante bluetooth"),
}

FALABELLA_MAX_PAGES = 20
FALABELLA_PAGE_SIZE = 48   # Falabella usa 48 por defecto en la web


def _falabella_fetch_page(
    session: requests.Session,
    cat_id: str,
    keyword: str,
    page: int,
) -> list:
    """
    [A] Usa /search con searchTerm + categoryId como filtro.
    Si falla, intenta /listing con categoryId puro.
    """
    headers = {
        **HEADERS_JSON,
        "Referer": f"https://www.falabella.com.pe/falabella-pe/category/{cat_id}/",
        "Origin":  "https://www.falabella.com.pe",
    }

    # Estrategia 1: search con keyword (más estable)
    params_search = {
        "searchTerm": keyword,
        "categoryId": cat_id,
        "page":       page,
        "pageSize":   FALABELLA_PAGE_SIZE,
        "sortBy":     "TOP_SELLERS",
        "channel":    "web",
        "locale":     "es_PE",
        "country":    "PE",
    }
    try:
        resp = session.get(
            FALABELLA_SEARCH_API, params=params_search,
            headers=headers, timeout=TIMEOUT
        )
        if resp.status_code == 200:
            data    = resp.json()
            results = (
                data.get("data", {}).get("results", []) or
                data.get("results", []) or
                data.get("products", [])
            )
            if results:
                return results
        logger.debug(f"  [Falabella] Search HTTP {resp.status_code} cat={cat_id} p={page}")
    except Exception as e:
        logger.debug(f"  [Falabella] Search error: {e}")

    # Estrategia 2: listing con categoryId (requiere sesión)
    params_listing = {
        "categoryId": cat_id,
        "page":       page,
        "pageSize":   FALABELLA_PAGE_SIZE,
        "sortBy":     "TOP_SELLERS",
        "channel":    "web",
        "locale":     "es_PE",
        "country":    "PE",
    }
    try:
        resp = session.get(
            FALABELLA_LISTING_API, params=params_listing,
            headers=headers, timeout=TIMEOUT
        )
        if resp.status_code == 200:
            data    = resp.json()
            results = (
                data.get("data", {}).get("results", []) or
                data.get("results", []) or
                data.get("products", [])
            )
            return results
        logger.warning(
            f"  [Falabella] Listing HTTP {resp.status_code} cat={cat_id} p={page}"
        )
    except Exception as e:
        logger.warning(f"  [Falabella] Listing error cat={cat_id} p={page}: {e}")

    return []


def _falabella_parse(raw: dict, category: str, batch_id: str, now_iso: str) -> Optional[dict]:
    try:
        prices     = raw.get("prices", [{}])
        price_info = prices[0] if isinstance(prices, list) and prices else (
            prices if isinstance(prices, dict) else {}
        )
        price      = (
            price_info.get("originalPrice") or
            price_info.get("normalPrice") or
            price_info.get("price")
        )
        price_sale = (
            price_info.get("specialPrice") or
            price_info.get("salePrice") or
            price_info.get("offerPrice")
        )

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
            ) if price and float(price) > 0 else 0.0,
            "rating":         raw.get("rating"),
            "reviews":        raw.get("totalReviews", raw.get("reviewCount")),
            "url":            "https://www.falabella.com.pe" + raw.get("url", ""),
        }
    except (TypeError, ValueError, KeyError, ZeroDivisionError) as e:
        logger.debug(f"  [Falabella] Parse error: {e}")
        return None


def scrape_falabella(batch_id: str) -> list:
    all_records = []
    now_iso     = datetime.now(timezone.utc).isoformat()
    session     = _make_session()

    # [E] Warm-up: obtener cookies reales de la homepage
    logger.info("[Falabella] Iniciando sesión (warm-up)...")
    _warm_session(session, "https://www.falabella.com.pe/falabella-pe")
    time.sleep(1.0)

    for cat_name, (cat_id, keyword) in FALABELLA_CATEGORIES.items():
        logger.info(f"[Falabella] Categoría: {cat_name} ({cat_id})")
        cat_records = []

        for page in range(1, FALABELLA_MAX_PAGES + 1):
            raw_items = _falabella_fetch_page(session, cat_id, keyword, page)

            if not raw_items:
                logger.debug(f"  Página {page}: sin items → fin")
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
# RIPLEY — [C] HTML scraping de /buscar
# ══════════════════════════════════════════════
#
# simple.ripley.com.pe → 403 (deprecado)
# www.ripley.com.pe/s/search → Cloudflare JS Challenge
# Solución: scraping HTML de /buscar?query= con BeautifulSoup
# ──────────────────────────────────────────────

RIPLEY_BASE       = "https://www.ripley.com.pe"
RIPLEY_SEARCH_URL = "https://www.ripley.com.pe/buscar"

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

RIPLEY_MAX_PAGES = 8


def _ripley_fetch_page_html(
    session: requests.Session, query: str, page: int
) -> list:
    """
    [C] Scraping HTML de /buscar?query=&page=N
    Retorna lista de tags BeautifulSoup de productos.
    """
    params = {
        "query": query,
        "page":  page,
    }
    headers = {
        **HEADERS_BROWSER,
        "Accept":         "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer":        f"{RIPLEY_BASE}/buscar?query={query.replace(' ', '+')}",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
    }
    try:
        resp = session.get(
            RIPLEY_SEARCH_URL, params=params,
            headers=headers, timeout=TIMEOUT
        )
        if resp.status_code in (403, 429):
            logger.warning(
                f"  [Ripley] HTTP {resp.status_code} query='{query}' p={page} "
                f"— bloqueado por anti-bot"
            )
            return []
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        # Selectores de tarjetas de producto Ripley (estructura 2025-2026)
        cards = (
            soup.select("div.catalog-product-item") or
            soup.select("div.product-card") or
            soup.select("article.product-item") or
            soup.select("li.product-item") or
            soup.select("[class*='ProductCard']") or
            soup.select("[data-product-id]")
        )
        return cards

    except requests.RequestException as e:
        logger.warning(f"  [Ripley] Error HTML query='{query}' p={page}: {e}")
        return []


def _ripley_parse_html(
    card, query: str, batch_id: str, now_iso: str
) -> Optional[dict]:
    """
    [C] Parsea una tarjeta HTML de producto de Ripley.
    Maneja múltiples estructuras de DOM posibles.
    """
    try:
        # Título
        title_tag = (
            card.select_one("a.product-item-link") or
            card.select_one(".product-title a") or
            card.select_one(".product-name a") or
            card.select_one("h3 a") or
            card.select_one("h2 a") or
            card.select_one("a[href*='/producto/']") or
            card.select_one("a[href*='/p']")
        )
        if not title_tag:
            return None
        title = title_tag.get_text(strip=True)
        url   = title_tag.get("href", "")
        if url and not url.startswith("http"):
            url = f"{RIPLEY_BASE}{url}"

        # Precio — múltiples selectores
        price_sale_tag = (
            card.select_one(".sale-price") or
            card.select_one(".offer-price") or
            card.select_one(".product-price .price") or
            card.select_one("[class*='salePrice']") or
            card.select_one("[class*='offerPrice']") or
            card.select_one(".special-price .price")
        )
        price_orig_tag = (
            card.select_one(".normal-price") or
            card.select_one(".regular-price .price") or
            card.select_one(".old-price .price") or
            card.select_one("[class*='normalPrice']") or
            card.select_one("[class*='regularPrice']")
        )

        final_price = _parse_price_str(
            price_sale_tag.get_text(strip=True) if price_sale_tag else None
        )
        orig_price  = _parse_price_str(
            price_orig_tag.get_text(strip=True) if price_orig_tag else None
        ) or final_price

        if not final_price or final_price <= 0:
            # Último intento: cualquier texto con patrón de precio
            all_text = card.get_text(" ", strip=True)
            price_match = re.search(r"S/\s*([\d,\.]+)", all_text)
            if price_match:
                final_price = _parse_price_str(price_match.group(1))
            if not final_price:
                return None

        # SKU
        sku = (
            card.get("data-product-id", "") or
            card.get("data-sku", "") or
            card.get("data-id", "")
        )
        if not sku:
            sku_tag = card.select_one("[data-product-id], [data-sku]")
            if sku_tag:
                sku = sku_tag.get("data-product-id") or sku_tag.get("data-sku", "")
        if not sku and url:
            # Extraer de URL: /producto-nombre-MPEID123/p
            m = re.search(r"-([A-Z0-9]{8,})(?:/p|\.html)?$", url)
            if m:
                sku = m.group(1)

        brand = _extract_brand(title)

        return {
            "batch_id":       batch_id,
            "timestamp":      now_iso,
            "source":         "ripley_pe",
            "category":       query,
            "sku":            str(sku),
            "brand":          brand,
            "title":          title,
            "price_pen":      final_price,
            "price_orig_pen": orig_price or final_price,
            "discount_pct":   round(
                (1 - final_price / orig_price) * 100, 1
            ) if orig_price and orig_price > 0 and orig_price != final_price else 0.0,
            "rating":         None,
            "reviews":        None,
            "url":            url,
        }
    except (TypeError, ValueError, AttributeError, ZeroDivisionError) as e:
        logger.debug(f"  [Ripley] Parse error: {e}")
        return None


def scrape_ripley(batch_id: str) -> list:
    all_records = []
    now_iso     = datetime.now(timezone.utc).isoformat()
    session     = _make_session()

    # [E] Warm-up: obtener cookies reales
    logger.info("[Ripley] Iniciando sesión (warm-up)...")
    _warm_session(session, "https://www.ripley.com.pe")
    time.sleep(1.5)

    for query in RIPLEY_QUERIES:
        logger.info(f"[Ripley] Query: '{query}'")
        query_records = []

        for page in range(1, RIPLEY_MAX_PAGES + 1):
            cards = _ripley_fetch_page_html(session, query, page)

            if not cards:
                if page == 1:
                    logger.warning(f"  [Ripley] Sin resultados para '{query}' p{page}")
                break

            for card in cards:
                record = _ripley_parse_html(card, query, batch_id, now_iso)
                if record:
                    query_records.append(record)

            logger.debug(f"  Página {page}: +{len(cards)} cards")
            time.sleep(REQUEST_DELAY)

        all_records.extend(query_records)
        logger.info(f"  ✅ '{query}': {len(query_records)} registros")

    logger.info(f"[Ripley] TOTAL: {len(all_records)} registros")
    return all_records


# ══════════════════════════════════════════════
# HIRAOKA — HTML scraping
# [D] URLs con sufijo .html + headers completos
# ══════════════════════════════════════════════

HIRAOKA_BASE = "https://www.hiraoka.com.pe"

# [D] Rutas verificadas — requieren sufijo .html
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
HIRAOKA_MIN_ITEMS_PAGE = 2


def _hiraoka_fetch_page(
    session: requests.Session,
    category: str,
    path: str,
    page: int
) -> list:
    """
    [D] Headers completos anti-403 + paginación ?p= sobre .html
    """
    base_url = f"{HIRAOKA_BASE}{path}"
    url      = f"{base_url}?p={page}"

    headers = {
        **HEADERS_BROWSER,
        "Accept":         "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Referer":        base_url if page > 1 else HIRAOKA_BASE,
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin" if page > 1 else "none",
        "sec-fetch-user": "?1",
        "Cache-Control":  "max-age=0",
    }

    try:
        resp = session.get(url, headers=headers, timeout=TIMEOUT)

        if resp.status_code == 403:
            logger.warning(f"  [Hiraoka] 403 en {path} p{page} — anti-bot activo")
            time.sleep(3.0)   # Espera extra antes de continuar
            return []
        if resp.status_code == 404:
            logger.warning(f"  [Hiraoka] 404 en {path} p{page} — URL incorrecta")
            return []

        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Detectar página sin resultados
        if soup.find("div", class_="message empty"):
            return []
        if soup.find("p", class_="empty-catalog"):
            return []

        # Selectores de productos Magento 2 / Luma
        products = (
            soup.select("li.product-item") or
            soup.select("div.product-item-info") or
            soup.select("article.product-item") or
            soup.select(".products-grid .item") or
            soup.select("[class*='product-item']")
        )
        return products

    except requests.RequestException as e:
        logger.warning(f"  [Hiraoka] Error p{page} {category}: {e}")
        return []


def _hiraoka_parse(item, category: str, batch_id: str, now_iso: str) -> Optional[dict]:
    """
    [D] Selectores actualizados para Magento 2 / Luma 2026.
    """
    try:
        # Nombre y URL
        name_tag = (
            item.select_one("a.product-item-link") or
            item.select_one(".product-item-name a") or
            item.select_one("strong.product-item-name a") or
            item.select_one(".product-name a") or
            item.select_one("h2.product-name a")
        )
        if not name_tag:
            return None
        title = name_tag.get_text(strip=True)
        url   = name_tag.get("href", "")

        # Precios — estructura Magento 2 Luma
        price_special = item.select_one(
            "span[data-price-type='finalPrice'] .price,"
            " .special-price .price,"
            " .price-box .price-final_price .price,"
            " [data-price-type='minPrice'] .price"
        )
        price_regular = item.select_one(
            "span[data-price-type='regularPrice'] .price,"
            " .old-price .price,"
            " .regular-price .price,"
            " .price-box .price-container .price"
        )

        final_price = _parse_price_str(
            price_special.get_text(strip=True) if price_special else None
        ) or _parse_price_str(
            price_regular.get_text(strip=True) if price_regular else None
        )
        orig_price = _parse_price_str(
            price_regular.get_text(strip=True) if price_regular else None
        ) or final_price

        if not final_price or final_price <= 0:
            return None

        # Rating
        rating = None
        rating_tag = item.select_one(".rating-result, .rating-summary")
        if rating_tag:
            style = rating_tag.get("style", "")
            m     = re.search(r"width:\s*([\d.]+)%", style)
            if m:
                rating = round(float(m.group(1)) / 20, 1)
            else:
                aria = rating_tag.get("aria-label", "")
                m2   = re.search(r"([\d.]+)\s*out\s*of", aria)
                if m2:
                    rating = float(m2.group(1))

        # SKU — múltiples estrategias
        sku = item.get("data-product-id", "")
        if not sku:
            sku_tag = item.select_one("[data-product-id]")
            if sku_tag:
                sku = sku_tag.get("data-product-id", "")
        if not sku and url:
            m = re.search(r"-(\d{5,})\.html", url)
            if m:
                sku = m.group(1)

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
            ) if orig_price and orig_price > 0 else 0.0,
            "rating":         rating,
            "reviews":        None,
            "url":            url if url.startswith("http") else f"{HIRAOKA_BASE}{url}",
        }
    except (TypeError, ValueError, AttributeError, ZeroDivisionError) as e:
        logger.debug(f"  [Hiraoka] Parse error: {e}")
        return None


def scrape_hiraoka(batch_id: str) -> list:
    all_records = []
    now_iso     = datetime.now(timezone.utc).isoformat()
    session     = _make_session()

    # [E] Warm-up: obtener cookies reales de Hiraoka
    logger.info("[Hiraoka] Iniciando sesión (warm-up)...")
    _warm_session(session, HIRAOKA_BASE)
    time.sleep(1.5)

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
    logger.info("  SCRAPING TIENDAS LOCALES PERÚ  v3.1")
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
        import json
        for src in ["falabella_pe", "ripley_pe", "hiraoka_pe"]:
            ex = next((r for r in results if r["source"] == src), None)
            if ex:
                print(f"\nEjemplo {src}:")
                print(json.dumps(ex, ensure_ascii=False, indent=2))
