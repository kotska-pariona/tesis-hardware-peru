#!/usr/bin/env python3
"""
scraper_competencia.py  v4.2
════════════════════════════════════════════════════════════════════
Scraper de precios de competencia — Mercado peruano (precio techo)

Fuentes:
  - Falabella PE   → API JSON v2 + fallback HTML (__NEXT_DATA__)
  - Hiraoka PE     → Magento 2 HTML (categoría directa + fallback búsqueda)
  - Coolbox PE     → HTML scraping (hardware/gaming especializado)
  - Compumundo PE  → Magento 2 HTML (deshabilitado por defecto — SSL mismatch)
  - Ripley PE      → PENDIENTE (requiere Playwright — 403 Cloudflare)

Fixes v4.2 (sobre v4.1):
  [SC26] _extract_sku_from_url(): helper para derivar SKU estable desde URL
         cuando el HTML/JSON no expone un ID explícito.
  [SC27] FalabellaScraper: productId/id/skuId propagado al record final —
         en v4.1 se usaba solo para dedup interno pero no se guardaba,
         causando colisiones en merge_to_master().
  [SC28] Hiraoka/Coolbox/Compumundo: extrae sku desde data-product-id
         (atributo Magento 2 estándar) antes de caer a _extract_sku_from_url.
  [SC29] COMP_FIELDS_PUBLIC: campo sku agregado — v4.1 lo omitía del output.
  [SC30] _dedup(): clave de identidad = sku > url > title (precio excluido).
         En v4.1 el precio formaba parte de la clave, causando duplicados
         intra-batch cuando el mismo producto aparecía con precios distintos
         en dos queries de la misma categoría.
  [SC31] FalabellaScraper: IDs vacíos ya no entran al set seen_ids —
         evita que todos los productos sin ID colisionen entre sí.
"""

import os
import re
import time
import json
import hashlib
import logging
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

try:
    from fake_useragent import UserAgent as _UA
    _ua_gen = _UA()
except ImportError:
    _ua_gen = None

log = logging.getLogger(__name__)

# ── Path fix ──────────────────────────────────────────────────────────────
import sys
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "configuracion"))
# ─────────────────────────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN (env vars con defaults)
# ══════════════════════════════════════════════════════════════════════════
_DEFAULT_OUTPUT    = str(_ROOT / "data" / "raw")
OUTPUT_DIR         = Path(os.getenv("OUTPUT_DIR", _DEFAULT_OUTPUT))
MAX_PAGES          = int(os.getenv("MAX_PAGES_COMP", "5"))
DELAY_REQ          = float(os.getenv("DELAY_REQ", "2.0"))
DELAY_CAT          = float(os.getenv("DELAY_CAT", "6.0"))
MAX_QUERIES_COMP   = int(os.getenv("MAX_QUERIES_COMP", "2"))
PRICE_MIN_PEN      = float(os.getenv("PRICE_MIN_PEN", "10.0"))
PRICE_MAX_PEN      = float(os.getenv("PRICE_MAX_PEN", "50000.0"))
COMPUMUNDO_ENABLED = os.getenv("COMPUMUNDO_ENABLED", "false").lower() == "true"

# [PP4] Chrome 136 — julio 2026
_UA_FALLBACK = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

