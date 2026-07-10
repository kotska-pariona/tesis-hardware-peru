"""
scraper_importacion.py  v1.0
════════════════════════════
Fuentes de PRECIO DE IMPORTACIÓN:
  - Amazon USA  (HTML con headers rotatorios + fallback API)
  - AliExpress  (API pública REST)
  - eBay USA    (Finding API pública)

Salida: importacion_YYYYMMDD_HHMMSS.csv
Columnas: batch_id | source | category | title | price_usd |
          shipping_usd | total_usd | url | asin_sku |
          rating | reviews | timestamp
"""

import os, re, time, json, hashlib, logging, csv
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scraper_importacion")

# ── Constantes ───────────────────────────────────────────────────────────────
OUTPUT_DIR   = Path(os.getenv("OUTPUT_DIR", "/home/user"))
MAX_PAGES    = int(os.getenv("MAX_PAGES_IMPORT", "5"))   # páginas por query
DELAY_REQ    = float(os.getenv("DELAY_REQ", "2.5"))      # segundos entre requests
DELAY_CAT    = float(os.getenv("DELAY_CAT", "5.0"))      # segundos entre categorías

# ── Queries por categoría ─────────────────────────────────────────────────────
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

# ── Headers rotativos ─────────────────────────────────────────────────────────
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
    }

def _json_headers(referer: str = "") -> dict:
    return {
        "User-Agent":  _next_ua(),
        "Accept":      "application/json, text/plain, */*",
        "Referer":     referer,
        "Connection":  "keep-alive",
    }

# ── CSV Writer ────────────────────────────────────────────────────────────────
IMPORT_FIELDS = [
    "batch_id","source","category","title","price_usd",
    "shipping_usd","total_usd","url","asin_sku",
    "rating","reviews","timestamp","fingerprint",
]

class ImportCSVWriter:
    def __init__(self, batch_id: str):
        self.path = OUTPUT_DIR / f"importacion_{batch_id}.csv"
        self._seen: set[str] = set()
        if not self.path.exists():
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=IMPORT_FIELDS).writeheader()
        log.info(f"CSV importación → {self.path}")

    def _fp(self, row: dict) -> str:
        key = f"{row['source']}|{row['title'][:60]}|{row['price_usd']}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def write(self, rows: list[dict]):
        new_rows = []
        for r in rows:
            fp = self._fp(r)
            if fp not in self._seen and float(r.get("price_usd", 0)) > 0:
                r["fingerprint"] = fp
                self._seen.add(fp)
                new_rows.append(r)
        if new_rows:
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=IMPORT_FIELDS, extrasaction="ignore")
                w.writerows(new_rows)
            log.info(f"  ✅ +{len(new_rows)} items escritos")
        return len(new_rows)

