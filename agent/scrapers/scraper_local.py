#!/usr/bin/env python3
"""
scraper_local.py  v3.6
Scraper de tiendas locales Perú — Falabella, Hiraoka
(Ripley deshabilitado — 403 Cloudflare)

Fixes v3.6 (sobre v3.5):
  [L10] scrape_local(): parámetro mode agregado — alinea firma con main.py
        (main.py pasa mode= a todos los scrapers)
  [L11] scrape_falabella() / scrape_hiraoka(): session cerrada en finally
        — evita conexiones TCP huérfanas (consistente con [I18])
  [L12] _falabella_parse_api_data(): operador 'or' con data.get() corregido
        — la expresión `data.get("data",{}).get("results") if isinstance(data,dict)
        else None or []` tiene precedencia incorrecta; reescrito con variables
        intermedias explícitas
  [L13] scrape_local(): log de tiempo total al finalizar
        (consistente con [M4]/[M18]/[K10] del resto de scrapers)
  [L14] FALABELLA_API: migrado a v2 + zones=150101 (Lima Metropolitana)
        — consistente con FalabellaScraper de scraper_competencia v4.1 [SC11]
"""

import re
import json
import time
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# [L1] UA rotativo — consistente con scraper_camel v3.1 y scraper_competencia v4.1
try:
    from fake_useragent import UserAgent as _UA
    _ua_gen = _UA()
except ImportError:
    _ua_gen = None

_UA_FALLBACK = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

def _get_ua() -> str:
    return _ua_gen.random if _ua_gen else _UA_FALLBACK

# ──────────────────────────────────────────────
# CONFIGURACIÓN GLOBAL
# ──────────────────────────────────────────────
REQUEST_DELAY = 2.0
TIMEOUT       = 20

def _headers_json() -> dict:
    return {
        "User-Agent": _get_ua(),
        "Accept":     "application/json, text/plain, */*",
        "Referer":    "https://www.falabella.com.pe/",
    }

