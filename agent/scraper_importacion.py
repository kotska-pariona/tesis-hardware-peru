"""
scraper_importacion.py  v2.0
════════════════════════════
Fuentes de PRECIO DE IMPORTACIÓN:
  - Amazon USA  (HTML con headers rotativos + Session)
  - AliExpress  (HTML + JSON embebido)
  - eBay USA    (HTML + Finding API opcional)

Fixes v2.0:
  - [FIX-1] Parser de precio Amazon robusto
  - [FIX-2] Selector shipping Amazon corregido
  - [FIX-3] AliExpress API URL actualizada + fallback mejorado
  - [FIX-4] find_products() con path explícito para AliExpress
  - [FIX-5] Selector título eBay actualizado
  - [FIX-6] DELAY_CAT movido fuera del loop de queries
  - [FIX-M1] Amazon category node expandido
  - [FIX-M2] Reviews selector Amazon corregido
  - [FIX-M3] eBay params como strings
  - [FIX-M4] Fingerprint más robusto (title completo + source + category)
  - [FIX-M6] requests.Session con Retry automático
  - [FIX-M7] max_retries por query

Salida: importacion_YYYYMMDD_HHMMSS.csv
Columnas: batch_id | source | category | title | price_usd |
          shipping_usd | total_usd | url | asin_sku |
          rating | reviews | timestamp | fingerprint
"""

import os, re, time, json, hashlib, logging, csv
from datetime import datetime, timezone
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scraper_importacion")

# ── Constantes ───────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/home/user"))
MAX_PAGES  = int(os.getenv("MAX_PAGES_IMPORT", "5"))
DELAY_REQ  = float(os.getenv("DELAY_REQ", "2.5"))
DELAY_CAT  = float(os.getenv("DELAY_CAT", "5.0"))
MAX_RETRIES_QUERY = int(os.getenv("MAX_RETRIES_QUERY", "2"))

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

# Amazon category nodes (Electronics + Computers)
AMAZON_CATEGORY_NODES = {
    "CPU":         "n:541966",   # Computers > CPUs
    "GPU":         "n:284822",   # Computers > Graphics Cards
    "RAM":         "n:172500",   # Computers > RAM
    "SSD":         "n:1292110011",
    "MOTHERBOARD": "n:1048424",
    "PSU":         "n:1161760",
    "COOLER":      "n:3012290011",
    "CASE":        "n:1161758",
    "_default":    "n:172282",   # Electronics general
}

# ── User Agents rotativos ─────────────────────────────────────────────────────
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
        "User-Agent":  _next_ua(),
        "Accept":      "application/json, text/plain, */*",
        "Referer":     referer,
        "Connection":  "keep-alive",
    }

# ── Session con Retry automático [FIX-M6] ────────────────────────────────────
def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    return session

# ── Utilidad: parsear precio desde string ─────────────────────────────────────
def _parse_price(raw: str) -> float:
    """Extrae float de strings como '$1,299.99', '1.299,99', '299' [FIX-1]"""
    if not raw:
        return 0.0
    # Remover símbolo de moneda y espacios
    cleaned = re.sub(r"[^\d.,]", "", raw.strip())
    if not cleaned:
        return 0.0
    # Detectar formato europeo (1.299,99) vs americano (1,299.99)
    if re.search(r"\d{1,3}\.\d{3},\d{2}$", cleaned):
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

