#!/usr/bin/env python3
"""
scraper_competencia.py  v4.3
════════════════════════════════════════════════════════════════════
Scraper de precios de competencia — Mercado peruano (precio techo)

Fuentes:
  - Falabella PE   → SSR __NEXT_DATA__ (/falabella-pe/search?Ntt=...)
  - Hiraoka PE     → HTML /computo-y-tablets/... + fallback gpsearch
  - Coolbox PE     → HTML scraping (hardware/gaming especializado)
  - Compumundo PE  → Magento 2 HTML (deshabilitado por defecto — SSL mismatch)
  - Ripley PE      → PENDIENTE (requiere Playwright — 403 Cloudflare)

Fixes v4.3 (sobre v4.2):
  [SC32] FalabellaScraper: migrado de API /s/browse/v2/ (404 desde 13-jul-2026)
         a extracción SSR via __NEXT_DATA__ de /falabella-pe/search?Ntt=...
         La API v2 exigía categoryId obligatorio y luego pasó a 404 completo.
         El SSR devuelve 48 productos/página con precios y paginación estables.
  [SC33] FalabellaScraper._parse_ssr_product(): extrae precio desde lista
         prices[] con tipos eventPrice/normalPrice/cmrPrice (estructura real
         confirmada en julio 2026). Reemplaza _parse_api_product() que leía
         prices.offerPrice (campo inexistente en la respuesta real).
  [SC34] HiraokaScraper: CATEGORY_PATHS reemplazados por URLs reales
         confirmadas en julio 2026. Las rutas /componentes/* no existen;
         el hardware de componentes no está disponible en Hiraoka PE.
         Categorías disponibles: SSD/HDD via /accesorios-computo/disco-duro.
         Resto de categorías usa fallback gpsearch con filtro de relevancia.
  [SC35] HiraokaScraper: fallback cambiado de /catalogsearch/result/ (404)
         a /gpsearch/?q= (200 confirmado). Agrega filtro _is_hw_relevant()
         para descartar falsos positivos (ej. "KitchenAid" en query "procesador").
  [SC36] Logging: todas las excepciones silenciosas (except: return []) elevadas
         a log.error() con traceback.format_exc() completo. Visible en
         artefactos de GitHub Actions.
  [SC37] scrape_competencia(): si all_records vacío al final, emite log.error
         con resumen de fuentes intentadas — elimina fallo silencioso de v4.2.
"""

import os
import re
import time
import json
import hashlib
import logging
import traceback
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

# Productos por página — valor real confirmado en Falabella SSR (julio 2026)
_FALABELLA_PER_PAGE = 48

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
    "sku",
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
# KEYWORDS DE RELEVANCIA POR CATEGORÍA — [SC35]
# Usados por _is_hw_relevant() para filtrar falsos positivos en gpsearch
# ══════════════════════════════════════════════════════════════════════════
_HW_KEYWORDS: Dict[str, List[str]] = {
    "CPU":         ["procesador", "intel", "amd", "ryzen", "core i", "lga", "am4", "am5"],
    "GPU":         ["tarjeta", "video", "nvidia", "geforce", "rtx", "gtx", "radeon", "rx ", "gpu"],
    "RAM":         ["memoria", "ram", "ddr4", "ddr5", "dimm", "sodimm", "gb"],
    "SSD":         ["ssd", "nvme", "m.2", "solido", "disco", "pcie", "sata"],
    "MOTHERBOARD": ["placa", "madre", "motherboard", "z790", "b650", "b550", "x570", "socket"],
    "PSU":         ["fuente", "poder", "psu", "watt", "80 plus", "gold", "modular"],
    "COOLER":      ["cooler", "disipador", "refrigeracion", "aio", "ventilador", "cpu"],
    "CASE":        ["case", "gabinete", "torre", "atx", "micro atx", "chasis"],
}


# ══════════════════════════════════════════════════════════════════════════
# UTILIDADES COMPARTIDAS
# ══════════════════════════════════════════════════════════════════════════

def _get_ua() -> str:
    return _ua_gen.random if _ua_gen else _UA_FALLBACK


