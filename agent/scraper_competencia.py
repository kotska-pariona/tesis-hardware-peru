"""
scraper_competencia.py  v1.1
════════════════════════════
Fuentes de PRECIO DE COMPETENCIA (referencia precio techo PE):
  - Falabella PE  (API JSON interna)
  - Ripley PE     (API JSON interna)
  - Hiraoka PE    (HTML con URLs de categoría directa)

Salida: competencia_YYYYMMDD_HHMMSS.csv
"""

import os, re, time, json, hashlib, logging, csv
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scraper_competencia")

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "data/raw"))   # ✅ FIX 1
MAX_PAGES  = int(os.getenv("MAX_PAGES_COMP", "30"))
DELAY_REQ  = float(os.getenv("DELAY_REQ", "2.0"))
DELAY_CAT  = float(os.getenv("DELAY_CAT", "4.0"))

# ── Queries por categoría ─────────────────────────────────────────────────────
CATEGORY_QUERIES_PE = {
    "CPU": [
        "procesador intel core i5",
        "procesador intel core i7",
        "procesador intel core i9",
        "procesador amd ryzen 5",
        "procesador amd ryzen 7",
        "procesador amd ryzen 9",
    ],
    "GPU": [
        "tarjeta de video nvidia rtx 4060",
        "tarjeta de video nvidia rtx 4070",
        "tarjeta de video nvidia rtx 4080",
        "tarjeta de video amd radeon rx 7800",
        "tarjeta grafica geforce rtx",
    ],
    "RAM": [
        "memoria ram ddr4 16gb",
        "memoria ram ddr4 32gb",
        "memoria ram ddr5",
        "memoria ram corsair",
        "memoria ram kingston fury",
    ],
    "SSD": [
        "disco solido nvme 1tb",
        "disco solido nvme 2tb",
        "ssd m2 pcie",
        "disco solido samsung 990",
        "disco solido wd black",
    ],
    "MOTHERBOARD": [
        "placa madre intel z790",
        "placa madre intel b760",
        "placa madre amd x670",
        "placa madre amd b650",
        "motherboard asus rog",
    ],
    "PSU": [
        "fuente de poder 850w gold",
        "fuente de poder 1000w platinum",
        "fuente corsair rm850x",
        "fuente seasonic 850w",
        "fuente poder 80 plus",
    ],
    "COOLER": [
        "cooler liquido 240mm cpu",
        "cooler liquido 360mm aio",
        "disipador cpu noctua",
        "refrigeracion liquida cpu",
        "cooler cpu be quiet",
    ],
    "CASE": [
        "case gamer atx vidrio templado",
        "gabinete pc gamer mid tower",
        "case lian li",
        "gabinete fractal design",
        "case nzxt h510",
    ],
}

# ── CSV Writer ────────────────────────────────────────────────────────────────
COMP_FIELDS = [
    "batch_id","source","category","title","price_pen",
    "price_original_pen","discount_pct","url","brand",
    "available","rating","timestamp","fingerprint",
]

class CompetenciaCSVWriter:
    def __init__(self, batch_id: str):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.path  = OUTPUT_DIR / f"competencia_{batch_id}.csv"
        self._seen: set = set()
        if not self.path.exists():
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=COMP_FIELDS).writeheader()
        log.info(f"CSV competencia → {self.path}")

    def _fp(self, row: dict) -> str:
        key = f"{row['source']}|{row['title'][:60]}|{row['price_pen']}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def write(self, rows: list) -> int:
        new_rows = []
        for r in rows:
            fp = self._fp(r)
            if fp not in self._seen and float(r.get("price_pen", 0)) > 0:
                r["fingerprint"] = fp
                self._seen.add(fp)
                new_rows.append(r)
        if new_rows:
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=COMP_FIELDS, extrasaction="ignore")
                w.writerows(new_rows)
            log.info(f"  ✅ +{len(new_rows)} items escritos")
        return len(new_rows)

# ── Headers ───────────────────────────────────────────────────────────────────
def _headers(referer="https://www.google.com") -> dict:
    return {
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
        "Referer":         referer,
    }

