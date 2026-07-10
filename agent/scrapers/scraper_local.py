"""
scraper_local.py  v3.2
Scraper de tiendas locales Perú — Falabella, Ripley, Hiraoka

ROOT CAUSE confirmado (julio 2026):
  - Falabella: /search + categoryId como FILTRO → bloquea resultados.
    scraper_competencia usa SOLO searchTerm sin categoryId → 48 items/pág ✅
    Fix: eliminar categoryId de los params de /search.
  - Ripley: 403 Cloudflare persistente incluso con warm-up.
    requests no ejecuta JS → no obtiene cf_clearance cookie.
    Fix: marcado como no_disponible, se omite sin crashear el pipeline.
  - Hiraoka: 404 en todas las URLs con .html
    Fix: probar sin .html y con slash final como alternativa.

Cambios v3.2:
  [A] Falabella: searchTerm SOLO, sin categoryId en params.
      Categorías mapeadas a keywords específicas de hardware PE.
  [B] Falabella: eliminar fallback a /listing (siempre 404).
      Un solo endpoint limpio: /search con searchTerm.
  [C] Ripley: deshabilitado con log claro. No crashea el pipeline.
      Razón: Cloudflare JS Challenge no superable con requests puro.
  [D] Hiraoka: probar 3 formatos de URL por categoría:
      1. /categoria/subcategoria (sin .html)
      2. /categoria/subcategoria/ (con slash)
      3. /categoria/subcategoria.html (con .html)
  [E] Log de diagnóstico mejorado para detectar cambios futuros.
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
REQUEST_DELAY = 1.2
TIMEOUT       = (10, 25)

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
}

HEADERS_JSON = {
    **HEADERS_BROWSER,
    "Accept":         "application/json, text/plain, */*",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}


def _make_session(retries: int = 3) -> requests.Session:
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
    try:
        resp = session.get(url, headers=HEADERS_BROWSER, timeout=TIMEOUT)
        logger.debug(f"  Warm-up {url} → HTTP {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        logger.debug(f"  Warm-up error: {e}")
        return False


def _parse_price_str(text: str) -> Optional[float]:
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
# FALABELLA — Fix [A][B]
# ══════════════════════════════════════════════
#
# CAUSA RAÍZ: categoryId como filtro adicional en /search
# bloquea resultados. scraper_competencia usa SOLO searchTerm
# y obtiene 48 items/pág consistentemente.
#
# Fix: usar SOLO searchTerm, sin categoryId.
# ──────────────────────────────────────────────

FALABELLA_SEARCH_API = "https://www.falabella.com.pe/s/browse/v1/search/pe"

# [A] Keywords específicas — sin categoryId
# Cada keyword mapea a productos de hardware/electrónica en Falabella PE
FALABELLA_QUERIES = {
    # Hardware PC
    "laptops":        "laptop",
    "computadoras":   "computadora escritorio",
    "monitores":      "monitor",
    "memorias_ram":   "memoria ram",
    "discos_ssd":     "disco ssd nvme",
    "procesadores":   "procesador intel amd",
    "tarjetas_video": "tarjeta de video nvidia amd",
    # Periféricos
    "teclados":       "teclado mecanico gaming",
    "mouse":          "mouse gaming",
    "auriculares":    "audifonos auriculares",
    "parlantes":      "parlante bluetooth",
    # Móviles y TV
    "celulares":      "celular smartphone",
    "tablets":        "tablet",
    "televisores":    "televisor smart tv",
    # Gaming
    "videojuegos":    "consola videojuegos",
    "smartwatch":     "smartwatch reloj inteligente",
}

FALABELLA_MAX_PAGES = 15   # 15 × 48 = 720 items máx por categoría
FALABELLA_PAGE_SIZE = 48   # Tamaño real que usa Falabella


def _falabella_fetch_page(
    session: requests.Session,
    keyword: str,
    page: int,
) -> list:
    """
    [A][B] SOLO searchTerm, sin categoryId.
    Mismo patrón que scraper_competencia (que funciona con 48 items/pág).
    """
    params = {
        "searchTerm": keyword,
        "page":       page,
        "pageSize":   FALABELLA_PAGE_SIZE,
        "sortBy":     "TOP_SELLERS",
        "channel":    "web",
        "locale":     "es_PE",
        "country":    "PE",
    }
    headers = {
        **HEADERS_JSON,
        "Referer": f"https://www.falabella.com.pe/falabella-pe/search?Ntt={keyword.replace(' ', '+')}",
        "Origin":  "https://www.falabella.com.pe",
    }
    try:
        resp = session.get(
            FALABELLA_SEARCH_API, params=params,
            headers=headers, timeout=TIMEOUT
        )
        if resp.status_code != 200:
            logger.warning(
                f"  [Falabella] HTTP {resp.status_code} keyword='{keyword}' p={page}"
            )
            return []
        data    = resp.json()
        results = (
            data.get("data", {}).get("results", []) or
            data.get("results", []) or
            data.get("products", [])
        )
        return results
    except requests.RequestException as e:
        logger.warning(f"  [Falabella] Error keyword='{keyword}' p={page}: {e}")
        return []
    except (ValueError, KeyError) as e:
        logger.warning(f"  [Falabella] JSON error p={page}: {e}")
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

    logger.info("[Falabella] Warm-up...")
    _warm_session(session, "https://www.falabella.com.pe/falabella-pe")
    time.sleep(1.0)

    for cat_name, keyword in FALABELLA_QUERIES.items():
        logger.info(f"[Falabella] '{cat_name}' → keyword='{keyword}'")
        cat_records = []

        for page in range(1, FALABELLA_MAX_PAGES + 1):
            raw_items = _falabella_fetch_page(session, keyword, page)

            if not raw_items:
                logger.debug(f"  p{page}: sin items → fin")
                break

            for raw in raw_items:
                record = _falabella_parse(raw, cat_name, batch_id, now_iso)
                if record:
                    cat_records.append(record)

            logger.info(f"  p{page}: +{len(raw_items)} → acum {len(cat_records)}")
            time.sleep(REQUEST_DELAY)

        all_records.extend(cat_records)
        logger.info(f"  ✅ '{cat_name}': {len(cat_records)} registros")

    logger.info(f"[Falabella] TOTAL: {len(all_records)} registros")
    return all_records


# ══════════════════════════════════════════════
# RIPLEY — [C] Deshabilitado temporalmente
# ══════════════════════════════════════════════
#
# CAUSA: Cloudflare JS Challenge en www.ripley.com.pe
# requests no ejecuta JavaScript → no obtiene cf_clearance
# El warm-up con requests puro NO resuelve el 403.
#
# SOLUCIÓN FUTURA: usar playwright/selenium headless, o
# esperar a que scraper_competencia implemente Ripley.
# ──────────────────────────────────────────────

RIPLEY_DISABLED_REASON = (
    "Cloudflare JS Challenge activo en www.ripley.com.pe. "
    "requests puro no puede obtener cf_clearance. "
    "Requiere playwright/selenium para bypass."
)


def scrape_ripley(batch_id: str) -> list:
    """[C] Deshabilitado — Cloudflare JS Challenge."""
    logger.warning(f"[Ripley] DESHABILITADO: {RIPLEY_DISABLED_REASON}")
    return []


# ══════════════════════════════════════════════
# HIRAOKA — [D] Detección automática de URL
# ══════════════════════════════════════════════
#
# 404 en todas las URLs con .html → probar múltiples formatos
# ──────────────────────────────────────────────

HIRAOKA_BASE = "https://www.hiraoka.com.pe"

# [D] Candidatos de URL por categoría — se prueba en orden
# hasta encontrar uno que responda 200
HIRAOKA_CATEGORIES = {
    "laptops": [
        "/laptops-y-accesorios/laptops",
        "/laptops-y-accesorios/laptops.html",
        "/computadoras/laptops",
        "/computadoras/laptops.html",
    ],
    "computadoras": [
        "/laptops-y-accesorios/computadoras-de-escritorio",
        "/laptops-y-accesorios/computadoras-de-escritorio.html",
        "/computadoras/computadoras-de-escritorio",
    ],
    "monitores": [
        "/laptops-y-accesorios/monitores",
        "/laptops-y-accesorios/monitores.html",
        "/computadoras/monitores",
    ],
    "impresoras": [
        "/impresoras-y-accesorios/impresoras",
        "/impresoras-y-accesorios/impresoras.html",
        "/impresoras/impresoras",
    ],
    "tablets": [
        "/celulares-y-tablets/tablets",
        "/celulares-y-tablets/tablets.html",
        "/tablets/tablets",
    ],
    "celulares": [
        "/celulares-y-tablets/celulares",
        "/celulares-y-tablets/celulares.html",
        "/celulares/celulares",
    ],
    "televisores": [
        "/television-y-video/televisores",
        "/television-y-video/televisores.html",
        "/tv-y-video/televisores",
    ],
    "auriculares": [
        "/audio/audifonos",
        "/audio/audifonos.html",
        "/audio/auriculares",
    ],
    "camaras": [
        "/camaras-y-accesorios/camaras-digitales",
        "/camaras-y-accesorios/camaras-digitales.html",
        "/camaras/camaras-digitales",
    ],
    "videojuegos": [
        "/videojuegos/consolas",
        "/videojuegos/consolas.html",
        "/gaming/consolas",
    ],
    "memorias": [
        "/laptops-y-accesorios/memorias-ram",
        "/laptops-y-accesorios/memorias-ram.html",
        "/computadoras/memorias-ram",
    ],
    "discos": [
        "/laptops-y-accesorios/discos-duros-y-ssd",
        "/laptops-y-accesorios/discos-duros-y-ssd.html",
        "/computadoras/discos-duros",
    ],
    "procesadores": [
        "/laptops-y-accesorios/procesadores",
        "/laptops-y-accesorios/procesadores.html",
        "/computadoras/procesadores",
    ],
}

HIRAOKA_MAX_PAGES      = 30
HIRAOKA_MIN_ITEMS_PAGE = 2

# Cache de URLs válidas descubiertas en este run
_hiraoka_valid_urls: dict = {}


def _hiraoka_discover_url(
    session: requests.Session, category: str, candidates: list
) -> Optional[str]:
    """
    [D] Prueba cada URL candidata hasta encontrar una que responda 200.
    Cachea el resultado para no repetir el discovery en páginas 2+.
    """
    if category in _hiraoka_valid_urls:
        return _hiraoka_valid_urls[category]

    headers = {
        **HEADERS_BROWSER,
        "Accept":         "text/html,application/xhtml+xml,*/*;q=0.8",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
    }
    for path in candidates:
        url = f"{HIRAOKA_BASE}{path}?p=1"
        try:
            resp = session.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
            if resp.status_code == 200:
                # Verificar que tiene productos
                soup  = BeautifulSoup(resp.text, "lxml")
                items = (
                    soup.select("li.product-item") or
                    soup.select("div.product-item-info") or
                    soup.select(".products-grid .item")
                )
                if items:
                    logger.info(f"  [Hiraoka] URL válida para '{category}': {path} ({len(items)} items)")
                    _hiraoka_valid_urls[category] = path
                    return path
                else:
                    logger.debug(f"  [Hiraoka] {path} → 200 pero sin productos")
            else:
                logger.debug(f"  [Hiraoka] {path} → HTTP {resp.status_code}")
        except Exception as e:
            logger.debug(f"  [Hiraoka] {path} → error: {e}")
        time.sleep(0.5)

    logger.warning(f"  [Hiraoka] No se encontró URL válida para '{category}'")
    logger.warning(f"  [Hiraoka] Candidatas probadas: {candidates}")
    return None


def _hiraoka_fetch_page(
    session: requests.Session,
    category: str,
    path: str,
    page: int
) -> list:
    url = f"{HIRAOKA_BASE}{path}?p={page}"
    headers = {
        **HEADERS_BROWSER,
        "Accept":         "text/html,application/xhtml+xml,*/*;q=0.8",
        "Referer":        f"{HIRAOKA_BASE}{path}?p={max(1, page-1)}",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1",
        "Cache-Control":  "max-age=0",
    }
    try:
        resp = session.get(url, headers=headers, timeout=TIMEOUT)
        if resp.status_code == 403:
            logger.warning(f"  [Hiraoka] 403 {path} p{page}")
            time.sleep(3.0)
            return []
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
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
    try:
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

        rating = None
        rating_tag = item.select_one(".rating-result, .rating-summary")
        if rating_tag:
            style = rating_tag.get("style", "")
            m     = re.search(r"width:\s*([\d.]+)%", style)
            if m:
                rating = round(float(m.group(1)) / 20, 1)

        sku = item.get("data-product-id", "")
        if not sku:
            sku_tag = item.select_one("[data-product-id]")
            if sku_tag:
                sku = sku_tag.get("data-product-id", "")
        if not sku and url:
            m = re.search(r"-(\d{5,})\.html", url)
            if m:
                sku = m.group(1)

        return {
            "batch_id":       batch_id,
            "timestamp":      now_iso,
            "source":         "hiraoka_pe",
            "category":       category,
            "sku":            str(sku),
            "brand":          _extract_brand(title),
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

    logger.info("[Hiraoka] Warm-up...")
    _warm_session(session, HIRAOKA_BASE)
    time.sleep(1.5)

    for cat_name, candidates in HIRAOKA_CATEGORIES.items():
        logger.info(f"[Hiraoka] Categoría: {cat_name}")
        cat_records = []

        # [D] Descubrir URL válida
        valid_path = _hiraoka_discover_url(session, cat_name, candidates)
        if not valid_path:
            logger.warning(f"  [Hiraoka] Saltando '{cat_name}' — sin URL válida")
            continue

        for page in range(1, HIRAOKA_MAX_PAGES + 1):
            items = _hiraoka_fetch_page(session, cat_name, valid_path, page)

            if not items or len(items) < HIRAOKA_MIN_ITEMS_PAGE:
                logger.debug(f"  p{page}: {len(items)} items → fin")
                break

            for item in items:
                record = _hiraoka_parse(item, cat_name, batch_id, now_iso)
                if record:
                    cat_records.append(record)

            logger.debug(f"  p{page}: +{len(items)} items")
            time.sleep(REQUEST_DELAY)

        all_records.extend(cat_records)
        logger.info(f"  ✅ {cat_name}: {len(cat_records)} registros")

    logger.info(f"[Hiraoka] TOTAL: {len(all_records)} registros")
    return all_records


# ══════════════════════════════════════════════
# SCRAPER UNIFICADO
# ══════════════════════════════════════════════

def scrape_local(batch_id: str) -> list:
    all_records = []

    logger.info("═" * 50)
    logger.info("  SCRAPING TIENDAS LOCALES PERÚ  v3.2")
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
        logger.info(f"[LOCAL PE] Deduplicados: {dupes} eliminados")

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
        for src in ["falabella_pe", "hiraoka_pe"]:
            ex = next((r for r in results if r["source"] == src), None)
            if ex:
                print(f"\nEjemplo {src}:")
                print(json.dumps(ex, ensure_ascii=False, indent=2))