def _make_session(verify_ssl: bool = True) -> requests.Session:
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
    return price is not None and PRICE_MIN_PEN <= price <= PRICE_MAX_PEN


def _extract_sku_from_url(url: str) -> Optional[str]:
    """[SC26] Extrae SKU estable desde URL."""
    if not url:
        return None
    m = re.search(r"/p/(\d{6,})", url)
    if m:
        return m.group(1)
    m = re.search(r"/([^/]+)\.html", url)
    if m:
        slug = m.group(1)
        return slug[:64] if slug else None
    path = url.rstrip("/").split("/")[-1].split("?")[0]
    return path[:64] if path else None


def _make_fingerprint(source: str, identity: str) -> str:
    raw = f"{source}|{identity}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _dedup(records: List[Dict]) -> List[Dict]:
    """[SC30] Deduplicación intra-batch. Clave: sku > url > title."""
    seen: set = set()
    out:  List[Dict] = []
    for r in records:
        source   = r.get("source", "")
        sku      = str(r.get("sku")   or "").strip()
        url      = str(r.get("url")   or "").strip()
        title    = str(r.get("title") or "").strip()
        identity = sku or url or title
        if not identity:
            out.append(r)
            continue
        fp = _make_fingerprint(source, identity)
        if fp not in seen:
            seen.add(fp)
            out.append(r)
    return out


def _is_hw_relevant(title: str, category: str) -> bool:
    """
    [SC35] Verifica que el título del producto sea hardware relevante
    para la categoría dada. Descarta falsos positivos de gpsearch
    (ej. "Procesadora de Alimentos KitchenAid" en query CPU).
    """
    keywords = _HW_KEYWORDS.get(category, [])
    if not keywords:
        return True
    title_lower = title.lower()
    return any(kw in title_lower for kw in keywords)


