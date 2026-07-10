"""
scraper_competencia.py  v1.0
════════════════════════════
Fuentes de PRECIO DE COMPETENCIA (referencia de precio techo PE):
  - Falabella PE  (API JSON interna — sin límite conocido)
  - Ripley PE     (API JSON interna)
  - Hiraoka PE    (HTML con URLs de categoría directa)

Salida: competencia_YYYYMMDD_HHMMSS.csv
Columnas: batch_id | source | category | title | price_pen |
          price_original_pen | discount_pct | url |
          brand | available | rating | timestamp
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

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/home/user"))
MAX_PAGES  = int(os.getenv("MAX_PAGES_COMP", "30"))
DELAY_REQ  = float(os.getenv("DELAY_REQ", "2.0"))
DELAY_CAT  = float(os.getenv("DELAY_CAT", "4.0"))

# ── Queries por categoría (en español para tiendas PE) ────────────────────────
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
        self.path = OUTPUT_DIR / f"competencia_{batch_id}.csv"
        self._seen: set[str] = set()
        if not self.path.exists():
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=COMP_FIELDS).writeheader()
        log.info(f"CSV competencia → {self.path}")

    def _fp(self, row: dict) -> str:
        key = f"{row['source']}|{row['title'][:60]}|{row['price_pen']}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def write(self, rows: list[dict]) -> int:
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
        "User-Agent":  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Accept":      "application/json, text/plain, */*",
        "Referer":     referer,
    }

# ══════════════════════════════════════════════════════════════════════════════
# SCRAPER 1 — FALABELLA PE (API JSON interna)
# ══════════════════════════════════════════════════════════════════════════════
class FalabellaScraper:
    """
    Falabella expone una API JSON interna de búsqueda.
    Devuelve hasta 24 productos/página con precios completos.
    No requiere autenticación.
    """
    API_BASE = "https://www.falabella.com.pe/s/browse/v1/listing/pe"

    def search(self, query: str, category: str, batch_id: str, max_pages: int = MAX_PAGES) -> list[dict]:
        items = []
        for page in range(1, max_pages + 1):
            log.info(f"  [Falabella] {category} | '{query[:40]}' | pág {page}")
            page_items = self._fetch_page(query, page, category, batch_id)
            items.extend(page_items)
            log.info(f"    → {len(page_items)} items (total: {len(items)})")
            if len(page_items) == 0:
                break
            time.sleep(DELAY_REQ)
        return items

    def _fetch_page(self, query: str, page: int, category: str, batch_id: str) -> list[dict]:
        # Método 1: API JSON interna
        try:
            params = {
                "Ntt":       query,
                "page":      page,
                "imageSize": "zoom",
                "zones":     "13",
            }
            resp = requests.get(
                self.API_BASE, params=params,
                headers=_json_headers("https://www.falabella.com.pe/"),
                timeout=20
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    items = self._parse_api(data, category, batch_id)
                    if items:
                        return items
                except:
                    pass
        except Exception as e:
            log.debug(f"    Falabella API error: {e}")

        # Método 2: Fallback HTML + __NEXT_DATA__
        return self._fetch_html(query, page, category, batch_id)

    def _parse_api(self, data: dict, category: str, batch_id: str) -> list[dict]:
        items = []
        ts = datetime.now(timezone.utc).isoformat()

        # Navegar estructura: data.state.resultList o data.results
        def extract_products(obj, depth=0):
            if depth > 8:
                return []
            found = []
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict):
                        # Detectar producto por presencia de campos clave
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

                title = (
                    p.get("displayName") or p.get("productName") or
                    p.get("name") or p.get("title") or ""
                )

                # Precio — múltiples estructuras de Falabella
                price_pen = 0.0
                price_orig = 0.0

                prices_obj = p.get("prices") or p.get("price") or {}
                if isinstance(prices_obj, list):
                    for pr in prices_obj:
                        if isinstance(pr, dict):
                            val = pr.get("price") or pr.get("value") or 0
                            label = str(pr.get("label","")).lower()
                            if "oferta" in label or "precio" in label or not label:
                                try:
                                    price_pen = float(str(val).replace(",",""))
                                except:
                                    pass
                            elif "normal" in label or "original" in label:
                                try:
                                    price_orig = float(str(val).replace(",",""))
                                except:
                                    pass
                elif isinstance(prices_obj, dict):
                    for key in ["offerPrice","salePrice","normalPrice","originalPrice","price"]:
                        val = prices_obj.get(key)
                        if val:
                            raw = re.sub(r"[^\d.]", "", str(val))
                            try:
                                price_pen = float(raw)
                                break
                            except:
                                pass
                    for key in ["normalPrice","originalPrice","regularPrice"]:
                        val = prices_obj.get(key)
                        if val:
                            raw = re.sub(r"[^\d.]", "", str(val))
                            try:
                                price_orig = float(raw)
                                break
                            except:
                                pass

                # Fallback directo
                if price_pen == 0:
                    for key in ["offerPrice","salePrice","price","currentPrice"]:
                        val = p.get(key)
                        if val:
                            raw = re.sub(r"[^\d.]", "", str(val))
                            try:
                                price_pen = float(raw)
                                break
                            except:
                                pass

                discount = 0.0
                if price_orig > 0 and price_pen > 0 and price_orig > price_pen:
                    discount = round((price_orig - price_pen) / price_orig * 100, 1)

                brand = p.get("brand") or p.get("brandName") or ""
                url_path = p.get("url") or p.get("pdpUrl") or p.get("productUrl") or ""
                url = f"https://www.falabella.com.pe{url_path}" if url_path and not url_path.startswith("http") else url_path
                rating = float(p.get("rating") or p.get("averageRating") or 0)
                available = bool(p.get("available") or p.get("isAvailable") or True)

                if price_pen > 0 and title:
                    items.append({
                        "batch_id":          batch_id,
                        "source":            "falabella",
                        "category":          category,
                        "title":             str(title)[:200],
                        "price_pen":         round(price_pen, 2),
                        "price_original_pen": round(price_orig, 2),
                        "discount_pct":      discount,
                        "url":               str(url)[:300],
                        "brand":             str(brand)[:100],
                        "available":         available,
                        "rating":            rating,
                        "timestamp":         ts,
                    })
            except Exception as e:
                log.debug(f"    parse product error: {e}")
                continue
        return items

    def _fetch_html(self, query: str, page: int, category: str, batch_id: str) -> list[dict]:
        """Fallback: scraping HTML con __NEXT_DATA__"""
        try:
            url = f"https://www.falabella.com.pe/falabella-pe/search?Ntt={requests.utils.quote(query)}&page={page}"
            resp = requests.get(url, headers=_headers("https://www.falabella.com.pe/"), timeout=20)
            if resp.status_code != 200:
                return []
            html = resp.text

            # Buscar __NEXT_DATA__
            m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1))
                    items = self._parse_api(data, category, batch_id)
                    if items:
                        return items
                except:
                    pass

            # Fallback CSS selectores
            soup = BeautifulSoup(html, "html.parser")
            items = []
            ts = datetime.now(timezone.utc).isoformat()
            for card in soup.select("div[class*='product-card'], div[class*='ProductCard'], li[class*='search-results']"):
                try:
                    title_el = card.select_one("b[class*='pod-title'], span[class*='pod-title'], a[class*='pod-title']")
                    price_el = card.select_one("span[class*='copy10'], li[class*='prices-0'], span[class*='price']")
                    if not title_el or not price_el:
                        continue
                    title = title_el.get_text(strip=True)
                    raw = re.sub(r"[^\d]", "", price_el.get_text(strip=True))
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
                except:
                    continue
            return items
        except Exception as e:
            log.error(f"    Falabella HTML error: {e}")
            return []

# ══════════════════════════════════════════════════════════════════════════════
# SCRAPER 2 — RIPLEY PE (API JSON interna)
# ══════════════════════════════════════════════════════════════════════════════
class RipleyScraper:
    """
    Ripley PE tiene una API de búsqueda JSON accesible públicamente.
    Devuelve hasta 40 productos/página.
    """
    API_BASE = "https://simple.ripley.com.pe/api/search"

    def search(self, query: str, category: str, batch_id: str, max_pages: int = MAX_PAGES) -> list[dict]:
        items = []
        for page in range(1, max_pages + 1):
            log.info(f"  [Ripley] {category} | '{query[:40]}' | pág {page}")
            page_items = self._fetch_page(query, page, category, batch_id)
            items.extend(page_items)
            log.info(f"    → {len(page_items)} items (total: {len(items)})")
            if len(page_items) == 0:
                break
            time.sleep(DELAY_REQ)
        return items

    def _fetch_page(self, query: str, page: int, category: str, batch_id: str) -> list[dict]:
        # Método 1: API JSON
        try:
            params = {
                "q":       query,
                "page":    page,
                "perPage": 40,
            }
            resp = requests.get(
                self.API_BASE, params=params,
                headers=_json_headers("https://simple.ripley.com.pe/"),
                timeout=20
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    items = self._parse_api(data, category, batch_id)
                    if items:
                        return items
                except:
                    pass
        except Exception as e:
            log.debug(f"    Ripley API error: {e}")

        # Método 2: Fallback HTML
        return self._fetch_html(query, page, category, batch_id)

    def _parse_api(self, data: dict, category: str, batch_id: str) -> list[dict]:
        items = []
        ts = datetime.now(timezone.utc).isoformat()
        products = data.get("results") or data.get("products") or data.get("items") or []
        if not isinstance(products, list):
            # Buscar recursivamente
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
                title = p.get("displayName") or p.get("name") or p.get("title") or ""
                brand = p.get("brand") or ""

                # Precio
                price_pen = 0.0
                price_orig = 0.0
                prices = p.get("prices") or {}
                if isinstance(prices, dict):
                    for key in ["normalPrice","offerPrice","salePrice","price"]:
                        val = prices.get(key)
                        if val:
                            try:
                                price_pen = float(str(val).replace(",",""))
                                break
                            except:
                                pass
                    for key in ["normalPrice","originalPrice","regularPrice"]:
                        val = prices.get(key)
                        if val:
                            try:
                                price_orig = float(str(val).replace(",",""))
                                break
                            except:
                                pass
                elif isinstance(prices, list):
                    for pr in prices:
                        val = pr.get("price") or pr.get("value") or 0
                        try:
                            price_pen = float(val)
                            break
                        except:
                            pass

                # Fallback precio directo
                if price_pen == 0:
                    for key in ["price","offerPrice","salePrice","normalPrice"]:
                        val = p.get(key)
                        if val:
                            raw = re.sub(r"[^\d.]", "", str(val))
                            try:
                                price_pen = float(raw)
                                break
                            except:
                                pass

                discount = 0.0
                if price_orig > price_pen > 0:
                    discount = round((price_orig - price_pen) / price_orig * 100, 1)

                url_path = p.get("url") or p.get("pdpUrl") or ""
                url = f"https://simple.ripley.com.pe{url_path}" if url_path and not url_path.startswith("http") else url_path
                rating = float(p.get("rating") or p.get("averageRating") or 0)
                available = bool(p.get("available") or p.get("isAvailable") or True)

                if price_pen > 0 and title:
                    items.append({
                        "batch_id":          batch_id,
                        "source":            "ripley",
                        "category":          category,
                        "title":             str(title)[:200],
                        "price_pen":         round(price_pen, 2),
                        "price_original_pen": round(price_orig, 2),
                        "discount_pct":      discount,
                        "url":               str(url)[:300],
                        "brand":             str(brand)[:100],
                        "available":         available,
                        "rating":            rating,
                        "timestamp":         ts,
                    })
            except Exception as e:
                log.debug(f"    parse Ripley error: {e}")
                continue
        return items

    def _fetch_html(self, query: str, page: int, category: str, batch_id: str) -> list[dict]:
        try:
            url = f"https://simple.ripley.com.pe/search?q={requests.utils.quote(query)}&page={page}"
            resp = requests.get(url, headers=_headers("https://simple.ripley.com.pe/"), timeout=20)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            items = []
            ts = datetime.now(timezone.utc).isoformat()
            for card in soup.select("div[class*='catalog-product'], div[class*='ProductCard']"):
                try:
                    title_el = card.select_one("div[class*='product-title'], span[class*='title']")
                    price_el = card.select_one("li[class*='price-sale'], span[class*='price']")
                    link_el  = card.select_one("a[href]")
                    if not title_el or not price_el:
                        continue
                    title = title_el.get_text(strip=True)
                    raw = re.sub(r"[^\d]", "", price_el.get_text(strip=True))
                    price = float(raw) if raw else 0.0
                    href = link_el.get("href","") if link_el else ""
                    full_url = f"https://simple.ripley.com.pe{href}" if href and not href.startswith("http") else href
                    if price > 0 and title:
                        items.append({
                            "batch_id": batch_id, "source": "ripley",
                            "category": category, "title": title[:200],
                            "price_pen": price, "price_original_pen": 0.0,
                            "discount_pct": 0.0, "url": full_url[:300],
                            "brand": "", "available": True,
                            "rating": 0.0, "timestamp": ts,
                        })
                except:
                    continue
            return items
        except Exception as e:
            log.error(f"    Ripley HTML error: {e}")
            return []

# ══════════════════════════════════════════════════════════════════════════════
# SCRAPER 3 — HIRAOKA PE (HTML con URLs de categoría directa)
# ══════════════════════════════════════════════════════════════════════════════
class HiraokaScraper:
    """
    Hiraoka PE: scraping HTML con URLs de categoría directa.
    Más estable que búsqueda por texto.
    """
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

    # Selectores CSS confirmados en Hiraoka
    SELECTORS = {
        "card":  ["li.product-item", "div.product-item-info", "div[class*='product-item']"],
        "title": ["a.product-item-link", "strong.product-item-name a", "a[class*='product-item-link']"],
        "price": ["span.price", "span[class*='price-final']", "span[data-price-type='finalPrice']"],
        "brand": ["div.product-item-brand", "span[class*='brand']"],
        "url":   ["a.product-item-link", "a[class*='product-item-link']"],
    }

    def search(self, query: str, category: str, batch_id: str, max_pages: int = MAX_PAGES) -> list[dict]:
        """
        Para Hiraoka usamos URLs de categoría directa (más estable).
        El parámetro query se usa como fallback de búsqueda.
        """
        items = []
        cat_path = self.CATEGORY_PATHS.get(category)