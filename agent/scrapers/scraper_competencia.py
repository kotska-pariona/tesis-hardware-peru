#!/usr/bin/env python3
"""
scraper_competencia.py  v4.4
════════════════════════════════════════════════════════════════════
Scraper de precios de competencia — Mercado peruano (precio techo)

Fuentes:
  - Falabella PE   → __NEXT_DATA__ SSR (HTML) con paginación corregida
  - Hiraoka PE     → Magento 2 HTML (categoría directa + fallback gpsearch)
  - Coolbox PE     → VTEX GraphQL (vtex.search-graphql) — migrado desde HTML
  - Compumundo PE  → Magento 2 HTML (deshabilitado por defecto — SSL mismatch)
  - Ripley PE      → PENDIENTE (requiere Playwright — 403 Cloudflare)

Fixes v4.4 (sobre v4.3):
  [SC36] CoolboxScraper: migrado completamente a VTEX GraphQL
         (/_v/segment/graphql/v1 + productSearch + selectedFacets[category-3]).
         Elimina dependencia de selectores CSS inestables.
  [SC37] CoolboxScraper: mapeo de slugs de categoría VTEX validados
         (procesadores, tarjetas-de-video, memorias-ram, etc.).
  [SC38] CoolboxScraper: extrae productId, sku, price, listPrice y
         disponibilidad directamente desde el catálogo VTEX.
  [SC39] FalabellaScraper: paginación corregida — usa totalPages desde
         pagination dict en lugar de count//48 (evitaba corte prematuro
         cuando count=0 pero había resultados).
  [SC40] FalabellaScraper: fallback de paginación robusto con múltiples
         claves (totalPages, total_pages, pages, count).
  [SC41] _parse_price_str: separador de miles peruano corregido —
         "1,299" ya no se interpreta como "1.299".
  [SC42] CoolboxScraper: request extra eliminada al final de cada
         categoría — se verifica hasNextPage desde la respuesta GraphQL
         antes de continuar paginación.
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
        allowed_methods=["GET", "POST"],
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
    [SC41] Limpia strings de precio peruanos.
    Lógica corregida para separadores de miles peruanos:
      "S/. 1,299.00" → 1299.0
      "1,299"        → 1299.0  (miles, NO decimal)
      "1.299,00"     → 1299.0  (formato europeo)
      "299.90"       → 299.9
    Regla: si hay coma Y punto → el último separador es el decimal.
    Si solo hay coma → es miles si la parte tras la coma tiene 3 dígitos,
    decimal si tiene 1-2 dígitos.
    """
    if not text:
        return None
    clean = re.sub(r"[^\d,.]", "", str(text).strip())
    if not clean:
        return None
    try:
        if "," in clean and "." in clean:
            # El separador que aparece último es el decimal
            if clean.rfind(",") > clean.rfind("."):
                # Formato europeo: 1.299,00
                clean = clean.replace(".", "").replace(",", ".")
            else:
                # Formato anglosajón: 1,299.00
                clean = clean.replace(",", "")
        elif "," in clean:
            parts = clean.split(",")
            # [SC41] 3 dígitos tras la coma → separador de miles (1,299 → 1299)
            # 1-2 dígitos tras la coma → separador decimal (1,29 → 1.29)
            if len(parts) == 2 and len(parts[-1]) == 3:
                clean = clean.replace(",", "")
            else:
                clean = clean.replace(",", ".")
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
    Falabella PE — __NEXT_DATA__ SSR con paginación corregida [SC39/SC40].
    Zona: Lima Metropolitana (zones=150101).
    """
    BASE_URL = "https://www.falabella.com.pe"
    SOURCE   = "falabella_pe"

    def __init__(self):
        self.session = _make_session()

    def close(self):
        self.session.close()

    def _fetch_ssr(self, query: str, page: int) -> tuple:
        """
        [SC32] Extrae productos desde __NEXT_DATA__ SSR.
        URL: /falabella-pe/search?Ntt=<query>&No=<offset>&Nrpp=48
        Retorna (results_list, pagination_dict).
        """
        offset = (page - 1) * 48
        url = (
            f"{self.BASE_URL}/falabella-pe/search"
            f"?Ntt={requests.utils.quote(query)}"
            f"&No={offset}&Nrpp=48"
        )
        try:
            r = self.session.get(url, headers=_headers_html(self.BASE_URL), timeout=25)
            if r.status_code != 200:
                log.error(f"[Falabella] HTTP {r.status_code} en query='{query}' p{page}")
                return [], {}
            nd = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                r.text, re.DOTALL
            )
            if not nd:
                log.error(f"[Falabella] __NEXT_DATA__ no encontrado query='{query}' p{page}")
                return [], {}
            pp = json.loads(nd.group(1))["props"]["pageProps"]
            return pp.get("results", []), pp.get("pagination", {})
        except Exception:
            import traceback
            log.error(f"[Falabella] _fetch_ssr error query='{query}' p{page}:\n{traceback.format_exc()}")
            return [], {}

    def _resolve_total_pages(self, pagination: dict, page_size: int = 48) -> int:
        """
        [SC39/SC40] Resuelve total de páginas desde múltiples claves posibles
        del dict pagination para evitar corte prematuro.
        Claves intentadas en orden: totalPages → total_pages → pages →
        derivado de count → derivado de total → fallback 1.
        """
        # Clave directa de páginas
        for key in ("totalPages", "total_pages", "pages", "pageCount", "page_count"):
            val = pagination.get(key)
            if val and int(val) > 0:
                return int(val)
        # Derivado de conteo de productos
        for key in ("count", "total", "totalCount", "total_count", "totalResults"):
            val = pagination.get(key)
            if val and int(val) > 0:
                return max(1, (int(val) + page_size - 1) // page_size)
        return 1

    def _parse_ssr_product(self, item: Dict, category: str, batch_id: str) -> Optional[Dict]:
        """
        [SC33] Convierte un item de __NEXT_DATA__ pageProps.results al schema público.
        Estructura de precios confirmada:
          prices[]: [{type: eventPrice, crossed: false, price: ["799.90"]},
                     {type: normalPrice, crossed: true,  price: ["999.90"]}]
        """
        import traceback
        try:
            pid   = str(item.get("productId") or item.get("skuId") or "").strip()
            title = (item.get("displayName") or item.get("name") or "").strip()
            if not title:
                return None

            prices_list    = item.get("prices", []) or []
            price_pen      = None
            price_orig_pen = None

            for entry in prices_list:
                ptype   = entry.get("type", "")
                crossed = entry.get("crossed", False)
                raw     = entry.get("price", [])
                try:
                    val = float(str(raw[0]).replace(",", "")) if raw else None
                except (ValueError, IndexError):
                    val = None
                if val is None:
                    continue
                if ptype in ("eventPrice", "cmrPrice") and not crossed:
                    if price_pen is None or val < price_pen:
                        price_pen = val
                elif ptype == "normalPrice" and crossed:
                    price_orig_pen = val

            # Fallback: primer precio no tachado
            if price_pen is None:
                for entry in prices_list:
                    if not entry.get("crossed", False):
                        raw = entry.get("price", [])
                        try:
                            price_pen = float(str(raw[0]).replace(",", ""))
                            break
                        except (ValueError, IndexError):
                            pass

            if not _valid_price(price_pen):
                return None

            discount_pct = None
            if price_pen and price_orig_pen and price_orig_pen > price_pen:
                discount_pct = round((1 - price_pen / price_orig_pen) * 100, 1)

            brand    = (item.get("brand") or "").strip() or None
            url_path = item.get("url") or ""
            url_full = url_path if url_path.startswith("http") else f"{self.BASE_URL}{url_path}"
            sku      = pid if pid else _extract_sku_from_url(url_full)

            return {
                "batch_id":       batch_id,
                "source":         self.SOURCE,
                "category":       category,
                "sku":            sku,
                "title":          title,
                "price_pen":      price_pen,
                "price_orig_pen": price_orig_pen,
                "discount_pct":   discount_pct,
                "url":            url_full,
                "brand":          brand,
                "available":      True,
                "rating":         None,
                "timestamp":      datetime.now(timezone.utc).isoformat(),
            }
        except Exception:
            import traceback
            log.error(f"[Falabella] _parse_ssr_product error:\n{traceback.format_exc()}")
            return None

    def scrape(self, category: str, queries: List[str], batch_id: str) -> List[Dict]:
        """[SC32/SC39] Scrape vía SSR __NEXT_DATA__ con paginación corregida."""
        records:  List[Dict] = []
        seen_ids: set        = set()

        for query in queries[:MAX_QUERIES_COMP]:
            log.info(f"  [Falabella] {category} | '{query}'")
            for page in range(1, MAX_PAGES + 1):
                raw, pagination = self._fetch_ssr(query, page)
                if not raw:
                    log.debug(f"    p{page}: vacío — stop")
                    break

                new_in_page = 0
                for item in raw:
                    rec = self._parse_ssr_product(item, category, batch_id)
                    if not rec:
                        continue
                    pid = str(item.get("productId") or item.get("skuId") or "").strip()
                    if pid:
                        if pid in seen_ids:
                            continue
                        seen_ids.add(pid)
                    records.append(rec)
                    new_in_page += 1

                # [SC39] Paginación corregida
                total_pages = self._resolve_total_pages(pagination, page_size=48)
                log.debug(f"    p{page}/{total_pages}: +{new_in_page}")
                if new_in_page == 0 or page >= total_pages:
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
    Estrategia: categoría directa → fallback gpsearch.
    """
    BASE_URL = "https://www.hiraoka.com.pe"
    SOURCE   = "hiraoka_pe"

    # [SC34] URLs reales confirmadas julio 2026.
    # Hiraoka NO vende componentes (CPU/GPU/RAM/MB/PSU/COOLER/CASE).
    # Solo SSD/HDD tiene categoría real.
    CATEGORY_PATHS = {
        "CPU":         None,
        "GPU":         None,
        "RAM":         None,
        "SSD":         "/computo-y-tablets/accesorios-computo/disco-duro",
        "MOTHERBOARD": None,
        "PSU":         None,
        "COOLER":      None,
        "CASE":        None,
    }

    # [SC35] Palabras clave para filtrar falsos positivos del gpsearch
    HW_KEYWORDS = [
        "intel", "amd", "ryzen", "core i", "nvme", "ssd", "m.2",
        "ddr4", "ddr5", "rtx", "radeon", "gb", "tb", "pcie",
        "wd", "seagate", "kingston", "samsung", "crucial",
    ]

    def _is_hw_relevant(self, title: str) -> bool:
        """[SC35] True si el título contiene al menos 1 keyword de hardware."""
        tl = title.lower()
        return any(kw in tl for kw in self.HW_KEYWORDS)

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
        items = soup.select("li.product-item, div.product-item-info")
        for item in items:
            try:
                title_el = item.select_one("a.product-item-link, strong.product-item-name a")
                if not title_el:
                    continue
                title    = title_el.get_text(strip=True)
                url_rel  = title_el.get("href", "")
                url_full = url_rel if url_rel.startswith("http") else f"{self.BASE_URL}{url_rel}"

                price_el  = item.select_one("span[data-price-type='finalPrice'] span.price")
                price_pen = _parse_price_str(price_el.get_text() if price_el else "")
                if not _valid_price(price_pen):
                    continue

                orig_el        = item.select_one("span[data-price-type='oldPrice'] span.price")
                price_orig_pen = _parse_price_str(orig_el.get_text() if orig_el else "")

                discount_pct = None
                if price_pen and price_orig_pen and price_orig_pen > price_pen:
                    discount_pct = round((1 - price_pen / price_orig_pen) * 100, 1)

                # [SC28] SKU desde data-product-id
                dp_el = item.select_one("[data-product-id]")
                sku = (
                    item.get("data-product-id")
                    or (dp_el.get("data-product-id") if dp_el else None)
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
            except Exception as e:
                log.debug(f"[Hiraoka] item parse error: {e}")
        return records

    def scrape(self, category: str, queries: List[str], batch_id: str) -> List[Dict]:
        records:  List[Dict] = []
        cat_path = self.CATEGORY_PATHS.get(category)

        # Estrategia 1: categoría directa
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
                log.debug(f"  [Hiraoka] {category} p{page}: +{len(page_recs)}")
                time.sleep(DELAY_REQ)

        # [SC35] Estrategia 2: fallback gpsearch
        if not records:
            for query in queries[:MAX_QUERIES_COMP]:
                search_url = (
                    f"{self.BASE_URL}/gpsearch/result/index/"
                    f"?q={requests.utils.quote(query)}"
                )
                soup = self._fetch_page(search_url)
                if soup:
                    page_recs = self._parse_products(soup, category, batch_id)
                    page_recs = [r for r in page_recs if self._is_hw_relevant(r["title"])]
                    records.extend(page_recs)
                    log.debug(f"  [Hiraoka] gpsearch '{query}': {len(page_recs)} relevantes")
                time.sleep(DELAY_REQ)

        log.info(f"  [Hiraoka] {category}: {len(records)} registros raw")
        return records


# ══════════════════════════════════════════════════════════════════════════
# COOLBOX SCRAPER  [SC36/SC37/SC38/SC42]
# ══════════════════════════════════════════════════════════════════════════
class CoolboxScraper:
    """
    Coolbox PE — VTEX GraphQL (vtex.search-graphql).
    [SC36] Migrado desde HTML scraping a API GraphQL directa.
    Endpoint: https://www.coolbox.pe/_v/segment/graphql/v1
    Query:    productSearch con selectedFacets[{key: category-3, value: <slug>}]
    Paginación: from/to con hasNextPage [SC42].
    """
    BASE_URL    = "https://www.coolbox.pe"
    SOURCE      = "coolbox_pe"
    GQL_ENDPOINT = "https://www.coolbox.pe/_v/segment/graphql/v1"
    PAGE_SIZE   = 50

    # [SC37] Slugs de categoría VTEX validados — julio 2026
    CATEGORY_SLUGS: Dict[str, str] = {
        "CPU":         "procesadores",
        "GPU":         "tarjetas-de-video",
        "RAM":         "memorias-ram",
        "SSD":         "discos-solidos-ssd",
        "MOTHERBOARD": "placas-madre",
        "PSU":         "fuentes-de-poder",
        "COOLER":      "refrigeracion",
        "CASE":        "gabinetes",
    }

    # Query GraphQL VTEX — productSearch con paginación y campos mínimos
    _GQL_QUERY = """
    query productSearch(
      $query: String,
      $selectedFacets: [SelectedFacetInput],
      $from: Int,
      $to: Int
    ) @context(provider: "vtex.search-graphql@0.x") {
      productSearch(
        query: $query,
        selectedFacets: $selectedFacets,
        from: $from,
        to: $to,
        hideUnavailableItems: false
      ) {
        products {
          productId
          productName
          brand
          linkText
          items {
            itemId
            sellers {
              commertialOffer {
                Price
                ListPrice
                AvailableQuantity
              }
            }
          }
        }
        recordsFiltered
      }
    }
    """

    def __init__(self):
        self.session = _make_session()

    def close(self):
        self.session.close()

    def _gql_headers(self) -> dict:
        return {
            "User-Agent":   _get_ua(),
            "Accept":       "application/json",
            "Content-Type": "application/json",
            "Referer":      self.BASE_URL,
            "Origin":       self.BASE_URL,
        }

    def _fetch_page_gql(
        self,
        category_slug: str,
        from_idx: int,
        to_idx: int,
    ) -> Optional[Dict]:
        """
        [SC36] Ejecuta la query GraphQL para una página de productos.
        Retorna el dict 'productSearch' o None si hay error.
        """
        payload = {
            "query": self._GQL_QUERY,
            "variables": {
                "query":          "",
                "selectedFacets": [
                    {"key": "category-3", "value": category_slug}
                ],
                "from": from_idx,
                "to":   to_idx,
            },
        }
        try:
            resp = self.session.post(
                self.GQL_ENDPOINT,
                headers=self._gql_headers(),
                json=payload,
                timeout=25,
            )
            if resp.status_code != 200:
                log.error(
                    f"[Coolbox] GQL HTTP {resp.status_code} "
                    f"slug={category_slug} from={from_idx}"
                )
                return None
            data = resp.json()
            errors = data.get("errors")
            if errors:
                log.error(f"[Coolbox] GQL errors slug={category_slug}: {errors}")
                return None
            return data.get("data", {}).get("productSearch")
        except Exception:
            import traceback
            log.error(
                f"[Coolbox] GQL fetch error slug={category_slug} from={from_idx}:\n"
                f"{traceback.format_exc()}"
            )
            return None

    def _parse_gql_product(
        self,
        product: Dict,
        category: str,
        batch_id: str,
    ) -> Optional[Dict]:
        """
        [SC38] Convierte un producto VTEX GraphQL al schema público.
        Extrae: productId, sku (itemId), price, listPrice, disponibilidad.
        """
        try:
            product_id   = str(product.get("productId") or "").strip()
            title        = (product.get("productName") or "").strip()
            brand        = (product.get("brand") or "").strip() or None
            link_text    = (product.get("linkText") or "").strip()

            if not title:
                return None

            url_full = f"{self.BASE_URL}/{link_text}/p" if link_text else self.BASE_URL

            # [SC38] Extraer precio y stock del primer seller disponible
            price_pen      = None
            price_orig_pen = None
            available      = False
            sku            = None

            items = product.get("items") or []
            for item in items:
                item_id = str(item.get("itemId") or "").strip()
                sellers = item.get("sellers") or []
                for seller in sellers:
                    offer = seller.get("commertialOffer") or {}
                    qty   = offer.get("AvailableQuantity", 0)
                    price = offer.get("Price")
                    list_price = offer.get("ListPrice")

                    if price and float(price) > 0:
                        candidate = float(price)
                        # Tomar el precio más bajo entre sellers
                        if price_pen is None or candidate < price_pen:
                            price_pen = candidate
                            sku       = item_id or product_id
                            available = int(qty) > 0
                            if list_price and float(list_price) > candidate:
                                price_orig_pen = float(list_price)

            if not _valid_price(price_pen):
                return None

            # Fallback SKU
            if not sku:
                sku = product_id or _extract_sku_from_url(url_full)

            discount_pct = None
            if price_pen and price_orig_pen and price_orig_pen > price_pen:
                discount_pct = round((1 - price_pen / price_orig_pen) * 100, 1)

            return {
                "batch_id":       batch_id,
                "source":         self.SOURCE,
                "category":       category,
                "sku":            sku,
                "title":          title,
                "price_pen":      price_pen,
                "price_orig_pen": price_orig_pen,
                "discount_pct":   discount_pct,
                "url":            url_full,
                "brand":          brand,
                "available":      available,
                "rating":         None,
                "timestamp":      datetime.now(timezone.utc).isoformat(),
            }
        except Exception:
            import traceback
            log.error(f"[Coolbox] _parse_gql_product error:\n{traceback.format_exc()}")
            return None

    def scrape(self, category: str, queries: List[str], batch_id: str) -> List[Dict]:
        """
        [SC36/SC42] Scrape vía VTEX GraphQL con paginación por from/to.
        Detiene la paginación cuando se alcanza recordsFiltered [SC42].
        """
        records:  List[Dict] = []
        seen_ids: set        = set()

        slug = self.CATEGORY_SLUGS.get(category)
        if not slug:
            log.warning(f"  [Coolbox] Sin slug para categoría '{category}' — omitido")
            return records

        log.info(f"  [Coolbox] {category} | slug='{slug}' (GraphQL)")

        page = 0
        while page < MAX_PAGES:
            from_idx = page * self.PAGE_SIZE
            to_idx   = from_idx + self.PAGE_SIZE - 1

            result = self._fetch_page_gql(slug, from_idx, to_idx)
            if not result:
                log.debug(f"    [Coolbox] p{page + 1}: sin resultado GQL — stop")
                break

            products        = result.get("products") or []
            records_filtered = int(result.get("recordsFiltered") or 0)

            if not products:
                log.debug(f"    [Coolbox] p{page + 1}: lista vacía — stop")
                break

            new_in_page = 0
            for prod in products:
                rec = self._parse_gql_product(prod, category, batch_id)
                if not rec:
                    continue
                pid = str(prod.get("productId") or "").strip()
                if pid:
                    if pid in seen_ids:
                        continue
                    seen_ids.add(pid)
                records.append(rec)
                new_in_page += 1

            # [SC42] Verificar si hay más páginas usando recordsFiltered
            fetched_so_far = from_idx + len(products)
            has_next       = fetched_so_far < records_filtered

            log.debug(
                f"    [Coolbox] p{page + 1}: +{new_in_page} "
                f"(total={fetched_so_far}/{records_filtered})"
            )

            page += 1
            if not has_next or new_in_page == 0:
                break
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

                price_el  = item.select_one("span[data-price-type='finalPrice'] span.price")
                price_pen = _parse_price_str(price_el.get_text() if price_el else "")
                if not _valid_price(price_pen):
                    continue

                orig_el        = item.select_one("span[data-price-type='oldPrice'] span.price")
                price_orig_pen = _parse_price_str(orig_el.get_text() if orig_el else "")

                discount_pct = None
                if price_pen and price_orig_pen and price_orig_pen > price_pen:
                    discount_pct = round((1 - price_pen / price_orig_pen) * 100, 1)

                # [SC28]
                dp_el = item.select_one("[data-product-id]")
                sku = (
                    item.get("data-product-id")
                    or (dp_el.get("data-product-id") if dp_el else None)
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
    log.info("  SCRAPING COMPETENCIA PE  v4.4")
    log.info(f"  Fuentes: {sources} | Categorías: {categories}")
    log.info("══════════════════════════════════════════════════")

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
    before      = len(all_records)
    all_records = _dedup(all_records)
    after       = len(all_records)
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