# ══════════════════════════════════════════════════════════════════════════
# FALABELLA SCRAPER  [SC32] [SC33]
# ══════════════════════════════════════════════════════════════════════════
class FalabellaScraper:
    """
    Falabella PE — SSR via __NEXT_DATA__ de /falabella-pe/search?Ntt=...

    [SC32] La API /s/browse/v2/listing/pe está caída desde el 13-jul-2026:
      - Primero exigió categoryId obligatorio (400 FST_ERR_VALIDATION).
      - Luego pasó a 404 completo en todos los endpoints /s/browse/v2/*.
    La página de búsqueda HTML devuelve __NEXT_DATA__ con pageProps.results[]
    que contiene los mismos datos (48 productos/página, precio, SKU, marca).

    [SC33] Estructura de precios confirmada (julio 2026):
      prices = [
        {"type": "eventPrice",  "crossed": False, "price": ["799.90"]},  ← oferta
        {"type": "normalPrice", "crossed": True,  "price": ["999.90"]},  ← tachado
        {"type": "cmrPrice",    "crossed": False, "price": ["759.90"]},  ← CMR
      ]
    Se toma el precio no-tachado más bajo como price_pen,
    y el normalPrice tachado como price_orig_pen.
    """
    BASE_URL  = "https://www.falabella.com.pe"
    SEARCH_URL = "https://www.falabella.com.pe/falabella-pe/search"
    SOURCE    = "falabella_pe"

    def __init__(self):
        self.session = _make_session()

    def close(self):
        self.session.close()

    # ── [SC33] Extracción de precios desde lista prices[] ──────────────
    @staticmethod
    def _extract_prices(prices: list) -> tuple:
        """
        Retorna (price_pen, price_orig_pen) desde la lista prices[] del SSR.
        price_pen      = precio vigente más bajo (no tachado)
        price_orig_pen = precio normal tachado (referencia de descuento)
        """
        offer_price  = None
        normal_price = None

        for entry in prices:
            ptype   = entry.get("type", "")
            crossed = entry.get("crossed", False)
            raw     = entry.get("price", [])
            try:
                value = float(str(raw[0]).replace(",", "")) if raw else None
            except (ValueError, IndexError):
                value = None
            if value is None or value <= 0:
                continue

            if ptype == "normalPrice" and crossed:
                # Precio de referencia tachado
                normal_price = value
            elif not crossed:
                # Cualquier precio vigente (eventPrice, cmrPrice, etc.)
                if offer_price is None or value < offer_price:
                    offer_price = value

        # Fallback: si no hay precio vigente, usar el primer valor disponible
        if offer_price is None:
            for entry in prices:
                raw = entry.get("price", [])
                try:
                    v = float(str(raw[0]).replace(",", ""))
                    if v > 0:
                        offer_price = v
                        break
                except (ValueError, IndexError):
                    pass

        return offer_price, normal_price

    # ── [SC32] Fetch de página SSR ──────────────────────────────────────
    def _fetch_ssr_page(self, query: str, page: int) -> tuple:
        """
        Descarga la página HTML de búsqueda y extrae pageProps via __NEXT_DATA__.
        Retorna (results: list, pagination: dict).
        """
        offset = (page - 1) * _FALABELLA_PER_PAGE
        url = (
            f"{self.SEARCH_URL}"
            f"?Ntt={requests.utils.quote(query)}"
            f"&No={offset}"
            f"&Nrpp={_FALABELLA_PER_PAGE}"
        )
        try:
            r = self.session.get(
                url,
                headers=_headers_html(referer=self.BASE_URL),
                timeout=25,
            )
            if r.status_code != 200:
                log.error(
                    "[Falabella] HTTP %d en query='%s' page=%d\n%s",
                    r.status_code, query, page, traceback.format_exc()
                )
                return [], {}

            nd_match = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                r.text, re.DOTALL
            )
            if not nd_match:
                log.error(
                    "[Falabella] __NEXT_DATA__ no encontrado — query='%s' page=%d. "
                    "Posible cambio en el HTML de Falabella.",
                    query, page
                )
                return [], {}

            nd_json    = json.loads(nd_match.group(1))
            page_props = nd_json.get("props", {}).get("pageProps", {})
            results    = page_props.get("results", [])
            pagination = page_props.get("pagination", {})
            return results, pagination

        except json.JSONDecodeError:
            log.error(
                "[Falabella] JSON inválido en __NEXT_DATA__ — query='%s' page=%d:\n%s",
                query, page, traceback.format_exc()
            )
            return [], {}
        except Exception:
            log.error(
                "[Falabella] Error inesperado — query='%s' page=%d:\n%s",
                query, page, traceback.format_exc()
            )
            return [], {}

    # ── [SC33] Parser de producto SSR ───────────────────────────────────
    def _parse_ssr_product(self, item: Dict, category: str, batch_id: str) -> Optional[Dict]:
        """Convierte un item de pageProps.results[] al schema público."""
        try:
            pid   = str(item.get("productId") or item.get("skuId") or "").strip()
            title = (item.get("displayName") or item.get("name") or "").strip()
            if not title:
                return None

            price_pen, price_orig_pen = self._extract_prices(item.get("prices", []))

            if not _valid_price(price_pen):
                return None

            discount_pct = None
            if price_pen and price_orig_pen and price_orig_pen > price_pen:
                discount_pct = round((1 - price_pen / price_orig_pen) * 100, 1)

            url_raw  = item.get("url") or item.get("pdpUrl") or ""
            url_full = (
                url_raw if url_raw.startswith("http")
                else f"{self.BASE_URL}{url_raw}"
            )

            # SKU: pid > extraído de URL [SC26]
            sku = pid if pid else _extract_sku_from_url(url_full)

            return {
                "batch_id":       batch_id,
                "source":         self.SOURCE,
                "category":       category,
                "sku":            sku or None,
                "title":          title,
                "price_pen":      price_pen,
                "price_orig_pen": price_orig_pen,
                "discount_pct":   discount_pct,
                "url":            url_full,
                "brand":          (item.get("brand") or "").strip() or None,
                "available":      True,
                "rating":         item.get("rating") or item.get("stars") or None,
                "timestamp":      datetime.now(timezone.utc).isoformat(),
            }
        except Exception:
            log.warning(
                "[Falabella] Error parseando producto '%s':\n%s",
                item.get("displayName", "?"), traceback.format_exc()
            )
            return None

    # ── Scrape principal ─────────────────────────────────────────────────
    def scrape(self, category: str, queries: List[str], batch_id: str) -> List[Dict]:
        records:  List[Dict] = []
        seen_ids: set        = set()

        for query in queries[:MAX_QUERIES_COMP]:
            log.info("  [Falabella] %s | '%s'", category, query)

            for page in range(1, MAX_PAGES + 1):
                raw, pagination = self._fetch_ssr_page(query, page)

                if not raw:
                    log.debug("    [Falabella] p%d vacío — stop", page)
                    break

                new_in_page = 0
                for item in raw:
                    rec = self._parse_ssr_product(item, category, batch_id)
                    if not rec:
                        continue
                    # [SC31] IDs vacíos no entran al set
                    pid = str(item.get("productId") or item.get("skuId") or "").strip()
                    if pid:
                        if pid in seen_ids:
                            continue
                        seen_ids.add(pid)
                    records.append(rec)
                    new_in_page += 1

                total_count = pagination.get("count", 0)
                log.debug(
                    "    [Falabella] p%d: +%d (total disponible: %d)",
                    page, new_in_page, total_count
                )

                # Última página si hay menos resultados que el máximo por página
                if len(raw) < _FALABELLA_PER_PAGE:
                    break

                time.sleep(DELAY_REQ)

            time.sleep(DELAY_CAT)

        log.info("  [Falabella] %s: %d registros raw", category, len(records))
        return records