# ── CSV Writer ────────────────────────────────────────────────────────────────
IMPORT_FIELDS = [
    "batch_id", "source", "category", "title", "price_usd",
    "shipping_usd", "total_usd", "url", "asin_sku",
    "rating", "reviews", "timestamp", "fingerprint",
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
        # [FIX-M4] Fingerprint más robusto: source + category + title completo + precio
        key = f"{row['source']}|{row['category']}|{row['title']}|{row['price_usd']}"
        return hashlib.md5(key.encode()).hexdigest()[:16]

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
    BASE = "https://www.amazon.com/s"

    def __init__(self):
        self.session = _make_session()

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
        # [FIX-M1] Usar nodo de categoría específico
        rh_node = AMAZON_CATEGORY_NODES.get(category, AMAZON_CATEGORY_NODES["_default"])
        params = {
            "k":    query,
            "page": page,
            "ref":  f"sr_pg_{page}",
            "rh":   rh_node,
        }
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
            # Detectar CAPTCHA
            if "Enter the characters you see below" in resp.text or "api-services-support@amazon.com" in resp.text:
                log.warning("    Amazon CAPTCHA detectado — saltando página")
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

                # Precio — [FIX-1] usar _parse_price()
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

                # Shipping [FIX-2] — selectores correctos de Amazon 2024
                shipping_usd = 15.0  # default estimado
                free_ship_selectors = [
                    "span[aria-label='Amazon Prime']",
                    "i.a-icon-prime",
                    "span.a-color-base:contains('FREE')",
                    "span[data-csa-c-content-id='FREE_SHIPPING']",
                ]
                for sel in free_ship_selectors:
                    try:
                        if card.select_one(sel):
                            shipping_usd = 0.0
                            break
                    except Exception:
                        continue
                # Verificar texto "FREE delivery" en el card
                if shipping_usd > 0:
                    card_text = card.get_text()
                    if "FREE delivery" in card_text or "FREE Shipping" in card_text:
                        shipping_usd = 0.0

                # Rating
                rating = 0.0
                rating_el = card.select_one("span.a-icon-alt")
                if rating_el:
                    m = re.search(r"([\d.]+) out of", rating_el.get_text())
                    if m:
                        rating = float(m.group(1))

                # Reviews [FIX-M2] — selector más específico
                reviews = 0
                rev_el = card.select_one("span[aria-label$='stars'] + span a span") \
                      or card.select_one("a[href*='#customerReviews'] span.a-size-base")
                if rev_el:
                    raw_rev = rev_el.get_text(strip=True).replace(",", "").replace(".", "")
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
    AliExpress bloquea APIs internas agresivamente.
    Estrategia: HTML scraping con extracción de JSON embebido en <script>.
    El JSON está en window.runParams o _dida_config_ con la lista de productos.
    """
    SEARCH_URL = "https://www.aliexpress.com/wholesale"

    def __init__(self):
        self.session = _make_session()

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
        try:
            params = {
                "SearchText": requests.utils.quote(query),
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

            html = resp.text

            # [FIX-3/4] Intentar extraer JSON embebido con paths conocidos
            items = self._extract_from_script(html, category, batch_id)
            if items:
                return items

            # Fallback: BeautifulSoup con selectores estables
            return self._parse_html_fallback(html, category, batch_id)

        except Exception as e:
            log.error(f"    AliExpress error: {e}")
            return []

    def _extract_from_script(self, html: str, category: str, batch_id: str) -> list[dict]:
        """[FIX-4] Extrae productos de JSON embebido con paths explícitos"""
        ts = datetime.now(timezone.utc).isoformat()
        items = []

        # Patrones conocidos de AliExpress para datos de productos
        script_patterns = [
            # window.runParams.data.root.fields.mods.itemList.content
            r'window\.runParams\s*=\s*({.*?});\s*(?:var|window|</script>)',
            # _dida_config_
            r'window\._dida_config_\s*=\s*({.*?});\s*</script>',
            # data embebido en __NEXT_DATA__
            r'<script id="__NEXT_DATA__"[^>]*>({.*?})</script>',
            # Lista directa de items
            r'"itemList"\s*:\s*\{"content"\s*:\s*(\[.*?\])\s*[,}]',
            r'"resultList"\s*:\s*(\[.*?\])',
        ]

        for pat in script_patterns:
            try:
                m = re.search(pat, html, re.DOTALL)
                if not m:
                    continue
                raw_json = m.group(1)
                # Truncar si es muy largo para evitar OOM
                if len(raw_json) > 2_000_000:
                    raw_json = raw_json[:2_000_000]
                data = json.loads(raw_json)

                # Navegar paths conocidos de AliExpress
                product_list = (
                    self._dig(data, ["data","root","fields","mods","itemList","content"]) or
                    self._dig(data, ["mods","itemList","content"]) or
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
            except (json.JSONDecodeError, Exception):
                continue
        return items

    def _dig(self, obj: dict, path: list):
        """Navega un path de keys en un dict anidado"""
        current = obj
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
            if current is None:
                return None
        return current

    def _parse_ali_product(self, p: dict, category: str, batch_id: str, ts: str) -> dict | None:
        """Parsea un producto individual de AliExpress"""
        try:
            # Título — múltiples paths conocidos
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

            # Precio — paths conocidos de AliExpress
            price = 0.0
            price_paths = [
                ["prices", "salePrice", "minPrice"],
                ["prices", "originalPrice", "minPrice"],
                ["salePrice", "minAmount"],
                ["price", "value"],
            ]
            for path in price_paths:
                val = self._dig(p, path)
                if val is not None:
                    price = _parse_price(str(val))
                    if price > 0:
                        break
            # Fallback: buscar cualquier key con "price"
            if price == 0:
                for key, val in p.items():
                    if "price" in key.lower() and isinstance(val, (int, float)) and val > 0:
                        price = float(val)
                        break

            url = (
                p.get("productDetailUrl") or p.get("url") or
                p.get("detailUrl") or ""
            )
            if url and not url.startswith("http"):
                url = "https:" + url

            rating = float(
                self._dig(p, ["evaluation", "starRating"]) or
                p.get("averageStarRate") or p.get("starRating") or 0
            )
            reviews = int(
                p.get("tradeCount") or p.get("orders") or
                self._dig(p, ["trade", "tradeCount"]) or 0
            )
            sku = str(p.get("productId") or p.get("itemId") or "")

            if price > 0 and title:
                return {
                    "batch_id":     batch_id,
                    "source":       "aliexpress",
                    "category":     category,
                    "title":        title[:200],
                    "price_usd":    round(price, 2),
                    "shipping_usd": 0.0,
                    "total_usd":    round(price, 2),
                    "url":          str(url)[:300],
                    "asin_sku":     sku,
                    "rating":       rating,
                    "reviews":      reviews,
                    "timestamp":    ts,
                }
        except Exception as e:
            log.debug(f"    parse ali product error: {e}")
        return None

    def _parse_html_fallback(self, html: str, category: str, batch_id: str) -> list[dict]:
        """Fallback BeautifulSoup con selectores estables (no clases hash)"""
        soup = BeautifulSoup(html, "html.parser")
        items = []
        ts = datetime.now(timezone.utc).isoformat()

        # Selectores estables de AliExpress (basados en atributos data-*, no clases hash)
        for card in soup.select("a[href*='aliexpress.com/item/']")[:40]:
            try:
                # Título: buscar cualquier h1/h2/h3 o span con texto largo
                title = ""
                for sel in ["h3", "h2", "[class*='title']", "[class*='Title']"]:
                    el = card.select_one(sel)
                    if el and len(el.get_text(strip=True)) > 10:
                        title = el.get_text(strip=True)
                        break

                # Precio: buscar spans con símbolo $ o texto numérico
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
                        "batch_id":     batch_id,
                        "source":       "aliexpress",
                        "category":     category,
                        "title":        title[:200],
                        "price_usd":    round(price, 2),
                        "shipping_usd": 0.0,
                        "total_usd":    round(price, 2),
                        "url":          url[:300],
                        "asin_sku":     "",
                        "rating":       0.0,
                        "reviews":      0,
                        "timestamp":    ts,
                    })
            except Exception:
                continue
        return items

# ══════════════════════════════════════════════════════════════════════════════
# SCRAPER 3 — EBAY USA
# ══════════════════════════════════════════════════════════════════════════════
class EbayScraper:
    FINDING_API = "https://svcs.ebay.com/services/search/FindingService/v1"
    BROWSE_URL  = "https://www.ebay.com/sch/i.html"
    APP_ID      = os.getenv("EBAY_APP_ID", "")

    def __init__(self):
        self.session = _make_session()

    def search(self, query: str, category: str, batch_id: str, max_pages: int = MAX_PAGES) -> list[dict]:
        items = []
        if self.APP_ID:
            items = self._search_api(query, category, batch_id, max_pages)
        if not items:
            items = self._search_html(query, category, batch_id, max_pages)
        return items

    def _search_api(self, query: str, category: str, batch_id: str, max_pages: int) -> list[dict]:
        items = []
        ts = datetime.now(timezone.utc).isoformat()
        for page in range(1, max_pages + 1):
            params = {
                "OPERATION-NAME":             "findItemsByKeywords",
                "SERVICE-VERSION":            "1.0.0",
                "SECURITY-APPNAME":           self.APP_ID,
                "RESPONSE-DATA-FORMAT":       "JSON",
                "keywords":                   query,
                "paginationInput.pageNumber": str(page),
                "paginationInput.entriesPerPage": "50",
                "itemFilter(0).name":         "Condition",
                "itemFilter(0).value":        "New",
                "itemFilter(1).name":         "ListingType",
                "itemFilter(1).value":        "FixedPrice",
                "sortOrder":                  "BestMatch",
            }
            try:
                resp = self.session.get(self.FINDING_API, params=params, timeout=15)
                data = resp.json()
                search_result = data.get("findItemsByKeywordsResponse", [{}])[0]
                search_items  = search_result.get("searchResult", [{}])[0].get("item", [])
                for item in search_items:
                    try:
                        title = item.get("title", [""])[0]
                        price = float(
                            item.get("sellingStatus", [{}])[0]
                                .get("currentPrice", [{}])[0]
                                .get("__value__", 0)
                        )
                        ship_cost = item.get("shippingInfo", [{}])[0].get("shippingServiceCost", [{}])
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
                    except Exception:
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
                    "_pgn":   str(page),   # [FIX-M3] string, no int
                    "LH_New": "1",         # [FIX-M3] string
                    "LH_BIN": "1",         # [FIX-M3] string
                    "_sop":   "12",        # [FIX-M3] string
                }
                resp = self.session.get(
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
                        # [FIX-5] Selector de título actualizado para eBay 2024
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

                        # Precio: tomar el primero si hay rango "X to Y"
                        raw_price = price_el.get_text(strip=True).split(" to ")[0]
                        price = _parse_price(raw_price)

                        # Shipping
                        ship = 0.0
                        ship_el = card.select_one("span.s-item__shipping, span.s-item__freeXDays")
                        if ship_el:
                            ship_text = ship_el.get_text(strip=True).lower()
                            if "free" not in ship_text:
                                ship = _parse_price(ship_text)
                                if ship == 0:
                                    ship = 10.0  # estimado

                        url = link_el.get("href", "") if link_el else ""
                        # Limpiar URL de tracking params
                        url = url.split("?")[0] if "?" in url else url
                        item_id_m = re.search(r"/(\d{10,})", url)
                        sku = item_id_m.group(1) if item_id_m else ""

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

# ══════════════════════════════════════════════════════════════════════════════
# RUNNER PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════
def run_importacion(
    batch_id: str,
    sources: list[str] = None,
    categories: list[str] = None,
    dry_run: bool = False,
):
    if sources is None:
        sources = ["amazon", "aliexpress", "ebay"]
    if categories is None:
        categories = list(CATEGORY_QUERIES.keys())

    writer   = ImportCSVWriter(batch_id)
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
                # [FIX-M7] Retry por query
                for attempt in range(MAX_RETRIES_QUERY):
                    try:
                        items = scraper.search(query, category, batch_id, MAX_PAGES)
                        if not dry_run:
                            written = writer.write(items)
                            stats[src_name] += written
                            total_written   += written
                        else:
                            log.info(f"  [DRY-RUN] {src_name} | {len(items)} items (no escritos)")
                        break  # éxito
                    except Exception as e:
                        log.error(f"  [{src_name}] intento {attempt+1} error en '{query}': {e}")
                        if attempt < MAX_RETRIES_QUERY - 1:
                            time.sleep(DELAY_REQ * 2)
                time.sleep(DELAY_REQ)

        # [FIX-6] DELAY_CAT fuera del loop de queries
        time.sleep(DELAY_CAT)

    log.info(f"\n{'='*60}")
    log.info(f"IMPORTACIÓN COMPLETA — {total_written} items escritos")
    for src, count in stats.items():
        log.info(f"  {src:<15}: {count:>6} items")
    log.info(f"CSV: {writer.path}")
    log.info(f"{'='*60}")
    return writer.path, total_written, stats

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Scraper de precios de importación")
    parser.add_argument("--sources",    nargs="+", default=None,
                        choices=["amazon","aliexpress","ebay"],
                        help="Fuentes a scrapear")
    parser.add_argument("--categories", nargs="+", default=None,
                        choices=list(CATEGORY_QUERIES.keys()),
                        help="Categorías a scrapear")
    parser.add_argument("--dry-run",    action="store_true",
                        help="Parsear sin escribir CSV")
    args = parser.parse_args()

    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_importacion(
        batch_id,
        sources=args.sources,
        categories=args.categories,
        dry_run=args.dry_run,
    )