# ══════════════════════════════════════════════════════════════════════════
# QUERIES POR CATEGORÍA
# ══════════════════════════════════════════════════════════════════════════
CATEGORY_QUERIES_PE: Dict[str, List[str]] = {
    "CPU": [
        "procesador intel core i5",
        "procesador intel core i7",
        "procesador amd ryzen 5",
        "procesador amd ryzen 7",
        "intel core ultra",
    ],
    "GPU": [
        "tarjeta de video nvidia rtx 4060",
        "tarjeta grafica geforce rtx",
        "tarjeta de video amd radeon rx",
        "nvidia rtx 4070",
        "nvidia rtx 5070",
    ],
    "RAM": [
        "memoria ram ddr4 16gb",
        "memoria ram ddr5",
        "memoria ram kingston fury",
        "memoria ram corsair",
        "memoria ram 32gb",
    ],
    "SSD": [
        "disco solido nvme 1tb",
        "ssd m2 pcie",
        "disco solido samsung 990",
        "disco solido wd black",
        "ssd nvme 2tb",
    ],
    "MOTHERBOARD": [
        "placa madre intel z790",
        "placa madre amd b650",
        "motherboard asus rog",
        "placa madre msi",
        "placa madre gigabyte",
    ],
    "PSU": [
        "fuente de poder 850w gold",
        "fuente corsair rm850x",
        "fuente poder 80 plus",
        "fuente de poder modular",
        "fuente poder 1000w",
    ],
    "COOLER": [
        "cooler liquido 240mm cpu",
        "disipador cpu noctua",
        "refrigeracion liquida cpu",
        "cooler cpu be quiet",
        "aio 360mm cpu",
    ],
    "CASE": [
        "case gamer atx vidrio templado",
        "case lian li",
        "gabinete fractal design",
        "case corsair",
        "gabinete nzxt",
    ],
}

# ══════════════════════════════════════════════════════════════════════════
# CAMPOS DE SALIDA PÚBLICOS
# ══════════════════════════════════════════════════════════════════════════
COMP_FIELDS_PUBLIC = [
    "batch_id",
    "source",
    "category",
    "sku",        # [SC29] agregado en v4.2
    "title",
    "price_pen",
    "price_orig_pen",
    "discount_pct",
    "url",
    "brand",
    "available",
    "rating",
    "timestamp",
]

# ══════════════════════════════════════════════════════════════════════════
# UTILIDADES COMPARTIDAS
# ══════════════════════════════════════════════════════════════════════════

def _get_ua() -> str:
    """User-Agent rotativo con fallback."""
    return _ua_gen.random if _ua_gen else _UA_FALLBACK


def _make_session(verify_ssl: bool = True) -> requests.Session:
    """
    Session HTTP con retry automático.
    backoff_factor=1.5 → esperas: 1.5s, 3s, 6s
    """
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    if not verify_ssl:
        session.verify = False
    return session


def _headers_json(referer: str = "") -> dict:
    return {
        "User-Agent":  _get_ua(),
        "Accept":      "application/json, text/plain, */*",
        "Referer":     referer,
        "Connection":  "keep-alive",
    }


def _headers_html(referer: str = "") -> dict:
    return {
        "User-Agent":      _get_ua(),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
        "Referer":         referer,
        "Connection":      "keep-alive",
    }