# ══════════════════════════════════════════════════════════════════════════
# HIRAOKA SCRAPER  [SC34] [SC35]
# ══════════════════════════════════════════════════════════════════════════
class HiraokaScraper:
    """
    Hiraoka PE — HTML scraping.

    [SC34] URLs de categorías actualizadas (julio 2026):
      - Hiraoka NO vende componentes de PC (CPU/GPU/RAM/Motherboard/PSU/Cooler/Case).
      - Solo tiene SSD/HDD bajo /computo-y-tablets/accesorios-computo/disco-duro.
      - Para el resto de categorías se usa gpsearch con filtro de relevancia.

    [SC35] Fallback: /gpsearch/?q= (200 confirmado) en lugar de
      /catalogsearch/result/ (404). Se aplica _is_hw_relevant() para
      descartar falsos positivos (ej. "Procesadora de Alimentos").
    """
    BASE_URL = "https://hiraoka.com.pe"
    SOURCE   = "hiraoka_pe"

    # [SC34] Solo rutas confirmadas como existentes en julio 2026
    CATEGORY_PATHS: Dict[str, Optional[str]] = {
        "CPU":         None,   # No existe en Hiraoka — usar gpsearch
        "GPU":         None,   # No existe en Hiraoka — usar gpsearch
        "RAM":         None,   # No existe en Hiraoka — usar gpsearch
        "SSD":         "/computo-y-tablets/accesorios-computo/disco-duro",
        "MOTHERBOARD": None,   # No existe en Hiraoka — usar gpsearch
        "PSU":         None,   # No existe en Hiraoka — usar gpsearch
        "COOLER":      None,   # No existe en Hiraoka — usar gpsearch
        "CASE":        None,   # No existe en Hiraoka — usar gpsearch
    }

    def __init__(self):
        self.session = _make_session()

    def close(self):
        self.session.close()

    def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        try:
            r = self.session.get(
                url,
                headers=_headers_html(self.BASE_URL),
                timeout=20,
                allow_redirects=True,
            )
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            log.debug("[Hiraoka] HTTP %d: %s", r.status_code, url)
            return None
        except Exception:
            log.error("[Hiraoka] fetch error: %s\n%s", url, traceback.format_exc())
            return None

    def _parse_products(
        self, soup: BeautifulSoup, category: str, batch_id: str,
        filter_relevance: bool = False
    ) -> List[Dict]:
        """
        Parsea .product-item de Magento 2.
        filter_relevance=True activa _is_hw_relevant() (para gpsearch).
        """
        records = []
        items = soup.select("li.product-item, div.product-item-info")

        for item in items:
            try:
                title_el = item.select_one(
                    "a.product-item-link, strong.product-item-name a"
                )
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)

                # [SC35] Filtro de relevancia para gpsearch
                if filter_relevance and not _is_hw_relevant(title, category):
                    log.debug("[Hiraoka] Descartado por relevancia: '%s'", title)
                    continue

                url_raw  = title_el.get("href", "")
                url_full = (
                    url_raw if url_raw.startswith("http")
                    else f"{self.BASE_URL}{url_raw}"
                )

                # Precio Magento 2: finalPrice > precio visible
                price_el = item.select_one(
                    "span[data-price-type='finalPrice'] span.price, "
                    ".special-price span.price, "
                    "span.price"
                )
                price_pen = _parse_price_str(price_el.get_text() if price_el else "")
                if not _valid_price(price_pen):
                    continue

                orig_el = item.select_one(
                    "span[data-price-type='oldPrice'] span.price, "
                    ".old-price span.price"
                )
                price_orig_pen = _parse_price_str(orig_el.get_text() if orig_el else "")

                discount_pct = None
                if price_pen and price_orig_pen and price_orig_pen > price_pen:
                    discount_pct = round((1 - price_pen / price_orig_pen) * 100, 1)

                # [SC28] SKU desde data-product-id
                sku_el = item.select_one("[data-product-id]")
                sku = (
                    item.get("data-product-id")
                    or (sku_el.get("data-product-id") if sku_el else None)
                    or _extract_sku_from_url(url_full)
                )

                stock_el  = item.select_one(".stock, .availability")
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
            except Exception:
                log.warning("[Hiraoka] item parse error:\n%s", traceback.format_exc())

        return records

    def scrape(self, category: str, queries: List[str], batch_id: str) -> List[Dict]:
        records:  List[Dict] = []
        cat_path = self.CATEGORY_PATHS.get(category)

        # ── Estrategia 1: categoría directa (solo si existe) ─────────────
        if cat_path:
            log.info("  [Hiraoka] %s | categoría directa: %s", category, cat_path)
            for page in range(1, MAX_PAGES + 1):
                url  = f"{self.BASE_URL}{cat_path}?p={page}"
                soup = self._fetch_page(url)
                if not soup:
                    log.error(
                        "[Hiraoka] Sin respuesta en categoría directa p%d: %s\n%s",
                        page, url, traceback.format_exc()
                    )
                    break
                page_recs = self._parse_products(soup, category, batch_id)
                if not page_recs:
                    break
                records.extend(page_recs)
                log.debug("  [Hiraoka] %s p%d: +%d", category, page, len(page_recs))
                time.sleep(DELAY_REQ)

        # ── Estrategia 2: gpsearch con filtro de relevancia [SC35] ───────
        if not records:
            log.info(
                "  [Hiraoka] %s | sin categoría directa — usando gpsearch",
                category
            )
            for query in queries[:MAX_QUERIES_COMP]:
                url  = f"{self.BASE_URL}/gpsearch/?q={requests.utils.quote(query)}"
                soup = self._fetch_page(url)
                if not soup:
                    log.error(
                        "[Hiraoka] gpsearch sin respuesta: query='%s'\n%s",
                        query, traceback.format_exc()
                    )
                    continue
                page_recs = self._parse_products(
                    soup, category, batch_id, filter_relevance=True
                )
                records.extend(page_recs)
                log.debug(
                    "  [Hiraoka] gpsearch '%s': +%d relevantes",
                    query, len(page_recs)
                )
                time.sleep(DELAY_REQ)

        log.info("  [Hiraoka] %s: %d registros raw", category, len(records))
        return records