# ══════════════════════════════════════════════════════════════════════════════
# SCRAPER 1 — AMAZON USA
# ══════════════════════════════════════════════════════════════════════════════
class AmazonScraper:
    """
    Scraper de Amazon.com usando HTML estático.
    Amazon sirve precios en el HTML para los primeros ~16 items/página.
    Usa headers rotativos + delays para evitar bloqueos.
    """
    BASE = "https://www.amazon.com/s"

    def search(self, query: str, category: str, batch_id: str, max_pages: int = MAX_PAGES) -> list[dict]:
        items = []
        for page in range(1, max_pages + 1):
            log.info(f"  [Amazon] {category} | '{query[:40]}' | pág {page}")
            page_items = self._fetch_page(query, page, category, batch_id)
            items.extend(page_items)
            log.info(f"    → {len(page_items)} items (total: {len(items)})")
            if len(page_items) == 0:
                break
            time.sleep(DELAY_REQ + (page * 0.3))
        return items

    def _fetch_page(self, query: str, page: int, category: str, batch_id: str) -> list[dict]:
        params = {
            "k":      query,
            "page":   page,
            "ref":    f"sr_pg_{page}",
            "rh":     "n:172282",  # Electronics category
        }
        try:
            resp = requests.get(
                self.BASE, params=params,
                headers=_headers("https://www.amazon.com/"),
                timeout=20
            )
            if resp.status_code != 200:
                log.warning(f"    Amazon HTTP {resp.status_code}")
                return []
            return self._parse(resp.text, category, batch_id)
        except Exception as e:
            log.error(f"    Amazon error: {e}")
            return []

    def _parse(self, html: str, category: str, batch_id: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        items = []
        ts = datetime.now(timezone.utc).isoformat()

        for card in soup.select("div[data-component-type='s-search-result']"):
            try:
                # Título
                title_el = card.select_one("h2 span") or card.select_one("h2 a span")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue

                # ASIN
                asin = card.get("data-asin", "")

                # URL
                link_el = card.select_one("h2 a")
                url = f"https://www.amazon.com{link_el['href']}" if link_el and link_el.get("href") else ""

                # Precio — múltiples selectores
                price_usd = 0.0
                for sel in [
                    "span.a-price > span.a-offscreen",
                    "span[data-a-color='base'] span.a-offscreen",
                    "span.a-price-whole",
                ]:
                    el = card.select_one(sel)
                    if el:
                        raw = el.get_text(strip=True).replace("$","").replace(",","").strip()
                        try:
                            price_usd = float(raw.split(".")[0] + "." + raw.split(".")[1]) if "." in raw else float(raw)
                            break
                        except:
                            continue

                # Shipping
                ship_el = card.select_one("span.s-free-shipping-badge") or card.select_one("span[aria-label*='FREE']")
                shipping_usd = 0.0 if ship_el else 15.0  # estimado si no es free

                # Rating
                rating_el = card.select_one("span.a-icon-alt")
                rating = 0.0
                if rating_el:
                    m = re.search(r"([\d.]+) out of", rating_el.get_text())
                    if m:
                        rating = float(m.group(1))

                # Reviews
                rev_el = card.select_one("span[aria-label*='stars'] + span") or card.select_one("a span.a-size-base")
                reviews = 0
                if rev_el:
                    raw_rev = rev_el.get_text(strip=True).replace(",","")
                    try:
                        reviews = int(raw_rev)
                    except:
                        pass

                if price_usd > 0:
                    items.append({
                        "batch_id":     batch_id,
                        "source":       "amazon_usa",
                        "category":     category,
                        "title":        title[:200],
                        "price_usd":    round(price_usd, 2),
                        "shipping_usd": shipping_usd,
                        "total_usd":    round(price_usd + shipping_usd, 2),
                        "url":          url[:300],
                        "asin_sku":     asin,
                        "rating":       rating,
                        "reviews":      reviews,
                        "timestamp":    ts,
                    })
            except Exception as e:
                log.debug(f"    parse card error: {e}")
                continue
        return items

# ══════════════════════════════════════════════════════════════════════════════
# SCRAPER 2 — ALIEXPRESS
# ══════════════════════════════════════════════════════════════════════════════
class AliExpressScraper:
    """
    AliExpress tiene una API de búsqueda pública (sin autenticación)
    accesible desde el frontend. Devuelve JSON con precios en USD.
    """
    SEARCH_API = "https://www.aliexpress.com/fn/search-pc/index"
    GWAY_API   = "https://gw.aliexpress.com/ajaxapi/search/pc/search"

    def search(self, query: str, category: str, batch_id: str, max_pages: int = MAX_PAGES) -> list[dict]:
        items = []
        for page in range(1, max_pages + 1):
            log.info(f"  [AliExpress] {category} | '{query[:40]}' | pág {page}")
            page_items = self._fetch_page(query, page, category, batch_id)
            items.extend(page_items)
            log.info(f"    → {len(page_items)} items (total: {len(items)})")
            if len(page_items) == 0:
                break
            time.sleep(DELAY_REQ)
        return items

    def _fetch_page(self, query: str, page: int, category: str, batch_id: str) -> list[dict]:
        # Método 1: API de búsqueda interna
        try:
            params = {
                "SearchText": query,
                "page":       page,
                "g":          "y",
                "isrefine":   "y",
            }
            headers = _json_headers("https://www.aliexpress.com/")
            headers["X-Requested-With"] = "XMLHttpRequest"

            resp = requests.get(
                self.SEARCH_API, params=params,
                headers=headers, timeout=20
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    items = self._parse_json(data, category, batch_id)
                    if items:
                        return items
                except:
                    pass
        except Exception as e:
            log.debug(f"    AliExpress API error: {e}")

        # Método 2: Fallback HTML
        return self._fetch_html(query, page, category, batch_id)

    def _fetch_html(self, query: str, page: int, category: str, batch_id: str) -> list[dict]:
        try:
            url = f"https://www.aliexpress.com/wholesale?SearchText={requests.utils.quote(query)}&page={page}"
            resp = requests.get(url, headers=_headers("https://www.aliexpress.com/"), timeout=20)
            if resp.status_code != 200:
                return []

            # AliExpress embebe datos en window._dida_config_ o __NEXT_DATA__
            html = resp.text
            items = []
            ts = datetime.now(timezone.utc).isoformat()

            # Buscar JSON embebido
            patterns = [
                r'window\._dida_config_\s*=\s*({.*?});\s*</script>',
                r'"mods":\{"itemList":\{"content":(\[.*?\])',
                r'"items":(\[{.*?}\])',
            ]
            for pat in patterns:
                m = re.search(pat, html, re.DOTALL)
                if m:
                    try:
                        data = json.loads(m.group(1))
                        items = self._parse_json(data, category, batch_id)
                        if items:
                            return items
                    except:
                        continue

            # Fallback: BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for card in soup.select("a[href*='aliexpress.com/item/']")[:40]:
                try:
                    title_el = card.select_one("h3") or card.select_one("span.manhattan--titleText--WccSjI9")
                    price_el = card.select_one("span.manhattan--price-sale--1CCSZfK") or card.select_one("div.price--originalText--Zsc6sMk")
                    if not title_el or not price_el:
                        continue
                    title = title_el.get_text(strip=True)
                    raw_price = re.sub(r"[^\d.]", "", price_el.get_text(strip=True))
                    price = float(raw_price) if raw_price else 0.0
                    if price > 0 and title:
                        items.append({
                            "batch_id":     batch_id,
                            "source":       "aliexpress",
                            "category":     category,
                            "title":        title[:200],
                            "price_usd":    round(price, 2),
                            "shipping_usd": 0.0,
                            "total_usd":    round(price, 2),
                            "url":          card.get("href", "")[:300],
                            "asin_sku":     "",
                            "rating":       0.0,
                            "reviews":      0,
                            "timestamp":    ts,
                        })
                except:
                    continue
            return items
        except Exception as e:
            log.error(f"    AliExpress HTML error: {e}")
            return []

    def _parse_json(self, data, category: str, batch_id: str) -> list[dict]:
        items = []
        ts = datetime.now(timezone.utc).isoformat()

        # Navegar estructura JSON recursivamente buscando listas de productos
        def find_products(obj, depth=0):
            if depth > 6:
                return []
            found = []
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict) and ("title" in item or "productTitle" in item or "name" in item):
                        found.append(item)
                    else:
                        found.extend(find_products(item, depth+1))
            elif isinstance(obj, dict):
                for v in obj.values():
                    found.extend(find_products(v, depth+1))
            return found

        products = find_products(data)
        for p in products[:60]:
            try:
                title = (
                    p.get("title") or p.get("productTitle") or
                    p.get("name") or p.get("subject") or ""
                )
                if isinstance(title, dict):
                    title = title.get("displayTitle", "") or str(title)

                # Precio — múltiples estructuras
                price = 0.0
                for key in ["salePrice","price","priceModule","originalPrice","minPrice"]:
                    val = p.get(key)
                    if isinstance(val, (int, float)) and val > 0:
                        price = float(val)
                        break
                    elif isinstance(val, dict):
                        for subkey in ["value","minAmount","formattedPrice","minPrice"]:
                            sv = val.get(subkey)
                            if sv:
                                raw = re.sub(r"[^\d.]", "", str(sv))
                                try:
                                    price = float(raw)
                                    break
                                except:
                                    pass
                        if price > 0:
                            break
                    elif isinstance(val, str):
                        raw = re.sub(r"[^\d.]", "", val)
                        try:
                            price = float(raw)
                            if price > 0:
                                break
                        except:
                            pass

                url = p.get("productDetailUrl") or p.get("url") or p.get("detailUrl") or ""
                if url and not url.startswith("http"):
                    url = "https:" + url

                rating = float(p.get("averageStarRate") or p.get("starRating") or 0)
                reviews = int(p.get("tradeCount") or p.get("orders") or 0)
                sku = str(p.get("productId") or p.get("itemId") or "")

                if price > 0 and title:
                    items.append({
                        "batch_id":     batch_id,
                        "source":       "aliexpress",
                        "category":     category,
                        "title":        str(title)[:200],
                        "price_usd":    round(price, 2),
                        "shipping_usd": 0.0,
                        "total_usd":    round(price, 2),
                        "url":          str(url)[:300],
                        "asin_sku":     sku,
                        "rating":       rating,
                        "reviews":      reviews,
                        "timestamp":    ts,
                    })
            except Exception as e:
                log.debug(f"    parse product error: {e}")
                continue
        return items

# ══════════════════════════════════════════════════════════════════════════════
# SCRAPER 3 — EBAY USA
# ══════════════════════════════════════════════════════════════════════════════
class EbayScraper:
    """
    eBay tiene una API de búsqueda pública (Finding API) sin autenticación
    para búsquedas básicas. También funciona scraping HTML.
    """
    FINDING_API = "https://svcs.ebay.com/services/search/FindingService/v1"
    BROWSE_URL  = "https://www.ebay.com/sch/i.html"
    APP_ID      = os.getenv("EBAY_APP_ID", "")  # Opcional — mejora rate limit

    def search(self, query: str, category: str, batch_id: str, max_pages: int = MAX_PAGES) -> list[dict]:
        items = []
        # Intentar Finding API si hay APP_ID
        if self.APP_ID:
            items = self._search_api(query, category, batch_id, max_pages)
        # Fallback HTML siempre
        if not items:
            items = self._search_html(query, category, batch_id, max_pages)
        return items

    def _search_api(self, query: str, category: str, batch_id: str, max_pages: int) -> list[dict]:
        items = []
        ts = datetime.now(timezone.utc).isoformat()
        for page in range(1, min(max_pages + 1, 4)):
            params = {
                "OPERATION-NAME":        "findItemsByKeywords",
                "SERVICE-VERSION":       "1.0.0",
                "SECURITY-APPNAME":      self.APP_ID,
                "RESPONSE-DATA-FORMAT":  "JSON",
                "keywords":              query,
                "paginationInput.pageNumber": page,
                "paginationInput.entriesPerPage": 50,
                "itemFilter(0).name":    "Condition",
                "itemFilter(0).value":   "New",
                "itemFilter(1).name":    "ListingType",
                "itemFilter(1).value":   "FixedPrice",
                "sortOrder":             "BestMatch",
            }
            try:
                resp = requests.get(self.FINDING_API, params=params, timeout=15)
                data = resp.json()
                search_result = data.get("findItemsByKeywordsResponse", [{}])[0]
                search_items  = search_result.get("searchResult", [{}])[0].get("item", [])
                for item in search_items:
                    try:
                        title = item.get("title", [""])[0]
                        price = float(item.get("sellingStatus",[{}])[0].get("currentPrice",[{}])[0].get("__value__", 0))
                        ship_cost = item.get("shippingInfo",[{}])[0].get("shippingServiceCost",[{}])
                        ship = float(ship_cost[0].get("__value__", 0)) if ship_cost else 0.0
                        url = item.get("viewItemURL", [""])[0]
                        item_id = item.get("itemId", [""])[0]
                        if price > 0:
                            items.append({
                                "batch_id":     batch_id,
                                "source":       "ebay_usa",
                                "category":     category,
                                "title":        title[:200],
                                "price_usd":    round(price, 2),
                                "shipping_usd": round(ship, 2),
                                "total_usd":    round(price + ship, 2),
                                "url":          url[:300],
                                "asin_sku":     item_id,
                                "rating":       0.0,
                                "reviews":      0,
                                "timestamp":    ts,
                            })
                    except:
                        continue
                time.sleep(DELAY_REQ)
            except Exception as e:
                log.error(f"    eBay API error: {e}")
                break
        return items

    def _search_html(self, query: str, category: str, batch_id: str, max_pages: int) -> list[dict]:
        items = []
        ts = datetime.now(timezone.utc).isoformat()
        for page in range(1, max_pages + 1):
            log.info(f"  [eBay] {category} | '{query[:40]}' | pág {page}")
            try:
                params = {
                    "_nkw":   query,
                    "_pgn":   page,
                    "LH_New": 1,
                    "LH_BIN": 1,  # Buy It Now only
                    "_sop":   12, # Best Match
                }
                resp = requests.get(
                    self.BROWSE_URL, params=params,
                    headers=_headers("https://www.ebay.com/"),
                    timeout=20
                )
                if resp.status_code != 200:
                    break
                soup = BeautifulSoup(resp.text, "html.parser")
                page_items = []

                for card in soup.select("li.s-item"):
                    try:
                        title_el = card.select_one("div.s-item__title span") or card.select_one("h3.s-item__title")
                        price_el = card.select_one("span.s-item__price")
                        link_el  = card.select_one("a.s-item__link")
                        if not title_el or not price_el:
                            continue
                        title = title_el.get_text(strip=True)
                        if title.lower() in ("shop on ebay", ""):
                            continue
                        raw_price = re.sub(r"[^\d.]", "", price_el.get_text(strip=True).split(" to ")[0])
                        price = float(raw_price) if raw_price else 0.0
                        # Shipping
                        ship_el = card.select_one("span.s-item__shipping")
                        ship = 0.0
                        if ship_el:
                            ship_text = ship_el.get_text(strip=True)
                            if "free" in ship_text.lower():
                                ship = 0.0
                            else:
                                raw_ship = re.sub(r"[^\d.]", "", ship_text)
                                try:
                                    ship = float(raw_ship)
                                except:
                                    ship = 10.0
                        url = link_el.get("href", "") if link_el else ""
                        item_id = re.search(r"/(\d+)\?", url)
                        sku = item_id.group(1) if item_id else ""
                        if price > 0:
                            page_items.append({
                                "batch_id":     batch_id,
                                "source":       "ebay_usa",
                                "category":     category,
                                "title":        title[:200],
                                "price_usd":    round(price, 2),
                                "shipping_usd": round(ship, 2),
                                "total_usd":    round(price + ship, 2),
                                "url":          url[:300],
                                "asin_sku":     sku,
                                "rating":       0.0,
                                "reviews":      0,
                                "timestamp":    ts,
                            })
                    except:
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

# ══════════════════════════════════════════════════════════════════════════════
# RUNNER PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════
def run_importacion(batch_id: str, sources: list[str] = None, categories: list[str] = None):
    if sources is None:
        sources = ["amazon", "aliexpress", "ebay"]
    if categories is None:
        categories = list(CATEGORY_QUERIES.keys())

    writer  = ImportCSVWriter(batch_id)
    scrapers = {}
    if "amazon"     in sources: scrapers["amazon"]     = AmazonScraper()
    if "aliexpress" in sources: scrapers["aliexpress"] = AliExpressScraper()
    if "ebay"       in sources: scrapers["ebay"]       = EbayScraper()

    total_written = 0
    stats = {s: 0 for s in scrapers}

    for category in categories:
        queries = CATEGORY_QUERIES.get(category, [category.lower()])
        log.info(f"\n{'='*60}")
        log.info(f"CATEGORÍA: {category} ({len(queries)} queries)")
        log.info(f"{'='*60}")

        for query in queries:
            for src_name, scraper in scrapers.items():
                try:
                    items = scraper.search(query, category, batch_id, MAX_PAGES)
                    written = writer.write(items)
                    stats[src_name] += written
                    total_written   += written
                except Exception as e:
                    log.error(f"  [{src_name}] error en '{query}': {e}")
                time.sleep(DELAY_REQ)
            time.sleep(DELAY_CAT)

    log.info(f"\n{'='*60}")
    log.info(f"IMPORTACIÓN COMPLETA — {total_written} items escritos")
    for src, count in stats.items():
        log.info(f"  {src:<15}: {count:>6} items")
    log.info(f"CSV: {writer.path}")
    log.info(f"{'='*60}")
    return writer.path, total_written, stats

if __name__ == "__main__":
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_importacion(batch_id)