def _json_headers(referer="") -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Accept":     "application/json, text/plain, */*",
        "Referer":    referer,
    }

# ══════════════════════════════════════════════════════════════════════════════
# SCRAPER 1 — FALABELLA PE
# ══════════════════════════════════════════════════════════════════════════════
class FalabellaScraper:
    API_BASE = "https://www.falabella.com.pe/s/browse/v1/listing/pe"

    def search(self, query: str, category: str, batch_id: str, max_pages: int = MAX_PAGES) -> list:
        items = []
        for page in range(1, max_pages + 1):
            log.info(f"  [Falabella] {category} | '{query[:40]}' | pág {page}")
            page_items = self._fetch_page(query, page, category, batch_id)
            items.extend(page_items)
            log.info(f"    → {len(page_items)} items (total: {len(items)})")
            if not page_items:
                break
            time.sleep(DELAY_REQ)
        return items

    def _fetch_page(self, query, page, category, batch_id):
        try:
            params = {"Ntt": query, "page": page, "imageSize": "zoom", "zones": "13"}
            resp = requests.get(
                self.API_BASE, params=params,
                headers=_json_headers("https://www.falabella.com.pe/"),
                timeout=20
            )
            if resp.status_code == 200:
                data  = resp.json()
                items = self._parse_api(data, category, batch_id)
                if items:
                    return items
        except Exception as e:
            log.debug(f"    Falabella API error: {e}")
        return self._fetch_html(query, page, category, batch_id)

    def _parse_api(self, data, category, batch_id):
        items  = []
        ts     = datetime.now(timezone.utc).isoformat()

        def extract_products(obj, depth=0):
            if depth > 8: return []
            found = []
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict):
                        if any(k in item for k in ["displayName","productName","name","title"]):
                            if any(k in item for k in ["prices","price","offerPrice"]):
                                found.append(item)
                        found.extend(extract_products(item, depth+1))
            elif isinstance(obj, dict):
                for v in obj.values():
                    found.extend(extract_products(v, depth+1))
            return found

        products = extract_products(data)
        seen_ids = set()

        for p in products:
            try:
                pid = p.get("productId") or p.get("id") or p.get("skuId") or ""
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)

                title = (p.get("displayName") or p.get("productName") or
                         p.get("name") or p.get("title") or "")

                price_pen  = 0.0
                price_orig = 0.0
                prices_obj = p.get("prices") or p.get("price") or {}

                if isinstance(prices_obj, list):
                    for pr in prices_obj:
                        if isinstance(pr, dict):
                            val   = pr.get("price") or pr.get("value") or 0
                            label = str(pr.get("label", "")).lower()
                            if "oferta" in label or "precio" in label or not label:
                                try: price_pen  = float(str(val).replace(",", ""))
                                except: pass
                            elif "normal" in label or "original" in label:
                                try: price_orig = float(str(val).replace(",", ""))
                                except: pass
                elif isinstance(prices_obj, dict):
                    for key in ["offerPrice","salePrice","normalPrice","originalPrice","price"]:
                        val = prices_obj.get(key)
                        if val:
                            raw = re.sub(r"[^\d.]", "", str(val))
                            try: price_pen = float(raw); break
                            except: pass
                    for key in ["normalPrice","originalPrice","regularPrice"]:
                        val = prices_obj.get(key)
                        if val:
                            raw = re.sub(r"[^\d.]", "", str(val))
                            try: price_orig = float(raw); break
                            except: pass

                if price_pen == 0:
                    for key in ["offerPrice","salePrice","price","currentPrice"]:
                        val = p.get(key)
                        if val:
                            raw = re.sub(r"[^\d.]", "", str(val))
                            try: price_pen = float(raw); break
                            except: pass

                discount = 0.0
                if price_orig > 0 and price_pen > 0 and price_orig > price_pen:
                    discount = round((price_orig - price_pen) / price_orig * 100, 1)

                brand    = p.get("brand") or p.get("brandName") or ""
                url_path = p.get("url") or p.get("pdpUrl") or p.get("productUrl") or ""
                url      = (f"https://www.falabella.com.pe{url_path}"
                            if url_path and not url_path.startswith("http") else url_path)
                rating    = float(p.get("rating") or p.get("averageRating") or 0)
                available = bool(p.get("available") or p.get("isAvailable") or p.get("stock"))  # ✅ FIX 5

                if price_pen > 0 and title:
                    items.append({
                        "batch_id": batch_id, "source": "falabella",
                        "category": category, "title": str(title)[:200],
                        "price_pen": round(price_pen, 2),
                        "price_original_pen": round(price_orig, 2),
                        "discount_pct": discount,
                        "url": str(url)[:300], "brand": str(brand)[:100],
                        "available": available, "rating": rating, "timestamp": ts,
                    })
            except Exception as e:
                log.debug(f"    parse Falabella error: {e}")
        return items

    def _fetch_html(self, query, page, category, batch_id):
        try:
            url  = f"https://www.falabella.com.pe/falabella-pe/search?Ntt={requests.utils.quote(query)}&page={page}"
            resp = requests.get(url, headers=_headers("https://www.falabella.com.pe/"), timeout=20)
            if resp.status_code != 200:
                return []
            m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                          resp.text, re.DOTALL)
            if m:
                try:
                    data  = json.loads(m.group(1))
                    items = self._parse_api(data, category, batch_id)
                    if items: return items
                except: pass
            soup  = BeautifulSoup(resp.text, "html.parser")
            items = []
            ts    = datetime.now(timezone.utc).isoformat()
            for card in soup.select("div[class*='product-card'],div[class*='ProductCard'],li[class*='search-results']"):
                try:
                    title_el = card.select_one("b[class*='pod-title'],span[class*='pod-title'],a[class*='pod-title']")
                    price_el = card.select_one("span[class*='copy10'],li[class*='prices-0'],span[class*='price']")
                    if not title_el or not price_el: continue
                    title = title_el.get_text(strip=True)
                    raw   = re.sub(r"[^\d]", "", price_el.get_text(strip=True))
                    price = float(raw) if raw else 0.0
                    if price > 0 and title:
                        items.append({
                            "batch_id": batch_id, "source": "falabella",
                            "category": category, "title": title[:200],
                            "price_pen": price, "price_original_pen": 0.0,
                            "discount_pct": 0.0, "url": url[:300],
                            "brand": "", "available": True,
                            "rating": 0.0, "timestamp": ts,
                        })
                except: continue
            return items
        except Exception as e:
            log.error(f"    Falabella HTML error: {e}")
            return []

# ══════════════════════════════════════════════════════════════════════════════
# SCRAPER 2 — RIPLEY PE
# ══════════════════════════════════════════════════════════════════════════════
class RipleyScraper:
    API_BASE = "https://simple.ripley.com.pe/api/search"

    def search(self, query: str, category: str, batch_id: str, max_pages: int = MAX_PAGES) -> list:
        items = []
        for page in range(1, max_pages + 1):
            log.info(f"  [Ripley] {category} | '{query[:40]}' | pág {page}")
            page_items = self._fetch_page(query, page, category, batch_id)
            items.extend(page_items)
            log.info(f"    → {len(page_items)} items (total: {len(items)})")
            if not page_items:
                break
            time.sleep(DELAY_REQ)
        return items

    def _fetch_page(self, query, page, category, batch_id):
        try:
            params = {"q": query, "page": page, "perPage": 40}
            resp   = requests.get(
                self.API_BASE, params=params,
                headers=_json_headers("https://simple.ripley.com.pe/"),
                timeout=20
            )
            if resp.status_code == 200:
                data  = resp.json()
                items = self._parse_api(data, category, batch_id)
                if items: return items
        except Exception as e:
            log.debug(f"    Ripley API error: {e}")
        return self._fetch_html(query, page, category, batch_id)

    def _parse_api(self, data, category, batch_id):
        items    = []
        ts       = datetime.now(timezone.utc).isoformat()
        products = data.get("results") or data.get("products") or data.get("items") or []

        if not isinstance(products, list):
            def find_list(obj, depth=0):
                if depth > 5: return []
                if isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
                    return obj
                if isinstance(obj, dict):
                    for v in obj.values():
                        r = find_list(v, depth+1)
                        if r: return r
                return []
            products = find_list(data)

        for p in products:
            try:
                title  = p.get("displayName") or p.get("name") or p.get("title") or ""
                brand  = p.get("brand") or ""
                price_pen  = 0.0
                price_orig = 0.0
                prices = p.get("prices") or {}

                if isinstance(prices, dict):
                    # ✅ FIX 2: offerPrice primero (precio real de venta)
                    for key in ["offerPrice","salePrice","normalPrice","price"]:
                        val = prices.get(key)
                        if val:
                            try: price_pen = float(str(val).replace(",","")); break
                            except: pass
                    for key in ["normalPrice","originalPrice","regularPrice"]:
                        val = prices.get(key)
                        if val:
                            try: price_orig = float(str(val).replace(",","")); break
                            except: pass
                elif isinstance(prices, list):
                    for pr in prices:
                        val = pr.get("price") or pr.get("value") or 0
                        try: price_pen = float(val); break
                        except: pass

                if price_pen == 0:
                    for key in ["offerPrice","salePrice","price","normalPrice"]:
                        val = p.get(key)
                        if val:
                            raw = re.sub(r"[^\d.]", "", str(val))
                            try: price_pen = float(raw); break
                            except: pass

                discount = 0.0
                if price_orig > price_pen > 0:
                    discount = round((price_orig - price_pen) / price_orig * 100, 1)

                url_path  = p.get("url") or p.get("pdpUrl") or ""
                url       = (f"https://simple.ripley.com.pe{url_path}"
                             if url_path and not url_path.startswith("http") else url_path)
                rating    = float(p.get("rating") or p.get("averageRating") or 0)
                available = bool(p.get("available") or p.get("isAvailable") or p.get("stock"))  # ✅ FIX 5

                if price_pen > 0 and title:
                    items.append({
                        "batch_id": batch_id, "source": "ripley",
                        "category": category, "title": str(title)[:200],
                        "price_pen": round(price_pen, 2),
                        "price_original_pen": round(price_orig, 2),
                        "discount_pct": discount,
                        "url": str(url)[:300], "brand": str(brand)[:100],
                        "available": available, "rating": rating, "timestamp": ts,
                    })
            except Exception as e:
                log.debug(f"    parse Ripley error: {e}")
        return items

    def _fetch_html(self, query, page, category, batch_id):
        try:
            url  = f"https://simple.ripley.com.pe/search?q={requests.utils.quote(query)}&page={page}"
            resp = requests.get(url, headers=_headers("https://simple.ripley.com.pe/"), timeout=20)
            if resp.status_code != 200: return []
            soup  = BeautifulSoup(resp.text, "html.parser")
            items = []
            ts    = datetime.now(timezone.utc).isoformat()
            for card in soup.select("div[class*='catalog-product'],div[class*='ProductCard']"):
                try:
                    title_el = card.select_one("div[class*='product-title'],span[class*='title']")
                    price_el = card.select_one("li[class*='price-sale'],span[class*='price']")
                    link_el  = card.select_one("a[href]")
                    if not title_el or not price_el: continue
                    title    = title_el.get_text(strip=True)
                    raw      = re.sub(r"[^\d]", "", price_el.get_text(strip=True))
                    price    = float(raw) if raw else 0.0
                    href     = link_el.get("href","") if link_el else ""
                    full_url = (f"https://simple.ripley.com.pe{href}"
                                if href and not href.startswith("http") else href)
                    if price > 0 and title:
                        items.append({
                            "batch_id": batch_id, "source": "ripley",
                            "category": category, "title": title[:200],
                            "price_pen": price, "price_original_pen": 0.0,
                            "discount_pct": 0.0, "url": full_url[:300],
                            "brand": "", "available": True,
                            "rating": 0.0, "timestamp": ts,
                        })
                except: continue
            return items
        except Exception as e:
            log.error(f"    Ripley HTML error: {e}")
            return []

# ══════════════════════════════════════════════════════════════════════════════
# SCRAPER 3 — HIRAOKA PE  ✅ FIX 3: implementación completa
# ══════════════════════════════════════════════════════════════════════════════
class HiraokaScraper:
    BASE = "https://www.hiraoka.com.pe"

    CATEGORY_PATHS = {
        "CPU":         "/procesadores-y-accesorios",
        "GPU":         "/tarjetas-de-video",
        "RAM":         "/memorias-ram",
        "SSD":         "/discos-solidos-ssd",
        "MOTHERBOARD": "/placas-madre",
        "PSU":         "/fuentes-de-poder",
        "COOLER":      "/coolers-cpu",
        "CASE":        "/cases-gabinetes",
    }

    def search(self, query: str, category: str, batch_id: str, max_pages: int = MAX_PAGES) -> list:
        items    = []
        cat_path = self.CATEGORY_PATHS.get(category)

        if cat_path:
            # Modo principal: URL de categoría directa con paginación
            for page in range(1, max_pages + 1):
                log.info(f"  [Hiraoka] {category} | categoría directa | pág {page}")
                page_items = self._fetch_category(cat_path, page, category, batch_id)
                items.extend(page_items)
                log.info(f"    → {len(page_items)} items (total: {len(items)})")
                if not page_items:
                    break
                time.sleep(DELAY_REQ)
        else:
            # Fallback: búsqueda por texto
            for page in range(1, min(max_pages, 10) + 1):
                log.info(f"  [Hiraoka] {category} | búsqueda '{query[:30]}' | pág {page}")
                page_items = self._fetch_search(query, page, category, batch_id)
                items.extend(page_items)
                log.info(f"    → {len(page_items)} items (total: {len(items)})")
                if not page_items:
                    break
                time.sleep(DELAY_REQ)

        return items

    def _fetch_category(self, cat_path: str, page: int, category: str, batch_id: str) -> list:
        """Fetch por URL de categoría directa — más estable y con más productos."""
        try:
            # Hiraoka usa ?p=N para paginación
            url  = f"{self.BASE}{cat_path}?p={page}"
            resp = requests.get(url, headers=_headers(self.BASE + "/"), timeout=25)
            if resp.status_code == 404:
                log.debug(f"    Hiraoka 404: {url}")
                return []
            if resp.status_code != 200:
                log.warning(f"    Hiraoka HTTP {resp.status_code}: {url}")
                return []
            return self._parse_html(resp.text, category, batch_id, base_url=url)
        except Exception as e:
            log.error(f"    Hiraoka category error: {e}")
            return []

    def _fetch_search(self, query: str, page: int, category: str, batch_id: str) -> list:
        """Fallback: búsqueda por texto en Hiraoka."""
        try:
            url  = f"{self.BASE}/catalogsearch/result/?q={requests.utils.quote(query)}&p={page}"
            resp = requests.get(url, headers=_headers(self.BASE + "/"), timeout=25)
            if resp.status_code != 200:
                return []
            return self._parse_html(resp.text, category, batch_id, base_url=url)
        except Exception as e:
            log.error(f"    Hiraoka search error: {e}")
            return []

    def _parse_html(self, html: str, category: str, batch_id: str, base_url: str = "") -> list:
        """Parser HTML unificado para Hiraoka (Magento 2)."""
        soup  = BeautifulSoup(html, "html.parser")
        items = []
        ts    = datetime.now(timezone.utc).isoformat()

        # Selectores de tarjeta de producto (Magento 2)
        card_selectors = [
            "li.product-item",
            "div.product-item-info",
            "div[class*='product-item']",
            "li[class*='item product']",
        ]
        cards = []
        for sel in card_selectors:
            cards = soup.select(sel)
            if cards:
                break

        if not cards:
            log.debug(f"    Hiraoka: sin tarjetas en {base_url}")
            return []

        for card in cards:
            try:
                # Título
                title_el = (
                    card.select_one("a.product-item-link") or
                    card.select_one("strong.product-item-name a") or
                    card.select_one("a[class*='product-item-link']") or
                    card.select_one("span[class*='product-name']")
                )
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title:
                    continue

                # Precio — Magento 2 usa data-price-type
                price_pen  = 0.0
                price_orig = 0.0

                # Precio final (con descuento)
                final_el = (
                    card.select_one("span[data-price-type='finalPrice'] span.price") or
                    card.select_one("span[class*='price-final'] span.price") or
                    card.select_one("span.special-price span.price") or
                    card.select_one("span.price")
                )
                if final_el:
                    raw = re.sub(r"[^\d.]", "", final_el.get_text(strip=True))
                    try:
                        price_pen = float(raw)
                    except:
                        pass

                # Precio original (sin descuento)
                orig_el = (
                    card.select_one("span[data-price-type='oldPrice'] span.price") or
                    card.select_one("span.old-price span.price") or
                    card.select_one("span[class*='regular-price'] span.price")
                )
                if orig_el:
                    raw = re.sub(r"[^\d.]", "", orig_el.get_text(strip=True))
                    try:
                        price_orig = float(raw)
                    except:
                        pass

                if price_pen == 0:
                    continue

                # Descuento
                discount = 0.0
                if price_orig > price_pen > 0:
                    discount = round((price_orig - price_pen) / price_orig * 100, 1)

                # URL
                link_el  = card.select_one("a.product-item-link") or card.select_one("a[href*='hiraoka']")
                item_url = link_el.get("href", "") if link_el else ""
                if item_url and not item_url.startswith("http"):
                    item_url = self.BASE + item_url

                # Marca
                brand_el = (
                    card.select_one("div.product-item-brand") or
                    card.select_one("span[class*='brand']") or
                    card.select_one("div[class*='brand']")
                )
                brand = brand_el.get_text(strip=True) if brand_el else ""

                # Disponibilidad
                stock_el  = card.select_one("div.stock") or card.select_one("span[class*='stock']")
                available = True
                if stock_el:
                    available = "unavailable" not in stock_el.get("class", [])

                # Rating
                rating_el = card.select_one("span.rating-result") or card.select_one("div[class*='rating']")
                rating    = 0.0
                if rating_el:
                    style = rating_el.get("style", "")
                    m     = re.search(r"width:\s*([\d.]+)%", style)
                    if m:
                        rating = round(float(m.group(1)) / 20, 1)  # 100% → 5.0

                items.append({
                    "batch_id":           batch_id,
                    "source":             "hiraoka",
                    "category":           category,
                    "title":              title[:200],
                    "price_pen":          round(price_pen, 2),
                    "price_original_pen": round(price_orig, 2),
                    "discount_pct":       discount,
                    "url":                item_url[:300],
                    "brand":              brand[:100],
                    "available":          available,
                    "rating":             rating,
                    "timestamp":          ts,
                })
            except Exception as e:
                log.debug(f"    parse Hiraoka card error: {e}")
                continue

        return items

# ══════════════════════════════════════════════════════════════════════════════
# RUNNER PRINCIPAL  ✅ FIX 4: función run_competencia() implementada
# ══════════════════════════════════════════════════════════════════════════════
def run_competencia(batch_id: str, sources: list = None, categories: list = None):
    if sources is None:
        sources = ["falabella", "ripley", "hiraoka"]
    if categories is None:
        categories = list(CATEGORY_QUERIES_PE.keys())

    writer   = CompetenciaCSVWriter(batch_id)
    scrapers = {}
    if "falabella" in sources: scrapers["falabella"] = FalabellaScraper()
    if "ripley"    in sources: scrapers["ripley"]    = RipleyScraper()
    if "hiraoka"   in sources: scrapers["hiraoka"]   = HiraokaScraper()

    total_written = 0
    stats         = {s: 0 for s in scrapers}

    for category in categories:
        queries = CATEGORY_QUERIES_PE.get(category, [category.lower()])
        log.info(f"\n{'='*60}")
        log.info(f"CATEGORÍA: {category} ({len(queries)} queries)")
        log.info(f"{'='*60}")

        for query in queries:
            for src_name, scraper in scrapers.items():
                try:
                    items   = scraper.search(query, category, batch_id, MAX_PAGES)
                    written = writer.write(items)
                    stats[src_name] += written
                    total_written   += written
                except Exception as e:
                    log.error(f"  [{src_name}] error en '{query}': {e}")
                time.sleep(DELAY_REQ)
            time.sleep(DELAY_CAT)

    log.info(f"\n{'='*60}")
    log.info(f"COMPETENCIA COMPLETA — {total_written} items escritos")
    for src, count in stats.items():
        log.info(f"  {src:<12}: {count:>6} items")
    log.info(f"CSV: {writer.path}")
    log.info(f"{'='*60}")

    return writer.path, total_written, stats

if __name__ == "__main__":
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_competencia(batch_id)
