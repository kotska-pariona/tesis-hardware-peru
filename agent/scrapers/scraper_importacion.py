"""
scraper_importacion.py  v4.2
════════════════════════════
Fuentes de PRECIO DE IMPORTACIÓN (referencia precio piso USA):
  - Amazon USA    (HTML + Session/Retry + CAPTCHA detection)
  - AliExpress    (JSON embebido con brackets balanceados + fallback HTML)

NOTA: eBay eliminado de este scraper — usar scraper_ebay.py (Browse API REST)
      para evitar duplicación de source='ebay_usa' en el MASTER.

Fixes v4.2 (sobre v4.1):
  [I17] scrape_importacion(): parámetro mode agregado — alinea firma con main.py
        (main.py pasa mode= a todos los scrapers)
  [I18] AmazonScraper/AliExpressScraper: session cerrada en __del__ para evitar
        conexiones TCP huérfanas en runs largos (37 categorías × 2 queries)
  [I19] _dedup(): float() con try/except — evita ValueError si price_usd es
        string no numérico (consistente con [SC24] de scraper_competencia)
  [I20] scrape_importacion(): dry_run retorna [] en lugar de unique_records
        (unique_records siempre vacío en dry_run — evita retorno engañoso)
  [I21] CATEGORY_QUERIES: PSU query "1000w 80 plus platinum psu atx 3.0" →
        "1000w 80 plus platinum power supply atx 3.0" — Amazon indexa
        "power supply", no "psu", en búsqueda de texto libre
"""

import os
import re
import time
import json
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# ── Constantes ─────────────────────────────────────────────────────────
_DEFAULT_OUTPUT = str(Path(__file__).resolve().parent.parent.parent / "data" / "raw")
OUTPUT_DIR         = Path(os.getenv("OUTPUT_DIR", _DEFAULT_OUTPUT))
MAX_PAGES          = int(os.getenv("MAX_PAGES_IMPORT", "5"))
DELAY_REQ          = float(os.getenv("DELAY_REQ", "2.5"))
DELAY_CAT          = float(os.getenv("DELAY_CAT", "5.0"))
MAX_RETRIES_QUERY  = int(os.getenv("MAX_RETRIES_QUERY", "2"))
MAX_QUERIES_IMPORT = int(os.getenv("MAX_QUERIES_IMPORT", "2"))  # [I13]

# [I10] SHIPPING_EST_DEFAULT desde config.py — consistente con FLETE_BASE_USD
try:
    from configuracion.config import (
        FLETE_BASE_USD   as _FLETE_BASE,
        FLETE_POR_KG_USD as _FLETE_KG,
    )
    SHIPPING_EST_DEFAULT = _FLETE_BASE   # 35.0 en config v2.3
except ImportError:
    SHIPPING_EST_DEFAULT = 35.0          # fallback explícito

# [I2] Shipping estimado por categoría (USD) — basado en peso/volumen
SHIPPING_EST_BY_CATEGORY = {
    "CPU":         18.0,
    "GPU":         38.0,   # [I10] mayor peso real
    "RAM":          8.0,
    "SSD":          8.0,
    "MOTHERBOARD": 25.0,
    "PSU":         32.0,
    "COOLER":      22.0,
    "CASE":        50.0,   # [I10] voluminoso
}

# [I1] Strings de detección de CAPTCHA
AMAZON_CAPTCHA_STRINGS = [
    "Enter the characters you see below",
    "api-services-support@amazon.com",
    "make sure you're not a robot",
    "Type the characters you see in this image",
    "Sorry, we just need to make sure you're not a robot",
]

# [I16] USER_AGENTS actualizados — Chrome 136 (julio 2026)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0",
]
_ua_idx = 0

def _next_ua() -> str:
    global _ua_idx
    ua = USER_AGENTS[_ua_idx % len(USER_AGENTS)]
    _ua_idx += 1
    return ua