def _parse_price_str(text: str) -> Optional[float]:
    """
    Limpia strings de precio peruanos (S/. 1,299.00 → 1299.0).
    Maneja separadores de miles y decimales en formato peruano.
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
            clean = (clean.replace(",", ".")
                     if len(parts) == 2 and len(parts[1]) <= 2
                     else clean.replace(",", ""))
        val = float(clean)
        return val if val > 0 else None
    except ValueError:
        return None


def _valid_price(price: Optional[float]) -> bool:
    """Valida que el precio esté dentro del rango permitido."""
    return price is not None and PRICE_MIN_PEN <= price <= PRICE_MAX_PEN


def _extract_sku_from_url(url: str) -> Optional[str]:
    """
    [SC26] Extrae SKU estable desde URL cuando el HTML no expone un ID.
    - Falabella: /p/<productId>-<slug> → extrae el ID numérico
    - Magento 2: último segmento del path antes de .html
    """
    if not url:
        return None
    # Falabella: /p/12345678-nombre-producto
    m = re.search(r"/p/(\d{6,})", url)
    if m:
        return m.group(1)
    # Magento 2: /categoria/nombre-producto.html
    m = re.search(r"/([^/]+)\.html", url)
    if m:
        slug = m.group(1)
        return slug[:64] if slug else None
    # Fallback: último segmento del path
    path = url.rstrip("/").split("/")[-1].split("?")[0]
    return path[:64] if path else None


def _make_fingerprint(source: str, identity: str) -> str:
    """MD5 de 12 chars para dedup."""
    raw = f"{source}|{identity}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _dedup(records: List[Dict]) -> List[Dict]:
    """
    [SC30] Deduplicación intra-batch.
    Clave de identidad: sku > url > title (precio EXCLUIDO).
    [SC31] IDs vacíos no entran al set seen.
    """
    seen: set = set()
    out:  List[Dict] = []
    for r in records:
        source = r.get("source", "")
        sku    = str(r.get("sku") or "").strip()
        url    = str(r.get("url") or "").strip()
        title  = str(r.get("title") or "").strip()

        identity = sku or url or title
        if not identity:
            out.append(r)
            continue

        fp = _make_fingerprint(source, identity)
        if fp not in seen:
            seen.add(fp)
            out.append(r)
    return out


# ══════════════════════════════════════════════════════════════════════════
# FALABELLA SCRAPER
# ══════════════════════════════════════════════════════════════════════════
class FalabellaScraper:
    """
    Falabella PE — API JSON v2 con fallback a __NEXT_DATA__ HTML.
    Zona: Lima Metropolitana (zones=150101).
    """
    BASE_API = (
        "https://www.falabella.com.pe/s/browse/v2/listing/pe"
        "?zones=150101&page={page}&productsPerPage=50"
        "&sortBy=BEST_MATCH&query={query}"
    )
    BASE_URL  = "https://www.falabella.com.pe"
    SOURCE    = "falabella_pe"

    def __init__(self):
        self.session = _make_session()

    def close(self):
        self.session.close()

    def _fetch_api(self, query: str, page: int) -> List[Dict]:
        """Llama a la API v2 y retorna lista de productos raw."""
        url = self.BASE_API.format(page=page, query=requests.utils.quote(query))
        try:
            r = self.session.get(
                url,
                headers=_headers_json(referer=self.BASE_URL),
                timeout=20,
            )
            if r.status_code != 200:
                return []
            data = r.json()
            # Estructura: data.data.results[] o data.results[]
            results = (
                data.get("data", {}).get("results")
                or data.get("results")
                or []
            )
            if not isinstance(results, list):
                return []
            return results
        except Exception as e:
            log.debug(f"[Falabella] API error p{page}: {e}")
            return []

    def _parse_api_product(self, item: Dict, category: str, batch_id: str) -> Optional[Dict]:
        """Convierte un item de la API v2 al schema público."""
        try:
            # [SC27] Propagar productId al record final
            pid = (
                str(item.get("productId") or item.get("id") or item.get("skuId") or "")
                .strip()
            )
            title = (item.get("displayName") or item.get("name") or "").strip()
            if not title:
                return None

            # Precios: oferta vs normal
            prices = item.get("prices", {}) or {}
            offer  = prices.get("offerPrice") or prices.get("salePrice")
            normal = prices.get("originalPrice") or prices.get("normalPrice")
            price_pen      = _parse_price_str(str(offer  or ""))
            price_orig_pen = _parse_price_str(str(normal or ""))
            if not _valid_price(price_pen):
                price_pen = _parse_price_str(str(normal or ""))
                price_orig_pen = None
            if not _valid_price(price_pen):
                return None

            discount_pct = None
            if price_pen and price_orig_pen and price_orig_pen > price_pen:
                discount_pct = round((1 - price_pen / price_orig_pen) * 100, 1)

            brand  = (item.get("brand") or "").strip() or None
            rating = item.get("rating") or item.get("stars") or None
            url_path = item.get("url") or item.get("pdpUrl") or ""
            url_full = (
                url_path if url_path.startswith("http")
                else f"{self.BASE_URL}{url_path}"
            )

            # [SC26] SKU: pid > extraído de URL
            sku = pid if pid else _extract_sku_from_url(url_full)

            return {
                "batch_id":      batch_id,
                "source":        self.SOURCE,
                "category":      category,
                "sku":           sku,
                "title":         title,
                "price_pen":     price_pen,
                "price_orig_pen": price_orig_pen,
                "discount_pct":  discount_pct,
                "url":           url_full,
                "brand":         brand,
                "available":     True,
                "rating":        rating,
                "timestamp":     datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            log.debug(f"[Falabella] parse error: {e}")
            return None

    def scrape(self, category: str, queries: List[str], batch_id: str) -> List[Dict]:
        records: List[Dict] = []
        seen_ids: set = set()

        for query in queries[:MAX_QUERIES_COMP]:
            log.info(f"  [Falabella] {category} | '{query}'")
            for page in range(1, MAX_PAGES + 1):
                raw = self._fetch_api(query, page)
                if not raw:
                    log.debug(f"    p{page}: vacío — stop")
                    break

                new_in_page = 0
                for item in raw:
                    rec = self._parse_api_product(item, category, batch_id)
                    if not rec:
                        continue
                    # [SC31] IDs vacíos no entran al set
                    pid = str(item.get("productId") or item.get("id") or "").strip()
                    if pid:
                        if pid in seen_ids:
                            continue
                        seen_ids.add(pid)
                    records.append(rec)
                    new_in_page += 1

                log.debug(f"    p{page}: +{new_in_page}")
                if new_in_page == 0:
                    break
                time.sleep(DELAY_REQ)
            time.sleep(DELAY_CAT)

        log.info(f"  [Falabella] {category}: {len(records)} registros raw")
        return records


# ══════════════════════════════════════════════════════════════════════════
# HIRAOKA SCRAPER
# ══════════════════════════════════════════════════════════════════════════
class HiraokaScraper:
    """
    Hiraoka PE — Magento 2 HTML.
    Estrategia: categoría directa → fallback búsqueda.
    """
    BASE_URL = "https://www.hiraoka.com.pe"
    SOURCE   = "hiraoka_pe"

    CATEGORY_PATHS = {
        "CPU":         "/componentes/procesadores",
        "GPU":         "/componentes/tarjetas-de-video",
        "RAM":         "/componentes/memorias-ram",
        "SSD":         "/componentes/discos-solidos-ssd",
        "MOTHERBOARD": "/componentes/placas-madre",
        "PSU":         "/componentes/fuentes-de-poder",
        "COOLER":      "/componentes/coolers-y-refrigeracion",
        "CASE":        "/componentes/gabinetes",
    }

    def __init__(self):
        self.session = _make_session()

    def close(self):
        self.session.close()

    def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        try:
            r = self.session.get(url, headers=_headers_html(self.BASE_URL), timeout=20)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            return None
        except Exception as e:
            log.debug(f"[Hiraoka] fetch error: {e}")
            return None

    def _parse_products(self, soup: BeautifulSoup, category: str, batch_id: str) -> List[Dict]:
        records = []
        # Magento 2: li.product-item
        items = soup.select("li.product-item, div.product-item-info")
        for item in items:
            try:
                title_el = item.select_one("a.product-item-link, strong.product-item-name a")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                url_rel = title_el.get("href", "")
                url_full = url_rel if url_rel.startswith("http") else f"{self.BASE_URL}{url_rel}"

                # Precio Magento 2
                price_el = item.select_one("span[data-price-type='finalPrice'] span.price")
                price_pen = _parse_price_str(price_el.get_text() if price_el else "")
                if not _valid_price(price_pen):
                    continue

                orig_el = item.select_one("span[data-price-type='oldPrice'] span.price")
                price_orig_pen = _parse_price_str(orig_el.get_text() if orig_el else "")

                discount_pct = None
                if price_pen and price_orig_pen and price_orig_pen > price_pen:
                    discount_pct = round((1 - price_pen / price_orig_pen) * 100, 1)

                # [SC28] SKU desde data-product-id
                sku = (
                    item.get("data-product-id")
                    or item.select_one("[data-product-id]", {}).get("data-product-id") if item.select_one("[data-product-id]") else None
                    or _extract_sku_from_url(url_full)
                )

                stock_el = item.select_one(".stock, .availability")
                available = True
                if stock_el:
                    txt = stock_el.get_text(strip=True).lower()
                    available = "agotado" not in txt and "sin stock" not in txt

                records.append({
                    "batch_id":       batch_id,
                    "source":         self.SOURCE,
                    "category":       category,
                    "sku":            str(sku) if sku else None,
                    "title":          title,
                    "price_pen":      price_pen,
                    "price_orig_pen": price_orig_pen,
                    "discount_pct":   discount_pct,
                    "url":            url_full,
                    "brand":          None,
                    "available":      available,
                    "rating":         None,
                    "timestamp":      datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                log.debug(f"[Hiraoka] item parse error: {e}")
        return records

    def scrape(self, category: str, queries: List[str], batch_id: str) -> List[Dict]:
        records: List[Dict] = []
        cat_path = self.CATEGORY_PATHS.get(category)

        # Estrategia 1: categoría directa
        if cat_path:
            for page in range(1, MAX_PAGES + 1):
                url = f"{self.BASE_URL}{cat_path}?p={page}"
                soup = self._fetch_page(url)
                if not soup:
                    break
                page_recs = self._parse_products(soup, category, batch_id)
                if not page_recs:
                    break
                records.extend(page_recs)
                log.debug(f"  [Hiraoka] {category} p{page}: +{len(page_recs)}")
                time.sleep(DELAY_REQ)

        # Estrategia 2: fallback búsqueda
        if not records:
            for query in queries[:MAX_QUERIES_COMP]:
                search_url = f"{self.BASE_URL}/catalogsearch/result/?q={requests.utils.quote(query)}"
                soup = self._fetch_page(search_url)
                if soup:
                    page_recs = self._parse_products(soup, category, batch_id)
                    records.extend(page_recs)
                time.sleep(DELAY_REQ)

        log.info(f"  [Hiraoka] {category}: {len(records)} registros raw")
        return records


# ══════════════════════════════════════════════════════════════════════════
# COOLBOX SCRAPER
# ══════════════════════════════════════════════════════════════════════════
class CoolboxScraper:
    """
    Coolbox PE — tienda especializada en hardware y gaming.
    HTML scraping con detección de stock.
    """
    BASE_URL = "https://www.coolbox.pe"
    SOURCE   = "coolbox_pe"

    CATEGORY_PATHS = {
        "CPU":         "/procesadores",
        "GPU":         "/tarjetas-de-video",
        "RAM":         "/memorias-ram",
        "SSD":         "/almacenamiento/discos-solidos-ssd",
        "MOTHERBOARD": "/placas-madre",
        "PSU":         "/fuentes-de-poder",
        "COOLER":      "/refrigeracion",
        "CASE":        "/gabinetes",
    }

    def __init__(self):
        self.session = _make_session()

    def close(self):
        self.session.close()

    def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        try:
            r = self.session.get(url, headers=_headers_html(self.BASE_URL), timeout=20)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            return None
        except Exception as e:
            log.debug(f"[Coolbox] fetch error: {e}")
            return None

    def _parse_products(self, soup: BeautifulSoup, category: str, batch_id: str) -> List[Dict]:
        records = []
        items = soup.select("div.product-item, article.product-item, li.product-item")
        for item in items:
            try:
                title_el = item.select_one("h2.product-name a, h3.product-name a, a.product-item-link")
                if not title_el:
                    continue
                title    = title_el.get_text(strip=True)
                url_rel  = title_el.get("href", "")
                url_full = url_rel if url_rel.startswith("http") else f"{self.BASE_URL}{url_rel}"

                price_el = item.select_one(".price, .product-price, span.price")
                price_pen = _parse_price_str(price_el.get_text() if price_el else "")
                if not _valid_price(price_pen):
                    continue

                orig_el = item.select_one(".old-price .price, .price-old, del.price")
                price_orig_pen = _parse_price_str(orig_el.get_text() if orig_el else "")

                discount_pct = None
                if price_pen and price_orig_pen and price_orig_pen > price_pen:
                    discount_pct = round((1 - price_pen / price_orig_pen) * 100, 1)

                # [SC28] SKU desde data-product-id
                sku = (
                    item.get("data-product-id")
                    or _extract_sku_from_url(url_full)
                )

                # Detección de stock
                stock_txt = item.get_text(strip=True).lower()
                available = "agotado" not in stock_txt and "sin stock" not in stock_txt

                records.append({
                    "batch_id":       batch_id,
                    "source":         self.SOURCE,
                    "category":       category,
                    "sku":            str(sku) if sku else None,
                    "title":          title,
                    "price_pen":      price_pen,
                    "price_orig_pen": price_orig_pen,
                    "discount_pct":   discount_pct,
                    "url":            url_full,
                    "brand":          None,
                    "available":      available,
                    "rating":         None,
                    "timestamp":      datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                log.debug(f"[Coolbox] item parse error: {e}")
        return records

    def scrape(self, category: str, queries: List[str], batch_id: str) -> List[Dict]:
        records: List[Dict] = []
        cat_path = self.CATEGORY_PATHS.get(category)

        if cat_path:
            for page in range(1, MAX_PAGES + 1):
                url = f"{self.BASE_URL}{cat_path}?page={page}"
                soup = self._fetch_page(url)
                if not soup:
                    break
                page_recs = self._parse_products(soup, category, batch_id)
                if not page_recs:
                    break
                records.extend(page_recs)
                log.debug(f"  [Coolbox] {category} p{page}: +{len(page_recs)}")
                time.sleep(DELAY_REQ)

        log.info(f"  [Coolbox] {category}: {len(records)} registros raw")
        return records


# ══════════════════════════════════════════════════════════════════════════
# COMPUMUNDO SCRAPER (deshabilitado por defecto — SSL mismatch)
# ══════════════════════════════════════════════════════════════════════════
class CompumundoScraper:
    """
    Compumundo PE — Magento 2 HTML.
    Deshabilitado por defecto (COMPUMUNDO_ENABLED=false) — SSL mismatch.
    Si se habilita, usa verify=False y suprime InsecureRequestWarning.
    """
    BASE_URL = "https://www.compumundo.com.pe"
    SOURCE   = "compumundo_pe"

    CATEGORY_PATHS = {
        "CPU":         "/procesadores",
        "GPU":         "/tarjetas-de-video",
        "RAM":         "/memorias",
        "SSD":         "/discos-solidos",
        "MOTHERBOARD": "/placas-madre",
        "PSU":         "/fuentes-de-poder",
        "COOLER":      "/refrigeracion",
        "CASE":        "/gabinetes",
    }

    def __init__(self):
        if not COMPUMUNDO_ENABLED:
            log.info("[Compumundo] DESHABILITADO (COMPUMUNDO_ENABLED=false)")
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")
        self.session = _make_session(verify_ssl=False)

    def close(self):
        self.session.close()

    def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        if not COMPUMUNDO_ENABLED:
            return None
        try:
            r = self.session.get(url, headers=_headers_html(self.BASE_URL), timeout=20)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            return None
        except Exception as e:
            log.debug(f"[Compumundo] fetch error: {e}")
            return None

    def _parse_products(self, soup: BeautifulSoup, category: str, batch_id: str) -> List[Dict]:
        records = []
        items = soup.select("li.product-item, div.product-item-info")
        for item in items:
            try:
                title_el = item.select_one("a.product-item-link")
                if not title_el:
                    continue
                title    = title_el.get_text(strip=True)
                url_rel  = title_el.get("href", "")
                url_full = url_rel if url_rel.startswith("http") else f"{self.BASE_URL}{url_rel}"

                price_el = item.select_one("span[data-price-type='finalPrice'] span.price")
                price_pen = _parse_price_str(price_el.get_text() if price_el else "")
                if not _valid_price(price_pen):
                    continue

                orig_el = item.select_one("span[data-price-type='oldPrice'] span.price")
                price_orig_pen = _parse_price_str(orig_el.get_text() if orig_el else "")

                discount_pct = None
                if price_pen and price_orig_pen and price_orig_pen > price_pen:
                    discount_pct = round((1 - price_pen / price_orig_pen) * 100, 1)

                # [SC28]
                sku = (
                    item.get("data-product-id")
                    or _extract_sku_from_url(url_full)
                )

                records.append({
                    "batch_id":       batch_id,
                    "source":         self.SOURCE,
                    "category":       category,
                    "sku":            str(sku) if sku else None,
                    "title":          title,
                    "price_pen":      price_pen,
                    "price_orig_pen": price_orig_pen,
                    "discount_pct":   discount_pct,
                    "url":            url_full,
                    "brand":          None,
                    "available":      True,
                    "rating":         None,
                    "timestamp":      datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                log.debug(f"[Compumundo] item parse error: {e}")
        return records

    def scrape(self, category: str, queries: List[str], batch_id: str) -> List[Dict]:
        if not COMPUMUNDO_ENABLED:
            return []
        records: List[Dict] = []
        cat_path = self.CATEGORY_PATHS.get(category)
        if cat_path:
            for page in range(1, MAX_PAGES + 1):
                url = f"{self.BASE_URL}{cat_path}?p={page}"
                soup = self._fetch_page(url)
                if not soup:
                    break
                page_recs = self._parse_products(soup, category, batch_id)
                if not page_recs:
                    break
                records.extend(page_recs)
                time.sleep(DELAY_REQ)
        log.info(f"  [Compumundo] {category}: {len(records)} registros raw")
        return records


# ══════════════════════════════════════════════════════════════════════════
# FUNCIÓN PÚBLICA PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════
def scrape_competencia(
    batch_id: str,
    mode: str = "normal",
    sources: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Punto de entrada principal del scraper de competencia.

    Args:
        batch_id:   ID único del batch actual (ej. "20260716_214633").
        mode:       Modo de ejecución — "normal" (integrado con main.py).
        sources:    Lista de fuentes a usar. Default: ["falabella", "hiraoka", "coolbox"].
        categories: Lista de categorías. Default: todas las de CATEGORY_QUERIES_PE.

    Returns:
        Lista de dicts con los campos de COMP_FIELDS_PUBLIC.
    """
    t0 = time.time()
    if sources is None:
        sources = ["falabella", "hiraoka", "coolbox"]
    if categories is None:
        categories = list(CATEGORY_QUERIES_PE.keys())

    log.info("══════════════════════════════════════════════════")
    log.info("  SCRAPING COMPETENCIA PE  v4.2")
    log.info(f"  Fuentes: {sources} | Categorías: {categories}")
    log.info("══════════════════════════════════════════════════")

    # Inicializar scrapers solicitados
    scrapers: Dict[str, Any] = {}
    if "falabella" in sources:
        scrapers["falabella"] = FalabellaScraper()
    if "hiraoka" in sources:
        scrapers["hiraoka"] = HiraokaScraper()
    if "coolbox" in sources:
        scrapers["coolbox"] = CoolboxScraper()
    if "compumundo" in sources and COMPUMUNDO_ENABLED:
        scrapers["compumundo"] = CompumundoScraper()

    all_records: List[Dict] = []

    try:
        for category in categories:
            queries = CATEGORY_QUERIES_PE.get(category, [])
            if not queries:
                continue
            log.info(f"\n[CATEGORÍA] {category} — {len(queries)} queries disponibles")

            for name, scraper in scrapers.items():
                try:
                    recs = scraper.scrape(category, queries, batch_id)
                    all_records.extend(recs)
                except Exception as e:
                    log.warning(f"  [{name}] Error en {category}: {e}")
                time.sleep(DELAY_CAT)

    finally:
        for scraper in scrapers.values():
            try:
                scraper.close()
            except Exception:
                pass

    # Deduplicación global [SC30]
    before = len(all_records)
    all_records = _dedup(all_records)
    after = len(all_records)
    if before > after:
        log.info(f"[Competencia] Deduplicados: {before - after} eliminados")

    # Filtrar a campos públicos [SC29]
    output: List[Dict] = []
    for rec in all_records:
        filtered = {k: rec.get(k) for k in COMP_FIELDS_PUBLIC}
        output.append(filtered)

    elapsed = round((time.time() - t0) / 60, 1)
    log.info(f"[Competencia] TOTAL: {len(output)} registros únicos — ⏱ {elapsed} min")
    return output


# ══════════════════════════════════════════════════════════════════════════
# EJECUCIÓN STANDALONE
# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results  = scrape_competencia(batch_id=batch_id)
    print(f"\nTotal: {len(results)} registros")
    if results:
        import pprint
        print("\nEjemplo (primer registro):")
        pprint.pprint(results[0])
