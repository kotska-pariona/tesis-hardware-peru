"""
scraper_importacion.py  v3.1
════════════════════════════
Fuentes de PRECIO DE IMPORTACIÓN (referencia precio piso USA):
  - Amazon USA    (HTML + Session/Retry + CAPTCHA detection)
  - AliExpress    (JSON embebido + fallback HTML)
  - eBay USA      (HTML — Finding API eliminada por deprecación)

Fixes v3.0:
  - [FIX-1] Alias scrape_importacion() → interfaz compatible con main.py
  - [FIX-2] scrape_importacion() retorna list[dict] — no tupla
  - [FIX-3] logging.basicConfig() eliminado del top-level
  - [FIX-4] OUTPUT_DIR default corregido: absoluto desde __file__
  - [FIX-5] eBay Finding API eliminada (deprecada Dic 2024) → solo HTML
  - [FIX-6] 'fingerprint' excluido del retorno público
  - [FIX-7] Amazon rh= node filter hecho opcional
  - [FIX-8] shipping_usd default documentado como estimado

Fixes v3.1:
  - [FIX-9]  'sku' agregado en todos los records → dedup correcto en merge_to_master
  - [FIX-10] 'price_date' agregado en todos los records → clave dedup completa
  - [FIX-11] OUTPUT_DIR usa path absoluto desde __file__ → independiente del CWD
  - [FIX-12] AliExpress: eliminado requests.utils.quote() → evita double-encoding
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

# FIX-3: Sin basicConfig() — logging configurado solo en main.py
log = logging.getLogger(__name__)

# ── Constantes ───────────────────────────────────────────────────────────
# FIX-11: path absoluto — independiente del CWD al ejecutar desde GitHub Actions
_DEFAULT_OUTPUT = str(Path(__file__).resolve().parent.parent.parent / "data" / "raw")
OUTPUT_DIR        = Path(os.getenv("OUTPUT_DIR", _DEFAULT_OUTPUT))
MAX_PAGES         = int(os.getenv("MAX_PAGES_IMPORT", "5"))
DELAY_REQ         = float(os.getenv("DELAY_REQ", "2.5"))
DELAY_CAT         = float(os.getenv("DELAY_CAT", "5.0"))
MAX_RETRIES_QUERY = int(os.getenv("MAX_RETRIES_QUERY", "2"))

# ── Queries por categoría ─────────────────────────────────────────────────
CATEGORY_QUERIES = {
    "CPU": [
        "intel core i5 13th gen processor",
        "intel core i7 13700k processor",
        "amd ryzen 5 7600x processor",
        "amd ryzen 7 7700x processor",
        "amd ryzen 9 7950x processor",
    ],
    "GPU": [
        "nvidia rtx 4060 graphics card",
        "nvidia rtx 4070 graphics card",
        "nvidia rtx 4080 graphics card",
        "amd radeon rx 7800 xt graphics card",
        "amd radeon rx 7900 xt graphics card",
    ],
    "RAM": [
        "ddr4 16gb 3200mhz ram memory",
        "ddr4 32gb 3600mhz ram memory",
        "ddr5 16gb 5600mhz ram memory",
        "ddr5 32gb 6000mhz ram memory",
        "corsair vengeance ddr4 ram",
    ],
    "SSD": [
        "nvme ssd 1tb m.2 pcie",
        "nvme ssd 2tb m.2 pcie 4.0",
        "samsung 990 pro nvme ssd",
        "western digital black sn850x",
        "sata ssd 1tb 2.5 inch",
    ],
    "MOTHERBOARD": [
        "intel z790 motherboard atx",
        "intel b760 motherboard micro atx",
        "amd x670e motherboard atx",
        "amd b650 motherboard micro atx",
        "asus rog strix z790 motherboard",
    ],
    "PSU": [
        "850w 80 plus gold power supply",
        "1000w 80 plus platinum psu",
        "corsair rm850x power supply",
        "seasonic focus gx 850w",
        "evga supernova 850 g6",
    ],
    "COOLER": [
        "240mm aio liquid cpu cooler",
        "360mm aio liquid cooler",
        "noctua nh-d15 cpu cooler",
        "be quiet dark rock pro 4",
        "arctic liquid freezer ii 240",
    ],
    "CASE": [
        "mid tower atx pc case tempered glass",
        "lian li lancool 216 case",
        "fractal design meshify 2 case",
        "nzxt h510 flow case",
        "corsair 4000d airflow case",
    ],
}

# FIX-7: Nodes opcionales — solo se aplican si el nodo es conocido
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

# ── User Agents rotativos ─────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]
_ua_idx = 0

def _next_ua() -> str:
    global _ua_idx
    ua = USER_AGENTS[_ua_idx % len(USER_AGENTS)]
    _ua_idx += 1
    return ua

def _headers(referer: str = "https://www.google.com") -> dict:
    return {
        "User-Agent":      _next_ua(),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer":         referer,
        "DNT":             "1",
        "Connection":      "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

def _json_headers(referer: str = "") -> dict:
    return {
        "User-Agent": _next_ua(),
        "Accept":     "application/json, text/plain, */*",
        "Referer":    referer,
        "Connection": "keep-alive",
    }

# ── Session con Retry automático ─────────────────────────────────────────
def _make_session() -> requests.Session:
    session = requests.Session()
    retry   = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    return session

# ── Parser de precio ─────────────────────────────────────────────────────
def _parse_price(raw: str) -> float:
    """Extrae float de strings como '$1,299.99', '1.299,99', '299'"""
    if not raw:
        return 0.0
    cleaned = re.sub(r"[^\d.,]", "", raw.strip())
    if not cleaned:
        return 0.0
    if re.search(r"\d{1,3}\.\d{3},\d{2}$", cleaned):
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

# ── Deduplicación ────────────────────────────────────────────────────────
def _dedup(records: list) -> list:
    """Elimina duplicados por fingerprint (source + category + title + price)."""
    seen = set()
    out  = []
    for r in records:
        # FIX-6: fingerprint calculado internamente, no expuesto en el registro
        key = f"{r.get('source')}|{r.get('category')}|{r.get('title','')}|{r.get('price_usd',0)}"
        fp  = hashlib.md5(key.encode()).hexdigest()[:16]
        if fp not in seen and float(r.get("price_usd", 0)) > 0:
            seen.add(fp)
            out.append(r)
    return out


# ══════════════════════════════════════════════════════════════════════════
# SCRAPER 1 — AMAZON USA
# ══════════════════════════════════════════════════════════════════════════
class AmazonScraper:
    BASE = "https://www.amazon.com/s"

    def __init__(self):
        self.session = _make_session()

    def search(self, query: str, category: str, batch_id: str, max_pages: int = MAX_PAGES) -> list:
        items = []
        for page in range(1, max_pages + 1):
            log.info(f"  [Amazon] {category} | '{query[:40]}' | pág {page}")
            page_items = self._fetch_page(query, page, category, batch_id)
            items.extend(page_items)
            log.info(f"    → {len(page_items)} items (total: {len(items)})")
            if not page_items:
                break
            time.sleep(DELAY_REQ + (page * 0.3))
        return items

    def _fetch_page(self, query: str, page: int, category: str, batch_id: str) -> list:
        # FIX-7: rh= node solo si el nodo está definido para la categoría
        params = {
            "k":    query,
            "page": page,
            "ref":  f"sr_pg_{page}",
        }
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
                return []
            if resp.status_code != 200:
                log.warning(f"    Amazon HTTP {resp.status_code}")
                return []
            if ("Enter the characters you see below" in resp.text or
                    "api-services-support@amazon.com" in resp.text):
                log.warning("    Amazon CAPTCHA detectado — saltando página")
                return []
            return self._parse(resp.text, category, batch_id)
        except Exception as e:
            log.error(f"    Amazon error: {e}")
            return []

    def _parse(self, html: str, category: str, batch_id: str) -> list:
        soup       = BeautifulSoup(html, "html.parser")
        items      = []
        ts         = datetime.now(timezone.utc).isoformat()
        price_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")  # FIX-10

        for card in soup.select("div[data-component-type='s-search-result']"):
            try:
                title_el = card.select_one("h2 span") or card.select_one("h2 a span")
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

                # FIX-8: shipping documentado como estimado
                shipping_usd = 15.0   # estimado — Amazon no envía directo a Perú
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
                rev_el  = (card.select_one("span[aria-label$='stars'] + span a span") or
                           card.select_one("a[href*='#customerReviews'] span.a-size-base"))
                if rev_el:
                    raw_rev = rev_el.get_text(strip=True).replace(",", "").replace(".", "")
                    try:
                        reviews = int(raw_rev)
                    except ValueError:
                        pass

                if price_usd > 0:
                    items.append({
                        "batch_id":      batch_id,
                        "source":        "amazon_usa",
                        "category":      category,
                        "title":         title[:200],
                        "sku":           asin,           # FIX-9
                        "asin_sku":      asin,
                        "price_usd":     round(price_usd, 2),
                        "price_date":    price_date,     # FIX-10
                        "shipping_usd":  shipping_usd,
                        "total_usd":     round(price_usd + shipping_usd, 2),
                        "url":           url[:300],
                        "rating":        rating,
                        "reviews":       reviews,
                        "timestamp":     ts,
                    })
            except Exception as e:
                log.debug(f"    parse card error: {e}")
                continue
        return items


# ══════════════════════════════════════════════════════════════════════════
# SCRAPER 2 — ALIEXPRESS
# ══════════════════════════════════════════════════════════════════════════
class AliExpressScraper:
    SEARCH_URL = "https://www.aliexpress.com/wholesale"

    def __init__(self):
        self.session = _make_session()

    def search(self, query: str, category: str, batch_id: str, max_pages: int = MAX_PAGES) -> list:
        items = []
        for page in range(1, max_pages + 1):
            log.info(f"  [AliExpress] {category} | '{query[:40]}' | pág {page}")
            page_items = self._fetch_page(query, page, category, batch_id)
            items.extend(page_items)
            log.info(f"    → {len(page_items)} items (total: {len(items)})")
            if not page_items:
                break
            time.sleep(DELAY_REQ)
        return items

    def _fetch_page(self, query: str, page: int, category: str, batch_id: str) -> list:
        try:
            params = {
                "SearchText": query,   # FIX-12: sin quote() — requests encodea solo
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

    def _extract_from_script(self, html: str, category: str, batch_id: str) -> list:
        ts    = datetime.now(timezone.utc).isoformat()
        items = []
        script_patterns = [
            r'window\.runParams\s*=\s*({.*?});\s*(?:var|window|</script>)',
            r'window\._dida_config_\s*=\s*({.*?});\s*</script>',
            r'<script id="__NEXT_DATA__"[^>]*>({.*?})</script>',
            r'"itemList"\s*:\s*\{"content"\s*:\s*(\[.*?\])\s*[,}]',
            r'"resultList"\s*:\s*(\[.*?\])',
        ]
        for pat in script_patterns:
            try:
                m = re.search(pat, html, re.DOTALL)
                if not m:
                    continue
                raw_json = m.group(1)
                if len(raw_json) > 2_000_000:
                    raw_json = raw_json[:2_000_000]
                data = json.loads(raw_json)

                product_list = (
                    self._dig(data, ["data", "root", "fields", "mods", "itemList", "content"]) or
                    self._dig(data, ["mods", "itemList", "content"]) or
                    self._dig(data, ["resultList"]) or
                    self._dig(data, ["items"]) or
                    (data if isinstance(data, list) else None)
                )
                if not product_list:
                    continue

                for p in product_list[:60]:
                    item = self._parse_ali_product(p, category, batch_id, ts)
                    if item:
                        items.append(item)
                if items:
                    return items
            except Exception:
                continue
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

    def _parse_ali_product(self, p: dict, category: str, batch_id: str, ts: str) -> Optional[dict]:
        price_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")  # FIX-10
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
                    if "price" in key.lower() and isinstance(val, (int, float)) and val > 0:
                        price = float(val)
                        break

            url = p.get("productDetailUrl") or p.get("url") or p.get("detailUrl") or ""
            if url and not url.startswith("http"):
                url = "https:" + url

            rating  = float(self._dig(p, ["evaluation", "starRating"]) or
                            p.get("averageStarRate") or p.get("starRating") or 0)
            reviews = int(p.get("tradeCount") or p.get("orders") or
                          self._dig(p, ["trade", "tradeCount"]) or 0)
            sku     = str(p.get("productId") or p.get("itemId") or "")

            if price > 0 and title:
                return {
                    "batch_id":     batch_id,
                    "source":       "aliexpress",
                    "category":     category,
                    "title":        title[:200],
                    "sku":          sku,            # FIX-9
                    "asin_sku":     sku,
                    "price_usd":    round(price, 2),
                    "price_date":   price_date,     # FIX-10
                    "shipping_usd": 0.0,
                    "total_usd":    round(price, 2),
                    "url":          str(url)[:300],
                    "rating":       rating,
                    "reviews":      reviews,
                    "timestamp":    ts,
                }
        except Exception as e:
            log.debug(f"    parse ali product error: {e}")
        return None

    def _parse_html_fallback(self, html: str, category: str, batch_id: str) -> list:
        soup       = BeautifulSoup(html, "html.parser")
        items      = []
        ts         = datetime.now(timezone.utc).isoformat()
        price_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")  # FIX-10
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
                        if 0 < p < 10000:
                            price = p
                            break
                url = card.get("href", "")
                if url and not url.startswith("http"):
                    url = "https:" + url
                if price > 0 and title:
                    items.append({
                        "batch_id":   batch_id,   "source":    "aliexpress",
                        "category":   category,   "title":     title[:200],
                        "sku":        "",          "asin_sku":  "",   # FIX-9
                        "price_usd":  round(price, 2),
                        "price_date": price_date,                     # FIX-10
                        "shipping_usd": 0.0,
                        "total_usd":  round(price, 2),
                        "url":        url[:300],
                        "rating":     0.0,         "reviews":   0,
                        "timestamp":  ts,
                    })
            except Exception:
                continue
        return items


# ══════════════════════════════════════════════════════════════════════════
# SCRAPER 3 — EBAY USA (solo HTML — Finding API deprecada Dic 2024)
# ══════════════════════════════════════════════════════════════════════════
class EbayScraper:
    BROWSE_URL = "https://www.ebay.com/sch/i.html"

    def __init__(self):
        self.session = _make_session()

    def search(self, query: str, category: str, batch_id: str, max_pages: int = MAX_PAGES) -> list:
        items      = []
        ts         = datetime.now(timezone.utc).isoformat()
        price_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")  # FIX-10

        for page in range(1, max_pages + 1):
            log.info(f"  [eBay] {category} | '{query[:40]}' | pág {page}")
            try:
                params = {
                    "_nkw":   query,
                    "_pgn":   str(page),
                    "LH_New": "1",
                    "LH_BIN": "1",
                    "_sop":   "12",
                }
                resp = self.session.get(
                    self.BROWSE_URL, params=params,
                    headers=_headers("https://www.ebay.com/"),
                    timeout=20
                )
                if resp.status_code != 200:
                    break
                soup       = BeautifulSoup(resp.text, "html.parser")
                page_items = []

                for card in soup.select("li.s-item"):
                    try:
                        title_el = (
                            card.select_one("span[role='heading']") or
                            card.select_one("div.s-item__title span[role='heading']") or
                            card.select_one("h3.s-item__title") or
                            card.select_one("div.s-item__title")
                        )
                        price_el = card.select_one("span.s-item__price")
                        link_el  = card.select_one("a.s-item__link")

                        if not title_el or not price_el:
                            continue

                        title = title_el.get_text(strip=True)
                        if title.lower() in ("shop on ebay", ""):
                            continue

                        raw_price = price_el.get_text(strip=True).split(" to ")[0]
                        price     = _parse_price(raw_price)

                        ship     = 0.0
                        ship_el  = card.select_one("span.s-item__shipping, span.s-item__freeXDays")
                        if ship_el:
                            ship_text = ship_el.get_text(strip=True).lower()
                            if "free" not in ship_text:
                                ship = _parse_price(ship_text)
                                if ship == 0:
                                    ship = 10.0

                        url = link_el.get("href", "") if link_el else ""
                        url = url.split("?")[0] if "?" in url else url
                        item_id_m = re.search(r"/(\d{10,})", url)
                        sku       = item_id_m.group(1) if item_id_m else ""

                        if price > 0:
                            page_items.append({
                                "batch_id":     batch_id,
                                "source":       "ebay_usa",
                                "category":     category,
                                "title":        title[:200],
                                "sku":          sku,            # FIX-9
                                "asin_sku":     sku,
                                "price_usd":    round(price, 2),
                                "price_date":   price_date,     # FIX-10
                                "shipping_usd": round(ship, 2),
                                "total_usd":    round(price + ship, 2),
                                "url":          url[:300],
                                "rating":       0.0,
                                "reviews":      0,
                                "timestamp":    ts,
                            })
                    except Exception:
                        continue

                items.extend(page_items)
                log.info(f"    → {len(page_items)} items (total: {len(items)})")
                if not page_items:
                    break
                time.sleep(DELAY_REQ)

            except Exception as e:
                log.error(f"    eBay HTML error: {e}")
                break

        return items


# ══════════════════════════════════════════════════════════════════════════
# FIX-1 + FIX-2: scrape_importacion() — interfaz pública compatible con main.py
# ══════════════════════════════════════════════════════════════════════════

def scrape_importacion(
    batch_id: str,
    sources: list = None,
    categories: list = None,
    dry_run: bool = False,
) -> list:
    """
    Scraper de precios de importación USA.
    FIX-1: Nombre correcto para main.py y __init__.py
    FIX-2: Retorna list[dict] — compatible con save_batch() de main.py
    FIX-6: 'fingerprint' excluido del retorno
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if sources is None:
        sources = ["amazon", "aliexpress", "ebay"]
    if categories is None:
        categories = list(CATEGORY_QUERIES.keys())

    scrapers = {}
    if "amazon"     in sources: scrapers["amazon"]     = AmazonScraper()
    if "aliexpress" in sources: scrapers["aliexpress"] = AliExpressScraper()
    if "ebay"       in sources: scrapers["ebay"]       = EbayScraper()

    all_records = []

    for category in categories:
        queries = CATEGORY_QUERIES.get(category, [category.lower()])
        log.info(f"\n{'='*60}")
        log.info(f"CATEGORÍA: {category} ({len(queries)} queries)")
        log.info(f"{'='*60}")

        for query in queries:
            for src_name, scraper in scrapers.items():
                for attempt in range(MAX_RETRIES_QUERY):
                    try:
                        items = scraper.search(query, category, batch_id, MAX_PAGES)
                        if not dry_run:
                            all_records.extend(items)
                        else:
                            log.info(f"  [DRY-RUN] {src_name} | {len(items)} items (no guardados)")
                        break
                    except Exception as e:
                        log.error(f"  [{src_name}] intento {attempt+1} error en '{query}': {e}")
                        if attempt < MAX_RETRIES_QUERY - 1:
                            time.sleep(DELAY_REQ * 2)
                time.sleep(DELAY_REQ)

        time.sleep(DELAY_CAT)

    # FIX-6: Deduplicar sin exponer fingerprint
    unique_records = _dedup(all_records)

    log.info(f"\n[Importación] TOTAL: {len(unique_records):,} registros únicos "
             f"(de {len(all_records):,} brutos)")
    return unique_records


# Alias para compatibilidad con código legacy
run_importacion = scrape_importacion


# ══════════════════════════════════════════════════════════════════════════
# STANDALONE
# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Scraper de precios de importación")
    parser.add_argument("--sources",    nargs="+", default=None,
                        choices=["amazon", "aliexpress", "ebay"])
    parser.add_argument("--categories", nargs="+", default=None,
                        choices=list(CATEGORY_QUERIES.keys()))
    parser.add_argument("--dry-run",    action="store_true")
    args     = parser.parse_args()
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    results  = scrape_importacion(
        batch_id,
        sources=args.sources,
        categories=args.categories,
        dry_run=args.dry_run,
    )
    print(f"\nTotal: {len(results)} registros")
    if results:
        print("Ejemplo:", results[0])