def _headers(referer: str = "https://www.google.com") -> dict:
    return {
        "User-Agent":                _next_ua(),
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":           "en-US,en;q=0.9",
        "Accept-Encoding":           "gzip, deflate, br",
        "Referer":                   referer,
        "DNT":                       "1",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

def _json_headers(referer: str = "") -> dict:
    return {
        "User-Agent": _next_ua(),
        "Accept":     "application/json, text/plain, */*",
        "Referer":    referer,
        "Connection": "keep-alive",
    }

def _make_session() -> requests.Session:
    session = requests.Session()
    retry   = Retry(
        total=3, backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    return session

def _parse_price(raw: str) -> float:
    """
    [I12] Limpieza explícita de símbolos de moneda antes del regex.
    Soporta: USD, US$, €, £, S/., y variantes con espacios.
    """
    if not raw:
        return 0.0
    cleaned = re.sub(r"(?:US\s*\$|USD|EUR|€|£|GBP|S/\.?\s*)", "", str(raw).strip())
    cleaned = re.sub(r"[^\d.,]", "", cleaned.strip())
    if not cleaned:
        return 0.0
    if re.search(r"\d{1,3}\.\d{3},\d{2}$", cleaned):
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        val = float(cleaned)
        return val if val > 0 else 0.0
    except ValueError:
        return 0.0

def _dedup(records: list) -> list:
    seen = set()
    out  = []
    for r in records:
        # [I19] float() con try/except — evita ValueError en price_usd no numérico
        try:
            price = float(r.get("price_usd", 0) or 0)
        except (ValueError, TypeError):
            price = 0.0
        key = (
            f"{r.get('source')}|{r.get('category')}|"
            f"{r.get('title','')}|{price}"
        )
        fp = hashlib.md5(key.encode()).hexdigest()[:16]
        if fp not in seen and price > 0:
            seen.add(fp)
            out.append(r)
    return out


# ── [I4] Extractor de brackets balanceados ────────────────────────────
def _extract_balanced(
    text: str, start_idx: int, open_ch: str, close_ch: str
) -> Optional[str]:
    depth   = 0
    in_str  = False
    escaped = False
    i       = start_idx
    while i < len(text):
        ch = text[i]
        if escaped:
            escaped = False
        elif ch == '\\' and in_str:
            escaped = True
        elif ch == '"' and not escaped:
            in_str = not in_str
        elif not in_str:
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return text[start_idx: i + 1]
        i += 1
    return None

def _find_balanced_block(
    content: str, marker: str, open_ch: str
) -> Optional[str]:
    close_ch = '}' if open_ch == '{' else ']'
    idx = content.find(marker)
    while idx != -1:
        start = content.find(open_ch, idx)
        if start == -1:
            break
        block = _extract_balanced(content, start, open_ch, close_ch)
        if block:
            return block
        idx = content.find(marker, idx + 1)
    return None


# ── [I9] CATEGORY_QUERIES — actualizado 2025-2026 ─────────────────────
CATEGORY_QUERIES = {
    "CPU": [
        "intel core ultra 9 285k processor",
        "intel core ultra 7 265k processor",
        "intel core i7 14700k processor",
        "amd ryzen 9 9950x processor",
        "amd ryzen 7 9700x processor",
    ],
    "GPU": [
        "nvidia rtx 5080 graphics card",
        "nvidia rtx 5070 graphics card",
        "nvidia rtx 4070 graphics card",
        "amd radeon rx 9070 xt graphics card",
        "amd radeon rx 7900 xt graphics card",
    ],
    "RAM": [
        "ddr5 32gb 6000mhz ram memory",
        "ddr5 64gb 6400mhz ram memory",
        "ddr4 32gb 3600mhz ram memory",
        "corsair vengeance ddr5 ram",
        "g.skill trident z5 ddr5",
    ],
    "SSD": [
        "nvme ssd 2tb m.2 pcie 5.0",
        "nvme ssd 1tb m.2 pcie 4.0",
        "samsung 990 pro nvme ssd",
        "western digital black sn850x",
        "crucial t705 nvme ssd",
    ],
    "MOTHERBOARD": [
        "intel z890 motherboard atx",
        "intel z790 motherboard atx",
        "amd x870e motherboard atx",
        "amd b650 motherboard micro atx",
        "asus rog strix z890 motherboard",
    ],
    "PSU": [
        # [I21] "psu" → "power supply" — Amazon indexa el término completo
        "1000w 80 plus platinum power supply atx 3.0",
        "850w 80 plus gold power supply",
        "corsair rm1000x power supply",
        "seasonic focus gx 850w",
        "be quiet straight power 12 1000w",
    ],
    "COOLER": [
        "360mm aio liquid cooler",
        "240mm aio liquid cpu cooler",
        "noctua nh-d15 g2 cpu cooler",
        "arctic liquid freezer iii 360",
        "be quiet dark rock pro 5",
    ],
    "CASE": [
        "mid tower atx pc case tempered glass",
        "lian li lancool 216 case",
        "fractal design north case",
        "nzxt h9 flow case",
        "corsair 5000d airflow case",
    ],
}

AMAZON_CATEGORY_NODES = {
    "CPU":         "n:541966",
    "GPU":         "n:284822",
    "RAM":         "n:172500",
    "SSD":         "n:1292110011",
    "MOTHERBOARD": "n:1048424",
    "PSU":         "n:1161760",
    "COOLER":      "n:3012290011",
    "CASE":        "n:1161758",
}


# ══════════════════════════════════════════════════════════════════════
# SCRAPER 1 — AMAZON USA
# ══════════════════════════════════════════════════════════════════════
class AmazonScraper:
    BASE = "https://www.amazon.com/s"

    def __init__(self):
        self.session = _make_session()

    def __del__(self):
        # [I18] Cerrar session al destruir el objeto — evita TCP huérfanas
        try:
            self.session.close()
        except Exception:
            pass

    def search(self, query: str, category: str, batch_id: str,
               max_pages: int = MAX_PAGES) -> tuple[list, bool]:
        """
        [I11] Retorna (items, captcha_detected).
        captcha_detected=True → scrape_importacion() hace break inmediato.
        """
        items          = []
        captcha_global = False

        for page in range(1, max_pages + 1):
            log.info(f"  [Amazon] {category} | '{query[:40]}' | pág {page}")
            page_items, captcha = self._fetch_page(query, page, category, batch_id)
            items.extend(page_items)
            log.info(f"    → {len(page_items)} items (total: {len(items)})")
            if captcha:
                captcha_global = True
                log.warning("    Amazon CAPTCHA — abortando query")
                break
            if not page_items:
                break
            time.sleep(DELAY_REQ + (page * 0.3))

        return items, captcha_global

    def _fetch_page(self, query: str, page: int, category: str,
                    batch_id: str) -> tuple[list, bool]:
        params  = {"k": query, "page": page, "ref": f"sr_pg_{page}"}
        rh_node = AMAZON_CATEGORY_NODES.get(category)
        if rh_node:
            params["rh"] = rh_node
        try:
            resp = self.session.get(
                self.BASE, params=params,
                headers=_headers("https://www.amazon.com/"),
                timeout=20
            )
            if resp.status_code == 503:
                log.warning("    Amazon 503 — posible CAPTCHA, esperando 30s")
                time.sleep(30)
                return [], True
            if resp.status_code != 200:
                log.warning(f"    Amazon HTTP {resp.status_code}")
                return [], False
            if any(s in resp.text for s in AMAZON_CAPTCHA_STRINGS):
                log.warning("    Amazon CAPTCHA detectado — saltando query")
                return [], True
            return self._parse(resp.text, category, batch_id), False
        except Exception as e:
            log.error(f"    Amazon error: {e}")
            return [], False

    def _parse(self, html: str, category: str, batch_id: str) -> list:
        soup         = BeautifulSoup(html, "html.parser")
        items        = []
        ts           = datetime.now(timezone.utc).isoformat()
        price_date   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        shipping_est = SHIPPING_EST_BY_CATEGORY.get(category, SHIPPING_EST_DEFAULT)

        for card in soup.select("div[data-component-type='s-search-result']"):
            try:
                title_el = (card.select_one("h2 span") or
                            card.select_one("h2 a span"))
                title    = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue

                asin    = card.get("data-asin", "")
                link_el = card.select_one("h2 a")
                url     = (f"https://www.amazon.com{link_el['href']}"
                           if link_el and link_el.get("href") else "")

                price_usd = 0.0
                for sel in [
                    "span.a-price > span.a-offscreen",
                    "span[data-a-color='base'] span.a-offscreen",
                    "span[data-a-color='price'] span.a-offscreen",
                    "span.a-price-whole",
                ]:
                    el = card.select_one(sel)
                    if el:
                        price_usd = _parse_price(el.get_text(strip=True))
                        if price_usd > 0:
                            break

                shipping_usd = shipping_est
                for sel in [
                    "span[aria-label='Amazon Prime']",
                    "i.a-icon-prime",
                    "span[data-csa-c-content-id='FREE_SHIPPING']",
                ]:
                    try:
                        if card.select_one(sel):
                            shipping_usd = 0.0
                            break
                    except Exception:
                        continue
                if shipping_usd > 0:
                    card_text = card.get_text()
                    if "FREE delivery" in card_text or "FREE Shipping" in card_text:
                        shipping_usd = 0.0

                rating  = 0.0
                rate_el = card.select_one("span.a-icon-alt")
                if rate_el:
                    m = re.search(r"([\d.]+) out of", rate_el.get_text())
                    if m:
                        rating = float(m.group(1))

                reviews = 0
                rev_el  = (
                    card.select_one(
                        "span[aria-label$='stars'] + span a span"
                    ) or
                    card.select_one(
                        "a[href*='#customerReviews'] span.a-size-base"
                    )
                )
                if rev_el:
                    raw_rev = (rev_el.get_text(strip=True)
                               .replace(",", "").replace(".", ""))
                    try:
                        reviews = int(raw_rev)
                    except ValueError:
                        pass

                if price_usd > 0:
                    items.append({
                        "batch_id":     batch_id,
                        "source":       "amazon_usa",
                        "category":     category,
                        "title":        title[:200],
                        "sku":          asin,      # [I14] asin_sku eliminado
                        "price_usd":    round(price_usd, 2),
                        "price_date":   price_date,
                        "shipping_usd": shipping_usd,
                        "total_usd":    round(price_usd + shipping_usd, 2),
                        "url":          url[:300],
                        "rating":       rating,
                        "reviews":      reviews,
                        "timestamp":    ts,
                    })
            except Exception as e:
                log.debug(f"    parse card error: {e}")
                continue
        return items


# ══════════════════════════════════════════════════════════════════════
# SCRAPER 2 — ALIEXPRESS
# ══════════════════════════════════════════════════════════════════════
class AliExpressScraper:
    SEARCH_URL = "https://www.aliexpress.com/wholesale"

    def __init__(self):
        self.session = _make_session()

    def __del__(self):
        # [I18] Cerrar session al destruir el objeto — evita TCP huérfanas
        try:
            self.session.close()
        except Exception:
            pass

    def search(self, query: str, category: str, batch_id: str,
               max_pages: int = MAX_PAGES) -> tuple[list, bool]:
        """[I11] Retorna (items, captcha_detected) — AliExpress no tiene CAPTCHA típico."""
        items = []
        for page in range(1, max_pages + 1):
            log.info(f"  [AliExpress] {category} | '{query[:40]}' | pág {page}")
            page_items = self._fetch_page(query, page, category, batch_id)
            items.extend(page_items)
            log.info(f"    → {len(page_items)} items (total: {len(items)})")
            if not page_items:
                break
            time.sleep(DELAY_REQ)
        return items, False   # AliExpress no tiene CAPTCHA flag

    def _fetch_page(self, query: str, page: int, category: str,
                    batch_id: str) -> list:
        try:
            params = {
                "SearchText": query,
                "page":       page,
                "g":          "y",
                "isrefine":   "y",
            }
            resp = self.session.get(
                self.SEARCH_URL, params=params,
                headers=_headers("https://www.aliexpress.com/"),
                timeout=25
            )
            if resp.status_code != 200:
                log.warning(f"    AliExpress HTTP {resp.status_code}")
                return []
            items = self._extract_from_script(resp.text, category, batch_id)
            if items:
                return items
            return self._parse_html_fallback(resp.text, category, batch_id)
        except Exception as e:
            log.error(f"    AliExpress error: {e}")
            return []

    def _extract_from_script(self, html: str, category: str,
                              batch_id: str) -> list:
        ts    = datetime.now(timezone.utc).isoformat()
        items = []

        block = _find_balanced_block(html, "window.runParams", '{')
        if block:
            try:
                data         = json.loads(block)
                product_list = (
                    self._dig(data, ["data", "root", "fields", "mods",
                                     "itemList", "content"]) or
                    self._dig(data, ["mods", "itemList", "content"]) or
                    self._dig(data, ["resultList"]) or
                    self._dig(data, ["items"])
                )
                if product_list:
                    for p in product_list[:60]:
                        item = self._parse_ali_product(p, category, batch_id, ts)
                        if item:
                            items.append(item)
                    if items:
                        return items
            except (json.JSONDecodeError, Exception):
                pass

        block = _find_balanced_block(html, '__NEXT_DATA__', '{')
        if block:
            try:
                data         = json.loads(block)
                product_list = (
                    self._dig(data, ["props", "pageProps", "searchResult",
                                     "resultList"]) or
                    self._dig(data, ["props", "pageProps", "items"])
                )
                if product_list:
                    for p in product_list[:60]:
                        item = self._parse_ali_product(p, category, batch_id, ts)
                        if item:
                            items.append(item)
                    if items:
                        return items
            except (json.JSONDecodeError, Exception):
                pass

        for marker in ['"itemList"', '"resultList"']:
            block = _find_balanced_block(html, marker, '[')
            if block:
                try:
                    product_list = json.loads(block)
                    if isinstance(product_list, list):
                        for p in product_list[:60]:
                            item = self._parse_ali_product(
                                p, category, batch_id, ts
                            )
                            if item:
                                items.append(item)
                        if items:
                            return items
                except (json.JSONDecodeError, Exception):
                    pass

        return items

    def _dig(self, obj: dict, path: list):
        current = obj
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
            if current is None:
                return None
        return current

    def _parse_ali_product(self, p: dict, category: str, batch_id: str,
                           ts: str) -> Optional[dict]:
        price_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            title = (
                self._dig(p, ["title", "displayTitle"]) or
                self._dig(p, ["title", "seoTitle"]) or
                p.get("title") or p.get("productTitle") or
                p.get("name") or p.get("subject") or ""
            )
            if isinstance(title, dict):
                title = next(iter(title.values()), "")
            title = str(title).strip()
            if not title:
                return None

            price = 0.0
            for path in [
                ["prices", "salePrice", "minPrice"],
                ["prices", "originalPrice", "minPrice"],
                ["salePrice", "minAmount"],
                ["price", "value"],
            ]:
                val = self._dig(p, path)
                if val is not None:
                    price = _parse_price(str(val))
                    if price > 0:
                        break
            if price == 0:
                for key, val in p.items():
                    if ("price" in key.lower() and
                            isinstance(val, (int, float)) and val > 0):
                        price = float(val)
                        break

            url = (p.get("productDetailUrl") or p.get("url") or
                   p.get("detailUrl") or "")
            if url and not url.startswith("http"):
                url = "https:" + url

            rating  = float(
                self._dig(p, ["evaluation", "starRating"]) or
                p.get("averageStarRate") or p.get("starRating") or 0
            )
            reviews = int(
                p.get("tradeCount") or p.get("orders") or
                self._dig(p, ["trade", "tradeCount"]) or 0
            )
            sku = str(p.get("productId") or p.get("itemId") or "")

            # [I5] shippingFee del JSON
            shipping_usd = 0.0
            ship_raw = (
                self._dig(p, ["logistics", "shippingFee"]) or
                p.get("shippingFee") or
                self._dig(p, ["shipping", "minFreight"])
            )
            if ship_raw is not None:
                try:
                    shipping_usd = float(
                        str(ship_raw).replace("$", "").strip()
                    )
                except (ValueError, TypeError):
                    shipping_usd = 0.0

            if price > 0 and title:
                return {
                    "batch_id":     batch_id,
                    "source":       "aliexpress",
                    "category":     category,
                    "title":        title[:200],
                    "sku":          sku,           # [I14] sin asin_sku
                    "price_usd":    round(price, 2),
                    "price_date":   price_date,
                    "shipping_usd": round(shipping_usd, 2),
                    "total_usd":    round(price + shipping_usd, 2),
                    "url":          str(url)[:300],
                    "rating":       rating,
                    "reviews":      reviews,
                    "timestamp":    ts,
                }
        except Exception as e:
            log.debug(f"    parse ali product error: {e}")
        return None

    def _parse_html_fallback(self, html: str, category: str,
                             batch_id: str) -> list:
        soup       = BeautifulSoup(html, "html.parser")
        items      = []
        ts         = datetime.now(timezone.utc).isoformat()
        price_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for card in soup.select("a[href*='aliexpress.com/item/']")[:40]:
            try:
                title = ""
                for sel in ["h3", "h2", "[class*='title']", "[class*='Title']"]:
                    el = card.select_one(sel)
                    if el and len(el.get_text(strip=True)) > 10:
                        title = el.get_text(strip=True)
                        break
                price = 0.0
                for el in card.select("span, div"):
                    text = el.get_text(strip=True)
                    if "$" in text or re.match(r"^\d+\.\d{2}$", text):
                        p = _parse_price(text)
                        if 1.0 < p < 10000:
                            price = p
                            break
                url = card.get("href", "")
                if url and not url.startswith("http"):
                    url = "https:" + url
                if price > 0 and title:
                    items.append({
                        "batch_id":     batch_id,
                        "source":       "aliexpress",
                        "category":     category,
                        "title":        title[:200],
                        "sku":          "",
                        "price_usd":    round(price, 2),
                        "price_date":   price_date,
                        "shipping_usd": 0.0,
                        "total_usd":    round(price, 2),
                        "url":          url[:300],
                        "rating":       0.0,
                        "reviews":      0,
                        "timestamp":    ts,
                    })
            except Exception:
                continue
        return items


# ══════════════════════════════════════════════════════════════════════
# INTERFAZ PÚBLICA
# ══════════════════════════════════════════════════════════════════════
def scrape_importacion(
    batch_id: str,
    mode: str = "normal",       # [I17] alinea firma con main.py
    sources: list = None,
    categories: list = None,
    dry_run: bool = False,
) -> list:
    """
    Scraper de precios de importación USA.
    Fuentes: amazon, aliexpress.
    [I6]  eBay eliminado — usar scraper_ebay.py (Browse API) para evitar duplicados.
    [I11] Manejo correcto de CAPTCHA via retorno (items, captcha_flag).
    [I17] Parámetro mode agregado — main.py lo pasa a todos los scrapers.
    [I20] dry_run retorna [] — unique_records siempre vacío en dry_run.
    """
    t_start = time.time()   # [M18]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if sources is None:
        sources = ["amazon", "aliexpress"]
    if categories is None:
        categories = list(CATEGORY_QUERIES.keys())

    scrapers = {}
    if "amazon"     in sources: scrapers["amazon"]     = AmazonScraper()
    if "aliexpress" in sources: scrapers["aliexpress"] = AliExpressScraper()
    if "ebay" in sources:
        log.warning(
            "[Importación] 'ebay' en sources — usar scraper_ebay.py "
            "(Browse API). Ignorado."
        )

    all_records  = []
    dry_run_hits = 0   # [I15]

    for category in categories:
        queries = CATEGORY_QUERIES.get(category, [category.lower()])
        # [I13] Limitar queries por categoría
        queries = queries[:MAX_QUERIES_IMPORT]

        log.info(f"\n{'='*60}")
        log.info(
            f"CATEGORÍA: {category} "
            f"({len(queries)} queries / MAX={MAX_QUERIES_IMPORT})"
        )
        log.info(f"{'='*60}")

        for query in queries:
            for src_name, scraper in scrapers.items():
                for attempt in range(MAX_RETRIES_QUERY):
                    try:
                        # [I11] search() retorna (items, captcha_flag)
                        items, captcha = scraper.search(
                            query, category, batch_id, MAX_PAGES
                        )
                        if dry_run:
                            dry_run_hits += len(items)
                            log.info(
                                f"  [DRY-RUN] {src_name} | "
                                f"{len(items)} items encontrados (no guardados)"
                            )
                        else:
                            all_records.extend(items)

                        if captcha:
                            log.warning(
                                f"  [{src_name}] CAPTCHA — "
                                f"no reintenta '{query}'"
                            )
                        break   # éxito o CAPTCHA → no reintentar
                    except Exception as e:
                        log.error(
                            f"  [{src_name}] intento {attempt+1} "
                            f"error en '{query}': {e}"
                        )
                        if attempt < MAX_RETRIES_QUERY - 1:
                            time.sleep(DELAY_REQ * 2)
                time.sleep(DELAY_REQ)

        time.sleep(DELAY_CAT)

    unique_records = _dedup(all_records)

    # [M18] Log de tiempo total
    elapsed = time.time() - t_start

    if dry_run:
        # [I15] Conteo real de items encontrados
        log.info(
            f"\n[Importación DRY-RUN] Items encontrados: {dry_run_hits:,} "
            f"(no guardados) — ⏱ {elapsed/60:.1f} min"
        )
        return []   # [I20] dry_run siempre retorna lista vacía
    else:
        log.info(
            f"\n[Importación] TOTAL: {len(unique_records):,} registros únicos "
            f"(de {len(all_records):,} brutos) — ⏱ {elapsed/60:.1f} min"
        )
        return unique_records


run_importacion = scrape_importacion


# ══════════════════════════════════════════════════════════════════════
# STANDALONE
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(
        description="Scraper de precios de importación v4.2"
    )
    parser.add_argument("--sources",    nargs="+", default=None,
                        choices=["amazon", "aliexpress"])
    parser.add_argument("--categories", nargs="+", default=None,
                        choices=list(CATEGORY_QUERIES.keys()))
    parser.add_argument("--dry-run",    action="store_true")
    args     = parser.parse_args()
    # [I8] datetime con timezone explícita
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results  = scrape_importacion(
        batch_id,
        sources=args.sources,
        categories=args.categories,
        dry_run=args.dry_run,
    )
    print(f"\nTotal: {len(results)} registros")
    if results:
        print("Ejemplo:", results[0])