# ══════════════════════════════════════════════════════════════════════════
# COOLBOX SCRAPER  (sin cambios funcionales vs v4.2)
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
            log.debug("[Coolbox] HTTP %d: %s", r.status_code, url)
            return None
        except Exception:
            log.error("[Coolbox] fetch error: %s\n%s", url, traceback.format_exc())
            return None

    def _parse_products(self, soup: BeautifulSoup, category: str, batch_id: str) -> List[Dict]:
        records = []
        items = soup.select("div.product-item, article.product-item, li.product-item")
        for item in items:
            try:
                title_el = item.select_one(
                    "h2.product-name a, h3.product-name a, a.product-item-link"
                )
                if not title_el:
                    continue
                title    = title_el.get_text(strip=True)
                url_raw  = title_el.get("href", "")
                url_full = (
                    url_raw if url_raw.startswith("http")
                    else f"{self.BASE_URL}{url_raw}"
                )

                price_el  = item.select_one(".price, .product-price, span.price")
                price_pen = _parse_price_str(price_el.get_text() if price_el else "")
                if not _valid_price(price_pen):
                    continue

                orig_el        = item.select_one(".old-price .price, .price-old, del.price")
                price_orig_pen = _parse_price_str(orig_el.get_text() if orig_el else "")

                discount_pct = None
                if price_pen and price_orig_pen and price_orig_pen > price_pen:
                    discount_pct = round((1 - price_pen / price_orig_pen) * 100, 1)

                sku = item.get("data-product-id") or _extract_sku_from_url(url_full)

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
            except Exception:
                log.warning("[Coolbox] item parse error:\n%s", traceback.format_exc())
        return records

    def scrape(self, category: str, queries: List[str], batch_id: str) -> List[Dict]:
        records:  List[Dict] = []
        cat_path = self.CATEGORY_PATHS.get(category)

        if cat_path:
            for page in range(1, MAX_PAGES + 1):
                url  = f"{self.BASE_URL}{cat_path}?page={page}"
                soup = self._fetch_page(url)
                if not soup:
                    break
                page_recs = self._parse_products(soup, category, batch_id)
                if not page_recs:
                    break
                records.extend(page_recs)
                log.debug("  [Coolbox] %s p%d: +%d", category, page, len(page_recs))
                time.sleep(DELAY_REQ)

        log.info("  [Coolbox] %s: %d registros raw", category, len(records))
        return records