def _headers_html(referer: str = "") -> dict:
    return {
        "User-Agent":      _get_ua(),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
        "Referer":         referer,
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


# ──────────────────────────────────────────────
# Helpers compartidos
# ──────────────────────────────────────────────
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
            clean = (clean.replace(",", ".")
                     if len(parts) == 2 and len(parts[1]) <= 2
                     else clean.replace(",", ""))
        val = float(clean)
        return val if val > 0 else None
    except ValueError:
        return None


KNOWN_BRANDS = [
    "ASUS", "Acer", "Apple", "AMD", "Alienware", "AOC",
    "BenQ", "Brother", "Canon", "Corsair", "Creative",
    "Dell", "D-Link", "Epson", "Gigabyte", "G.Skill",
    "HP", "HyperX", "Hisense", "Honor", "Huawei", "Intel",
    "JBL", "Kingston", "Lenovo", "LG", "Logitech",
    "Microsoft", "MSI", "Motorola", "Nikon", "NVIDIA",
    "Panasonic", "Philips", "Razer", "Samsung", "Seagate",
    "Sony", "TP-Link", "Toshiba", "WD", "Western Digital", "Xiaomi",
]
_BRAND_RE = re.compile(
    r"\b(" + "|".join(re.escape(b) for b in KNOWN_BRANDS) + r")\b",
    re.IGNORECASE,
)

def _extract_brand(title: str) -> str:
    m = _BRAND_RE.search(title or "")
    return m.group(1).upper() if m else ""


# ══════════════════════════════════════════════
# FALABELLA
# ══════════════════════════════════════════════
# [L14] Migrado a v2 + zones=150101 (Lima Metropolitana)
#       consistente con FalabellaScraper de scraper_competencia v4.1 [SC11]
FALABELLA_API = "https://www.falabella.com.pe/s/browse/v2/listing/pe"

FALABELLA_QUERIES = {
    "laptops":        "laptop",
    "computadoras":   "computadora escritorio",
    "monitores":      "monitor",
    "memorias_ram":   "memoria ram",
    "discos_ssd":     "disco solido ssd nvme",
    "procesadores":   "procesador intel amd ryzen",
    "tarjetas_video": "tarjeta de video nvidia amd",
    "teclados":       "teclado mecanico gaming",
    "mouse":          "mouse gaming",
    "auriculares":    "audifonos auriculares",
    "parlantes":      "parlante bluetooth",
    "celulares":      "celular smartphone",
    "tablets":        "tablet",
    "televisores":    "televisor smart tv",
    "videojuegos":    "consola videojuegos",
    "smartwatch":     "smartwatch reloj inteligente",
}

FALABELLA_MAX_PAGES   = 15
FALABELLA_EMPTY_LIMIT = 2


def _falabella_fetch_page(
    session: requests.Session, query: str, page: int
) -> list:
    # Intento 1 — API JSON v2 [L14]
    try:
        params = {
            "Ntt":       query,
            "page":      page,
            "imageSize": "zoom",
            "zones":     "150101",   # [L14] Lima Metropolitana
        }
        resp = session.get(
            FALABELLA_API, params=params,
            headers=_headers_json(), timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            items = _falabella_parse_api_data(resp.json())
            if items:
                return items
        else:
            logger.debug(
                f"  [Falabella] API HTTP {resp.status_code} "
                f"'{query}' p{page}"
            )
    except Exception as e:
        logger.debug(f"  [Falabella] API error '{query}' p{page}: {e}")

    # Intento 2 — HTML __NEXT_DATA__
    try:
        url  = (f"https://www.falabella.com.pe/falabella-pe/search"
                f"?Ntt={requests.utils.quote(query)}&page={page}")
        resp = session.get(
            url,
            headers=_headers_html("https://www.falabella.com.pe/"),
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            m = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">'
                r'(.*?)</script>',
                resp.text, re.DOTALL,
            )
            if m:
                items = _falabella_parse_api_data(json.loads(m.group(1)))
                if items:
                    return items
    except Exception as e:
        logger.debug(f"  [Falabella] HTML error '{query}' p{page}: {e}")

    return []


def _falabella_parse_api_data(data: dict) -> list:
    """
    [L12] Operador 'or' con data.get() reescrito con variables intermedias
    explícitas — la expresión original tenía precedencia incorrecta:
      `data.get("data",{}).get("results") if isinstance(data,dict) else None or []`
    se evaluaba como:
      `(data.get(...)) if (...) else (None or [])` → siempre retornaba []
    """
    if not isinstance(data, dict):
        return []

    # [L12] Variables intermedias — precedencia explícita
    products = data.get("results")
    if not products:
        products = data.get("products")
    if not products:
        nested = data.get("data", {})
        if isinstance(nested, dict):
            products = nested.get("results") or nested.get("products")

    if products and isinstance(products, list):
        return [
            p for p in products
            if isinstance(p, dict) and
            any(k in p for k in ["displayName", "productName", "name", "title"]) and
            any(k in p for k in ["prices", "price", "offerPrice"])
        ]

    # Fallback recursivo
    def extract_products(obj, depth=0):
        if depth > 4:
            return []
        found = []
        if isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    if any(k in item for k in
                           ["displayName", "productName", "name", "title"]):
                        if any(k in item for k in
                               ["prices", "price", "offerPrice"]):
                            found.append(item)
                    found.extend(extract_products(item, depth + 1))
        elif isinstance(obj, dict):
            for v in obj.values():
                found.extend(extract_products(v, depth + 1))
        return found

    return extract_products(data)


def _falabella_parse_product(
    p: dict, category: str, batch_id: str, now_iso: str
) -> Optional[dict]:
    try:
        pid   = p.get("productId") or p.get("id") or p.get("skuId") or ""
        title = (p.get("displayName") or p.get("productName") or
                 p.get("name") or p.get("title") or "")
        if not title:
            return None

        price_pen  = 0.0
        price_orig = 0.0
        prices_obj = p.get("prices") or p.get("price") or {}

        if isinstance(prices_obj, list):
            for pr in prices_obj:
                if isinstance(pr, dict):
                    val    = pr.get("price") or pr.get("value") or 0
                    label  = str(pr.get("label", "")).lower()
                    parsed = _parse_price_str(str(val))
                    if parsed:
                        if "oferta" in label or "precio" in label or not label:
                            price_pen  = parsed
                        elif "normal" in label or "original" in label:
                            price_orig = parsed
        elif isinstance(prices_obj, dict):
            for key in ["offerPrice", "salePrice", "normalPrice",
                        "originalPrice", "price"]:
                val = prices_obj.get(key)
                if val:
                    parsed = _parse_price_str(str(val))
                    if parsed:
                        price_pen = parsed
                        break
            for key in ["normalPrice", "originalPrice", "regularPrice"]:
                val = prices_obj.get(key)
                if val:
                    parsed = _parse_price_str(str(val))
                    if parsed:
                        price_orig = parsed
                        break

        if price_pen == 0:
            for key in ["offerPrice", "salePrice", "price", "currentPrice"]:
                val = p.get(key)
                if val:
                    parsed = _parse_price_str(str(val))
                    if parsed:
                        price_pen = parsed
                        break

        if price_pen <= 0:
            return None

        discount = 0.0
        if price_orig > 0 and price_pen > 0 and price_orig > price_pen:
            discount = round((price_orig - price_pen) / price_orig * 100, 1)

        brand    = p.get("brand") or p.get("brandName") or _extract_brand(title)
        url_path = (p.get("url") or p.get("pdpUrl") or
                    p.get("productUrl") or "")
        url      = (f"https://www.falabella.com.pe{url_path}"
                    if url_path and not url_path.startswith("http")
                    else url_path)

        # [L3] reviews convertido a int — maneja strings '1,234'
        reviews_raw = p.get("totalReviews") or p.get("reviewCount")
        reviews     = None
        if reviews_raw is not None:
            try:
                reviews = int(
                    str(reviews_raw).replace(",", "").replace(".", "")
                )
            except (ValueError, TypeError):
                reviews = None

        return {
            "batch_id":       batch_id,
            "timestamp":      now_iso,
            "source":         "falabella_pe",
            "category":       category,
            "sku":            str(pid),
            "brand":          str(brand)[:100],
            "title":          str(title)[:200],
            "price_pen":      round(price_pen, 2),
            "price_orig_pen": round(price_orig, 2),
            "discount_pct":   discount,
            "rating":         float(
                p.get("rating") or p.get("averageRating") or 0
            ),
            "reviews":        reviews,
            "url":            str(url)[:300],
        }
    except (TypeError, ValueError, KeyError, ZeroDivisionError) as e:
        logger.debug(f"  [Falabella] Parse error: {e}")
        return None


def scrape_falabella(batch_id: str) -> list:
    all_records = []
    now_iso     = datetime.now(timezone.utc).isoformat()
    session     = _make_session()

    try:   # [L11] session cerrada en finally
        for cat_name, keyword in FALABELLA_QUERIES.items():
            logger.info(f"[Falabella] '{cat_name}' → '{keyword}'")
            cat_records = []
            seen_ids    = set()
            empty_pages = 0

            for page in range(1, FALABELLA_MAX_PAGES + 1):
                raw_items = _falabella_fetch_page(session, keyword, page)

                if not raw_items:
                    empty_pages += 1
                    logger.debug(
                        f"  p{page}: sin items "
                        f"(empty_pages={empty_pages})"
                    )
                    if empty_pages >= FALABELLA_EMPTY_LIMIT:
                        logger.info(
                            f"  p{page}: early-stop — "
                            f"{empty_pages} páginas vacías"
                        )
                        break
                    continue

                added = 0
                for raw in raw_items:
                    pid = (raw.get("productId") or raw.get("id") or
                           raw.get("skuId") or "")
                    if pid and pid in seen_ids:
                        continue
                    if pid:
                        seen_ids.add(pid)
                    record = _falabella_parse_product(
                        raw, cat_name, batch_id, now_iso
                    )
                    if record:
                        cat_records.append(record)
                        added += 1

                if added == 0:
                    empty_pages += 1
                    logger.info(
                        f"  p{page}: +{len(raw_items)} raw → +0 nuevos "
                        f"(todos dupes, empty_pages={empty_pages})"
                    )
                    if empty_pages >= FALABELLA_EMPTY_LIMIT:
                        logger.info(
                            f"  p{page}: early-stop — "
                            f"{empty_pages} páginas sin nuevos"
                        )
                        break
                else:
                    empty_pages = 0
                    logger.info(
                        f"  p{page}: +{len(raw_items)} raw → "
                        f"+{added} válidos (acum {len(cat_records)})"
                    )

                time.sleep(REQUEST_DELAY)

            all_records.extend(cat_records)
            logger.info(f"  ✅ '{cat_name}': {len(cat_records)} registros")

    finally:
        session.close()   # [L11]

    logger.info(f"[Falabella] TOTAL: {len(all_records)} registros")
    return all_records


# ══════════════════════════════════════════════
# RIPLEY — Deshabilitado (403 Cloudflare)
# ══════════════════════════════════════════════
def scrape_ripley(batch_id: str) -> list:
    # [L8] Warning solo en llamada directa
    logger.warning(
        "[Ripley] DESHABILITADO — 403 Cloudflare JS Challenge. "
        "Requiere playwright headless para bypass."
    )
    return []


# ══════════════════════════════════════════════
# HIRAOKA
# ══════════════════════════════════════════════
HIRAOKA_BASE = "https://www.hiraoka.com.pe"

HIRAOKA_CATEGORIES = {
    "laptops":      None,
    "computadoras": None,
    "monitores":    None,
    "impresoras":   None,
    "tablets":      None,
    "celulares":    None,
    "televisores":  None,
    "auriculares":  None,
}

HIRAOKA_SEARCH_KEYWORDS = {
    "laptops":      "laptop",
    "computadoras": "computadora escritorio",
    "monitores":    "monitor",
    "impresoras":   "impresora",
    "tablets":      "tablet",
    "celulares":    "celular",
    "televisores":  "televisor",
    "auriculares":  "audifonos",
}

HIRAOKA_MAX_PAGES      = 30
HIRAOKA_MIN_ITEMS_PAGE = 2
HIRAOKA_EMPTY_LIMIT    = 3   # [L4]


def _hiraoka_fetch_url(session: requests.Session, url: str) -> list:
    # [L5] Fallback a html.parser si lxml no está instalado
    try:
        from bs4 import FeatureNotFound as _FNF
    except ImportError:
        _FNF = Exception

    headers = _headers_html(HIRAOKA_BASE + "/")
    try:
        resp = session.get(url, headers=headers, timeout=25)
        if resp.status_code == 404:
            logger.debug(f"  [Hiraoka] 404: {url}")
            return []
        if resp.status_code != 200:
            logger.warning(f"  [Hiraoka] HTTP {resp.status_code}: {url}")
            return []

        # [L5] Intentar lxml primero, fallback a html.parser
        try:
            soup = BeautifulSoup(resp.text, "lxml")
        except _FNF:
            logger.debug("  [Hiraoka] lxml no disponible — usando html.parser")
            soup = BeautifulSoup(resp.text, "html.parser")

        cards = []
        for sel in [
            "li.product-item",
            "div.product-item-info",
            "div[class*='product-item']",
            "li[class*='item product']",
        ]:
            cards = soup.select(sel)
            if cards:
                break
        return cards
    except Exception as e:
        logger.warning(f"  [Hiraoka] Error {url}: {e}")
        return []


def _hiraoka_parse_card(
    card, category: str, batch_id: str, now_iso: str
) -> Optional[dict]:
    try:
        title_el = (
            card.select_one("a.product-item-link") or
            card.select_one("strong.product-item-name a") or
            card.select_one("a[class*='product-item-link']") or
            card.select_one("span[class*='product-name']")
        )
        if not title_el:
            return None
        title = title_el.get_text(strip=True)
        if not title:
            return None

        final_el = (
            card.select_one(
                "span[data-price-type='finalPrice'] span.price"
            ) or
            card.select_one("span[class*='price-final'] span.price") or
            card.select_one("span.special-price span.price") or
            card.select_one("span.price")
        )
        price_pen = _parse_price_str(
            final_el.get_text(strip=True) if final_el else None
        ) or 0.0

        orig_el = (
            card.select_one(
                "span[data-price-type='oldPrice'] span.price"
            ) or
            card.select_one("span.old-price span.price") or
            card.select_one("span[class*='regular-price'] span.price")
        )
        price_orig = _parse_price_str(
            orig_el.get_text(strip=True) if orig_el else None
        ) or 0.0

        if price_pen <= 0:
            return None

        discount = 0.0
        if price_orig > price_pen > 0:
            discount = round((price_orig - price_pen) / price_orig * 100, 1)

        link_el  = (card.select_one("a.product-item-link") or
                    card.select_one("a[href*='hiraoka']"))
        item_url = link_el.get("href", "") if link_el else ""
        if item_url and not item_url.startswith("http"):
            item_url = HIRAOKA_BASE + item_url

        brand_el = (
            card.select_one("div.product-item-brand") or
            card.select_one("span[class*='brand']")
        )
        brand = (brand_el.get_text(strip=True) if brand_el
                 else _extract_brand(title))

        # SKU: data-product-id → selector interno → [L6] ÚLTIMO número de URL
        sku = card.get("data-product-id", "")
        if not sku:
            sku_tag = card.select_one("[data-product-id]")
            if sku_tag:
                sku = sku_tag.get("data-product-id", "")
        if not sku and item_url:
            # [L6] Tomar el último match — evita capturar número de categoría
            matches = re.findall(r"-(\d{5,})(?=\.html|$)", item_url)
            if matches:
                sku = matches[-1]

        rating    = 0.0
        rating_el = card.select_one(
            "span.rating-result, div[class*='rating']"
        )
        if rating_el:
            style = rating_el.get("style", "")
            m     = re.search(r"width:\s*([\d.]+)%", style)
            if m:
                rating = round(float(m.group(1)) / 20, 1)

        return {
            "batch_id":       batch_id,
            "timestamp":      now_iso,
            "source":         "hiraoka_pe",
            "category":       category,
            "sku":            str(sku),
            "brand":          str(brand)[:100],
            "title":          str(title)[:200],
            "price_pen":      round(price_pen, 2),
            "price_orig_pen": round(price_orig, 2),
            "discount_pct":   discount,
            "rating":         rating,
            "reviews":        None,
            "url":            str(item_url)[:300],
        }
    except (TypeError, ValueError, AttributeError, ZeroDivisionError) as e:
        logger.debug(f"  [Hiraoka] Parse error: {e}")
        return None


def scrape_hiraoka(batch_id: str) -> list:
    all_records = []
    now_iso     = datetime.now(timezone.utc).isoformat()
    session     = _make_session()

    try:   # [L11] session cerrada en finally
        for cat_name, cat_path in HIRAOKA_CATEGORIES.items():
            logger.info(f"[Hiraoka] Categoría: {cat_name}")
            cat_records = []
            seen_skus   = set()
            seen_fps    = set()   # [L7] fingerprints para items sin SKU
            empty_pages = 0

            for page in range(1, HIRAOKA_MAX_PAGES + 1):
                if cat_path:
                    url = f"{HIRAOKA_BASE}{cat_path}?p={page}"
                else:
                    keyword = HIRAOKA_SEARCH_KEYWORDS.get(cat_name, cat_name)
                    url = (f"{HIRAOKA_BASE}/catalogsearch/result/"
                           f"?q={requests.utils.quote(keyword)}&p={page}")

                cards = _hiraoka_fetch_url(session, url)

                if not cards or len(cards) < HIRAOKA_MIN_ITEMS_PAGE:
                    empty_pages += 1
                    logger.debug(
                        f"  p{page}: {len(cards)} cards "
                        f"(empty_pages={empty_pages})"
                    )
                    if empty_pages >= HIRAOKA_EMPTY_LIMIT:
                        logger.info(
                            f"  p{page}: early-stop — "
                            f"{empty_pages} páginas vacías"
                        )
                        break
                    continue

                added = 0
                for card in cards:
                    record = _hiraoka_parse_card(
                        card, cat_name, batch_id, now_iso
                    )
                    if record:
                        sku = record["sku"]
                        if sku:
                            if sku in seen_skus:
                                continue
                            seen_skus.add(sku)
                        else:
                            # [L7] Sin SKU → fingerprint title[:80]+price
                            fp = hashlib.md5(
                                f"{record['title'][:80]}|"
                                f"{record['price_pen']}".encode()
                            ).hexdigest()[:12]
                            if fp in seen_fps:
                                continue
                            seen_fps.add(fp)
                        cat_records.append(record)
                        added += 1

                if added == 0:
                    empty_pages += 1
                    logger.info(
                        f"  p{page}: +{len(cards)} cards → +0 nuevos "
                        f"(todos dupes, empty_pages={empty_pages})"
                    )
                    if empty_pages >= HIRAOKA_EMPTY_LIMIT:
                        logger.info(
                            f"  p{page}: early-stop — "
                            f"{empty_pages} páginas sin nuevos"
                        )
                        break
                else:
                    empty_pages = 0
                    logger.info(
                        f"  p{page}: +{len(cards)} cards → "
                        f"+{added} válidos (acum {len(cat_records)})"
                    )

                time.sleep(REQUEST_DELAY)

            all_records.extend(cat_records)
            logger.info(f"  ✅ {cat_name}: {len(cat_records)} registros")

    finally:
        session.close()   # [L11]

    logger.info(f"[Hiraoka] TOTAL: {len(all_records)} registros")
    return all_records


# ══════════════════════════════════════════════
# SCRAPER UNIFICADO
# ══════════════════════════════════════════════
def scrape_local(batch_id: str, mode: str = "normal") -> list:
    """
    Ejecuta Falabella + Hiraoka en secuencia.
    [L8]  Ripley deshabilitado — warning emitido UNA vez aquí.
    [L10] Parámetro mode agregado — main.py lo pasa a todos los scrapers.
    [L13] Log de tiempo total al finalizar.
    Deduplica por (source, sku) + fingerprint para items sin SKU.
    """
    t_start = time.time()   # [L13]

    all_records = []

    logger.info("═" * 50)
    logger.info("  SCRAPING TIENDAS LOCALES PERÚ  v3.6")
    logger.info("═" * 50)

    # [L8] Warning de Ripley una sola vez, fuera del loop
    logger.warning(
        "[Ripley] DESHABILITADO — 403 Cloudflare JS Challenge. "
        "Requiere playwright headless para bypass."
    )

    for name, fn in [
        ("Falabella", scrape_falabella),
        ("Hiraoka",   scrape_hiraoka),
    ]:
        try:
            records = fn(batch_id)
            all_records.extend(records)
            logger.info(f"[{name}] → {len(records)} registros")
        except Exception as e:
            logger.error(f"[{name}] Error fatal: {e}", exc_info=True)

    # Deduplicar por (source, sku) — items sin SKU por fingerprint
    seen_keys = set()
    seen_fps  = set()
    unique    = []

    for r in all_records:
        sku = str(r.get("sku", ""))
        if sku:
            key = (r.get("source", ""), sku)
            if key not in seen_keys:
                seen_keys.add(key)
                unique.append(r)
        else:
            # [L7] Sin SKU → fingerprint title[:80]+price
            fp = hashlib.md5(
                f"{r.get('title','')[:80]}|"
                f"{r.get('price_pen',0)}".encode()
            ).hexdigest()[:12]
            if fp not in seen_fps:
                seen_fps.add(fp)
                unique.append(r)

    dupes = len(all_records) - len(unique)
    if dupes:
        logger.info(f"[LOCAL PE] Deduplicados: {dupes} eliminados")

    # [L13] Log de tiempo total
    elapsed = time.time() - t_start
    logger.info(
        f"[LOCAL PE] TOTAL COMBINADO: {len(unique)} registros únicos — "
        f"⏱ {elapsed/60:.1f} min"
    )
    return unique


# ──────────────────────────────────────────────
# STANDALONE
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    # [L9] datetime con timezone explícita
    test_batch = f"test_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    results    = scrape_local(test_batch)
    print(f"\nTotal registros: {len(results)}")
    if results:
        import json as _json
        for src in ["falabella_pe", "hiraoka_pe"]:
            ex = next((r for r in results if r["source"] == src), None)
            if ex:
                print(f"\nEjemplo {src}:")
                print(_json.dumps(ex, ensure_ascii=False, indent=2))