# ══════════════════════════════════════════════════════════════════════════
# COMPUMUNDO SCRAPER (deshabilitado por defecto — SSL mismatch)
# ══════════════════════════════════════════════════════════════════════════
class CompumundoScraper:
    """
    Compumundo PE — Magento 2 HTML.
    Deshabilitado por defecto (COMPUMUNDO_ENABLED=false).
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
        except Exception:
            log.error("[Compumundo] fetch error: %s\n%s", url, traceback.format_exc())
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
                url_raw  = title_el.get("href", "")
                url_full = (
                    url_raw if url_raw.startswith("http")
                    else f"{self.BASE_URL}{url_raw}"
                )
                price_el  = item.select_one("span[data-price-type='finalPrice'] span.price")
                price_pen = _parse_price_str(price_el.get_text() if price_el else "")
                if not _valid_price(price_pen):
                    continue
                orig_el        = item.select_one("span[data-price-type='oldPrice'] span.price")
                price_orig_pen = _parse_price_str(orig_el.get_text() if orig_el else "")
                discount_pct   = None
                if price_pen and price_orig_pen and price_orig_pen > price_pen:
                    discount_pct = round((1 - price_pen / price_orig_pen) * 100, 1)
                sku = item.get("data-product-id") or _extract_sku_from_url(url_full)
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
            except Exception:
                log.warning("[Compumundo] item parse error:\n%s", traceback.format_exc())
        return records

    def scrape(self, category: str, queries: List[str], batch_id: str) -> List[Dict]:
        if not COMPUMUNDO_ENABLED:
            return []
        records:  List[Dict] = []
        cat_path = self.CATEGORY_PATHS.get(category)
        if cat_path:
            for page in range(1, MAX_PAGES + 1):
                url  = f"{self.BASE_URL}{cat_path}?p={page}"
                soup = self._fetch_page(url)
                if not soup:
                    break
                page_recs = self._parse_products(soup, category, batch_id)
                if not page_recs:
                    break
                records.extend(page_recs)
                time.sleep(DELAY_REQ)
        log.info("  [Compumundo] %s: %d registros raw", category, len(records))
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
        sources:    Lista de fuentes. Default: ["falabella", "hiraoka", "coolbox"].
        categories: Lista de categorías. Default: todas las de CATEGORY_QUERIES_PE.

    Returns:
        Lista de dicts con los campos de COMP_FIELDS_PUBLIC.
        [SC37] Nunca retorna vacío silenciosamente — emite log.error si ocurre.
    """
    t0 = time.time()
    if sources is None:
        sources = ["falabella", "hiraoka", "coolbox"]
    if categories is None:
        categories = list(CATEGORY_QUERIES_PE.keys())

    log.info("══════════════════════════════════════════════════")
    log.info("  SCRAPING COMPETENCIA PE  v4.3")
    log.info("  Fuentes    : %s", sources)
    log.info("  Categorías : %s", categories)
    log.info("══════════════════════════════════════════════════")

    scrapers: Dict[str, Any] = {}
    if "falabella"  in sources: scrapers["falabella"]  = FalabellaScraper()
    if "hiraoka"    in sources: scrapers["hiraoka"]    = HiraokaScraper()
    if "coolbox"    in sources: scrapers["coolbox"]    = CoolboxScraper()
    if "compumundo" in sources and COMPUMUNDO_ENABLED:
        scrapers["compumundo"] = CompumundoScraper()

    all_records:    List[Dict]      = []
    source_counts:  Dict[str, int]  = {name: 0 for name in scrapers}
    source_errors:  Dict[str, bool] = {name: False for name in scrapers}

    try:
        for category in categories:
            queries = CATEGORY_QUERIES_PE.get(category, [])
            if not queries:
                continue
            log.info("\n[CATEGORÍA] %s — %d queries disponibles", category, len(queries))

            for name, scraper in scrapers.items():
                try:
                    recs = scraper.scrape(category, queries, batch_id)
                    all_records.extend(recs)
                    source_counts[name] += len(recs)
                except Exception:
                    # [SC36] Error visible — no silencioso
                    log.error(
                        "  [%s] FALLO COMPLETO en categoría '%s':\n%s",
                        name, category, traceback.format_exc()
                    )
                    source_errors[name] = True
                time.sleep(DELAY_CAT)

    finally:
        for scraper in scrapers.values():
            try:
                scraper.close()
            except Exception:
                pass

    # ── Deduplicación global [SC30] ──────────────────────────────────────
    before      = len(all_records)
    all_records = _dedup(all_records)
    after       = len(all_records)
    if before > after:
        log.info("[Competencia] Deduplicados: %d eliminados", before - after)

    # ── Filtrar a campos públicos [SC29] ─────────────────────────────────
    output: List[Dict] = [
        {k: rec.get(k) for k in COMP_FIELDS_PUBLIC}
        for rec in all_records
    ]

    elapsed = round((time.time() - t0) / 60, 1)

    # ── [SC37] Validación final — error explícito si vacío ───────────────
    if not output:
        log.error(
            "[Competencia] RESULTADO VACÍO después de %.1f min. "
            "Resumen por fuente: %s | Errores: %s",
            elapsed,
            {k: v for k, v in source_counts.items()},
            {k: v for k, v in source_errors.items() if v},
        )
    else:
        log.info(
            "[Competencia] TOTAL: %d registros únicos — ⏱ %.1f min",
            len(output), elapsed
        )
        log.info(
            "[Competencia] Por fuente: %s",
            {k: v for k, v in source_counts.items() if v > 0}
        )

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
        from collections import Counter
        print(f"\nPor fuente   : {dict(Counter(r['source']   for r in results))}")
        print(f"Por categoría: {dict(Counter(r['category'] for r in results))}")
        print("\nEjemplo (primer registro):")
        pprint.pprint(results[0])
