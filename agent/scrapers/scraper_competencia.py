# ✅ Archivo completo corregido — `scraper_competencia.py` v4.2

Aplico los 5 parches (`[SC26]`-`[SC30]`) más un bug adicional que encontré al escribir el código completo (`[SC31]`, explicado abajo). Aquí está el archivo íntegro, listo para reemplazar el actual:

```python
#!/usr/bin/env python3
"""
scraper_competencia.py  v4.2
════════════════════════════
Fuentes de PRECIO DE COMPETENCIA (referencia precio techo PE):
  - Falabella PE   (API JSON v2 + fallback HTML)
  - Hiraoka PE     (HTML Magento 2 — categoría directa + fallback búsqueda)
  - Coolbox PE     (HTML — tienda especializada hardware/gaming)
  - Compumundo PE  (HTML Magento 2 — DESHABILITADO por SSL mismatch)
  - Ripley PE      (PENDIENTE — 403 Cloudflare, requiere playwright)

Fixes v4.2 (sobre v4.1):
  [SC26] _extract_sku_from_url(): nuevo helper — deriva un identificador
         estable desde la URL del producto cuando la fuente no expone un
         ID explícito en el HTML/JSON. Usado como fallback en las 4 fuentes.
  [SC27] FalabellaScraper._parse_api()/_fetch_html(): el 'pid' que la API
         YA devolvía (productId/id/skuId) se usaba solo para dedup interno
         de página y se DESCARTABA antes de construir el registro final.
         Ahora se propaga como campo 'sku'. Sin esto, cada cambio de precio
         de un mismo producto Falabella se veía como producto nuevo en
         main.py._make_dedup_key() (fallback title+price).
  [SC28] HiraokaScraper / CoolboxScraper / CompumundoScraper._parse_html():
         se agrega extracción de 'sku' desde el atributo data-product-id
         del card (ya usado como selector, nunca leído) con fallback a
         _extract_sku_from_url(). Mismo problema que [SC27], mismo fix.
  [SC29] COMP_FIELDS_PUBLIC: se agrega 'sku' — sin esto, aunque los 4
         scrapers ya generaran el campo, este filtro final lo eliminaba
         antes de llegar a main.py/save_batch().
  [SC30] _dedup(): la identidad ya NO incluye price_pen. Antes,
         f"{source}|{title}|{price}" rompía la deduplicación intra-batch
         apenas el precio cambiaba entre dos queries que traían el mismo
         producto. Ahora usa sku > url > title, en ese orden.
  [SC31] FalabellaScraper._parse_api(): guard `if pid and pid in seen_ids`
         — el bug original `if pid in seen_ids` trataba TODOS los
         productos sin id (pid="") como si fueran el MISMO producto
         (colisión en el set por string vacío), descartando productos
         válidos que Falabella no expone con productId/id/skuId.

Fixes v4.1 (sobre v4.0):
  [SC21] COMPUMUNDO_ENABLED: leído desde env — deshabilita CompumundoScraper
         si COMPUMUNDO_ENABLED=false (SSL mismatch permanente — ahorra ~12 min)
  [SC22] scrape_competencia(): sources default excluye compumundo si
         COMPUMUNDO_ENABLED=false (consistencia con [SC21])
  [SC23] scrape_competencia(): parámetro mode agregado — alinea firma
         con main.py (main.py pasa mode= a todos los scrapers)
  [SC24] _dedup(): float() con fallback 0.0 — evita ValueError si
         price_pen es string no numérico en registros mal formados
  [SC25] CompumundoScraper: verify=False + suppress InsecureRequestWarning
         como fallback si COMPUMUNDO_ENABLED=true (SSL mismatch conocido)
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
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# ── UA rotativo ────────────────────────────────────────────────────────────
try:
    from fake_useragent import UserAgent as _UA
    _ua_gen = _UA()
except ImportError:
    _ua_gen = None

_UA_FALLBACK = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

log = logging.getLogger(__name__)

OUTPUT_DIR          = Path(os.getenv("OUTPUT_DIR", "data/raw"))
MAX_PAGES           = int(os.getenv("MAX_PAGES_COMP", "5"))
DELAY_REQ           = float(os.getenv("DELAY_REQ", "2.0"))
DELAY_CAT           = float(os.getenv("DELAY_CAT", "6.0"))           # [SC20]
MAX_QUERIES_PER_CAT = int(os.getenv("MAX_QUERIES_COMP", "2"))        # [SC15]
PRICE_MIN           = float(os.getenv("PRICE_MIN_PEN", "10.0"))      # [SC16]
PRICE_MAX           = float(os.getenv("PRICE_MAX_PEN", "50000.0"))   # [SC16]
# [SC21] Leído desde env — workflows v6.2/v2.1 setean COMPUMUNDO_ENABLED=false
COMPUMUNDO_ENABLED  = os.getenv("COMPUMUNDO_ENABLED", "true").lower() == "true"


# ── [SC14] Sesión con retry automático ────────────────────────────────────
def _make_session(verify_ssl: bool = True) -> requests.Session:
    """
    Sesión HTTP con reintentos automáticos en errores 429/5xx.
    [SC25] verify_ssl=False para CompumundoScraper (SSL mismatch conocido).
    """
    s     = requests.Session()
    s.verify = verify_ssl
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://",  HTTPAdapter(max_retries=retry))
    return s


def _get_ua() -> str:
    return _ua_gen.random if _ua_gen else _UA_FALLBACK

def _headers(referer="https://www.google.com") -> dict:
    return {
        "User-Agent":      _get_ua(),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
        "Referer":         referer,
    }

def _json_headers(referer="") -> dict:
    return {
        "User-Agent": _get_ua(),
        "Accept":     "application/json, text/plain, */*",
        "Referer":    referer,
    }


# ── [SC13] Parser de precios — limpieza explícita de S/. ─────────────────
def _parse_price_str(text: str) -> Optional[float]:
    if not text:
        return None
    # [SC13] Remover símbolo de moneda peruano antes del regex
    clean = re.sub(r"[Ss]/\.?\s*", "", str(text).strip())
    clean = re.sub(r"[^\d,.]", "", clean)
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


# ── [SC16] Validador de precio dentro de rango razonable ─────────────────
def _valid_price(price: float) -> bool:
    return PRICE_MIN <= price <= PRICE_MAX


# ── [SC26] Extractor de SKU/ID estable desde URL ──────────────────────────
_FALABELLA_URL_ID_RE = re.compile(r"/product/(\d+)")

def _extract_sku_from_url(url: str) -> str:
    """
    [SC26] Deriva un identificador estable desde la URL del producto.
    Usado como FALLBACK cuando la fuente no expone un id explícito
    (data-product-id, productId, etc.) en el HTML/JSON.

    Los slugs de producto (Falabella /product/<id>/, o el último
    segmento en Magento tipo /nombre-producto-12345.html) se mantienen
    ESTABLES entre scrapes de días distintos — a diferencia del título
    (puede llevar prefijos promocionales variables como "¡OFERTA!") o
    el precio (cambia constantemente y NUNCA debe formar parte de la
    identidad de un producto — ver bug corregido en [SC27]/[SC30]).
    """
    if not url:
        return ""
    m = _FALABELLA_URL_ID_RE.search(url)
    if m:
        return f"fal_{m.group(1)}"
    tail = url.rstrip("/").split("/")[-1]
    tail = re.sub(r"\.html?$", "", tail, flags=re.I)
    tail = re.sub(r"\?.*$", "", tail)
    return tail[:80] if tail else ""


# ── Queries por categoría ─────────────────────────────────────────────────
CATEGORY_QUERIES_PE = {
    "CPU": [
        "procesador intel core i5", "procesador intel core i7",
        "procesador intel core i9", "procesador amd ryzen 5",
        "procesador amd ryzen 7", "procesador amd ryzen 9",
    ],
    "GPU": [
        "tarjeta de video nvidia rtx 4060", "tarjeta de video nvidia rtx 4070",
        "tarjeta de video nvidia rtx 4080", "tarjeta de video amd radeon rx 7800",
        "tarjeta grafica geforce rtx",
    ],
    "RAM": [
        "memoria ram ddr4 16gb", "memoria ram ddr4 32gb",
        "memoria ram ddr5", "memoria ram corsair", "memoria ram kingston fury",
    ],
    "SSD": [
        "disco solido nvme 1tb", "disco solido nvme 2tb",
        "ssd m2 pcie", "disco solido samsung 990", "disco solido wd black",
    ],
    "MOTHERBOARD": [
        "placa madre intel z790", "placa madre intel b760",
        "placa madre amd x670", "placa madre amd b650", "motherboard asus rog",
    ],
    "PSU": [
        "fuente de poder 850w gold", "fuente de poder 1000w platinum",
        "fuente corsair rm850x", "fuente seasonic 850w", "fuente poder 80 plus",
    ],
    "COOLER": [
        "cooler liquido 240mm cpu", "cooler liquido 360mm aio",
        "disipador cpu noctua", "refrigeracion liquida cpu", "cooler cpu be quiet",
    ],
    "CASE": [
        "case gamer atx vidrio templado", "gabinete pc gamer mid tower",
        "case lian li", "gabinete fractal design", "case nzxt h510",
    ],
}

# [SC29] 'sku' agregado — sin esto, el campo se descartaba antes de
# llegar a main.py aunque los scrapers ya lo generaran.
COMP_FIELDS_PUBLIC = [
    "batch_id", "source", "category", "sku", "title",
    "price_pen", "price_orig_pen",
    "discount_pct", "url", "brand",
    "available", "rating", "timestamp",
]


# ══════════════════════════════════════════════════════════════════════════
# SCRAPER 1 — FALABELLA PE
# ══════════════════════════════════════════════════════════════════════════
class FalabellaScraper:
    # [SC11] Migrado a v2 + zona Lima Metropolitana
    API_BASE = "https://www.falabella.com.pe/s/browse/v2/listing/pe"

    def __init__(self):
        self._session = _make_session()  # [SC14]

    def search(self, query: str, category: str, batch_id: str,
               max_pages: int = MAX_PAGES) -> list:
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
            # [SC11] zones=150101 (Lima Metropolitana)
            params = {
                "Ntt":       query,
                "page":      page,
                "imageSize": "zoom",
                "zones":     "150101",
            }
            resp = self._session.get(
                self.API_BASE, params=params,
                headers=_json_headers("https://www.falabella.com.pe/"),
                timeout=20,
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
        items = []
        ts    = datetime.now(timezone.utc).isoformat()

        products = (
            data.get("results") or
            data.get("products") or
            data.get("data", {}).get("results") or
            data.get("data", {}).get("products") or
            []
        )

        if not products:
            def extract_products(obj, depth=0):
                if depth > 4:
                    return []
                found = []
                if isinstance(obj, list):
                    for item in obj:
                        if isinstance(item, dict):
                            if any(k in item for k in ["displayName", "productName", "name", "title"]):
                                if any(k in item for k in ["prices", "price", "offerPrice"]):
                                    found.append(item)
                            found.extend(extract_products(item, depth + 1))
                elif isinstance(obj, dict):
                    for v in obj.values():
                        found.extend(extract_products(v, depth + 1))
                return found
            products = extract_products(data)

        seen_ids = set()
        for p in products:
            try:
                pid = p.get("productId") or p.get("id") or p.get("skuId") or ""

                # [SC31] Guard 'if pid and ...' — antes, TODOS los productos
                # sin id (pid="") colisionaban en seen_ids y se descartaban
                # entre sí como si fueran el mismo producto duplicado.
                if pid and pid in seen_ids:
                    continue
                if pid:
                    seen_ids.add(pid)

                title = (p.get("displayName") or p.get("productName") or
                         p.get("name") or p.get("title") or "")

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
                    for key in ["offerPrice", "salePrice", "normalPrice", "originalPrice", "price"]:
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

                # [SC16] Validar rango de precio
                if not _valid_price(price_pen):
                    continue

                discount = 0.0
                if price_orig > 0 and price_pen > 0 and price_orig > price_pen:
                    discount = round((price_orig - price_pen) / price_orig * 100, 1)

                brand    = p.get("brand") or p.get("brandName") or ""
                url_path = p.get("url") or p.get("pdpUrl") or p.get("productUrl") or ""
                url      = (f"https://www.falabella.com.pe{url_path}"
                            if url_path and not url_path.startswith("http") else url_path)
                rating    = float(p.get("rating") or p.get("averageRating") or 0)
                available = bool(p.get("available") or p.get("isAvailable") or p.get("stock"))

                # [SC27] SKU real desde la API — antes se descartaba tras
                # usarse solo para el dedup local de página (seen_ids).
                sku = f"fal_{pid}" if pid else _extract_sku_from_url(str(url))

                if title:
                    items.append({
                        "batch_id":       batch_id,
                        "source":         "falabella_benchmark",
                        "category":       category,
                        "sku":            sku,                    # [SC27]
                        "title":          str(title)[:200],
                        "price_pen":      round(price_pen, 2),
                        "price_orig_pen": round(price_orig, 2),
                        "discount_pct":   discount,
                        "url":            str(url)[:300],
                        "brand":          str(brand)[:100],
                        "available":      available,
                        "rating":         rating,
                        "timestamp":      ts,
                    })
            except Exception as e:
                log.debug(f"    parse Falabella error: {e}")
        return items

    def _fetch_html(self, query, page, category, batch_id):
        try:
            url  = (f"https://www.falabella.com.pe/falabella-pe/search"
                    f"?Ntt={requests.utils.quote(query)}&page={page}")
            resp = self._session.get(
                url, headers=_headers("https://www.falabella.com.pe/"), timeout=20
            )
            if resp.status_code != 200:
                return []
            m = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                resp.text, re.DOTALL
            )
            if m:
                try:
                    data  = json.loads(m.group(1))
                    items = self._parse_api(data, category, batch_id)
                    if items:
                        return items
                except Exception:
                    pass
            soup  = BeautifulSoup(resp.text, "html.parser")
            items = []
            ts    = datetime.now(timezone.utc).isoformat()
            for card in soup.select(
                "div[class*='product-card'],div[class*='ProductCard'],"
                "li[class*='search-results']"
            ):
                try:
                    title_el = card.select_one(
                        "b[class*='pod-title'],span[class*='pod-title'],"
                        "a[class*='pod-title']"
                    )
                    price_el = card.select_one(
                        "span[class*='copy10'],li[class*='prices-0'],"
                        "span[class*='price']"
                    )
                    if not title_el or not price_el:
                        continue
                    title = title_el.get_text(strip=True)
                    price = _parse_price_str(price_el.get_text(strip=True)) or 0.0
                    if _valid_price(price) and title:  # [SC16]
                        items.append({
                            "batch_id": batch_id, "source": "falabella",
                            "category": category,
                            "sku": _extract_sku_from_url(url),      # [SC27]
                            "title": title[:200],
                            "price_pen": price, "price_orig_pen": 0.0,
                            "discount_pct": 0.0, "url": url[:300],
                            "brand": "", "available": True,
                            "rating": 0.0, "timestamp": ts,
                        })
                except Exception:
                    continue
            return items
        except Exception as e:
            log.error(f"    Falabella HTML error: {e}")
            return []


# ══════════════════════════════════════════════════════════════════════════
# SCRAPER 2 — RIPLEY PE
# PENDIENTE: requiere playwright para bypass Cloudflare 403
# ══════════════════════════════════════════════════════════════════════════
# class RipleyScraper:
#     DESHABILITADO — Cloudflare JS Challenge bloquea requests estándar.
#     Implementación futura: playwright + stealth plugin.


# ══════════════════════════════════════════════════════════════════════════
# SCRAPER 3 — HIRAOKA PE
# ══════════════════════════════════════════════════════════════════════════
class HiraokaScraper:
    BASE = "https://www.hiraoka.com.pe"

    # [SC12] Paths actualizados a estructura /componentes/* (2026)
    CATEGORY_PATHS = {
        "CPU":         "/componentes/procesadores",
        "GPU":         "/componentes/tarjetas-de-video",
        "RAM":         "/componentes/memorias-ram",
        "SSD":         "/componentes/discos-solidos",
        "MOTHERBOARD": "/componentes/placas-madre",
        "PSU":         "/componentes/fuentes-de-poder",
        "COOLER":      "/componentes/refrigeracion",
        "CASE":        "/componentes/cases-y-gabinetes",
    }

    def __init__(self):
        self._session = _make_session()  # [SC14]

    def search(self, query: str, category: str, batch_id: str,
               max_pages: int = MAX_PAGES) -> list:
        items    = []
        cat_path = self.CATEGORY_PATHS.get(category)

        if cat_path:
            for page in range(1, max_pages + 1):
                log.info(f"  [Hiraoka] {category} | categoría directa | pág {page}")
                page_items = self._fetch_category(cat_path, page, category, batch_id)
                items.extend(page_items)
                log.info(f"    → {len(page_items)} items (total: {len(items)})")
                if not page_items:
                    break
                time.sleep(DELAY_REQ)

            if not items:
                log.info(f"  [Hiraoka] {category} | cat=0 → fallback búsqueda")
                for page in range(1, min(max_pages, 3) + 1):
                    log.info(f"  [Hiraoka] {category} | búsqueda '{query[:30]}' | pág {page}")
                    page_items = self._fetch_search(query, page, category, batch_id)
                    items.extend(page_items)
                    log.info(f"    → {len(page_items)} items (total: {len(items)})")
                    if not page_items:
                        break
                    time.sleep(DELAY_REQ)
        else:
            for page in range(1, min(max_pages, 3) + 1):
                log.info(f"  [Hiraoka] {category} | búsqueda '{query[:30]}' | pág {page}")
                page_items = self._fetch_search(query, page, category, batch_id)
                items.extend(page_items)
                log.info(f"    → {len(page_items)} items (total: {len(items)})")
                if not page_items:
                    break
                time.sleep(DELAY_REQ)

        return items

    def _fetch_category(self, cat_path, page, category, batch_id):
        try:
            url  = f"{self.BASE}{cat_path}?p={page}"
            resp = self._session.get(
                url, headers=_headers(self.BASE + "/"), timeout=25
            )
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

    def _fetch_search(self, query, page, category, batch_id):
        try:
            url  = (f"{self.BASE}/catalogsearch/result/"
                    f"?q={requests.utils.quote(query)}&p={page}")
            resp = self._session.get(
                url, headers=_headers(self.BASE + "/"), timeout=25
            )
            if resp.status_code != 200:
                return []
            return self._parse_html(resp.text, category, batch_id, base_url=url)
        except Exception as e:
            log.error(f"    Hiraoka search error: {e}")
            return []

    def _parse_html(self, html, category, batch_id, base_url=""):
        soup  = BeautifulSoup(html, "html.parser")
        items = []
        ts    = datetime.now(timezone.utc).isoformat()

        cards = []
        for sel in [
            "li.product-item",
            "div.product-item-info",
            "li[class*='item product']",
            "div[class*='product-item']",
            "div.product-item-details",
            "article[class*='product']",
            "div[data-product-id]",
        ]:
            cards = soup.select(sel)
            if cards:
                break

        if not cards:
            log.debug(f"    Hiraoka: sin tarjetas en {base_url}")
            return []

        for card in cards:
            try:
                title_el = (
                    card.select_one("a.product-item-link") or
                    card.select_one("strong.product-item-name a") or
                    card.select_one("a[class*='product-item-link']") or
                    card.select_one("span[class*='product-name']") or
                    card.select_one("a[class*='product-name']") or
                    card.select_one("h2.product-name a") or
                    card.select_one("h3[class*='product'] a")
                )
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title:
                    continue

                price_pen  = 0.0
                price_orig = 0.0

                final_el = (
                    card.select_one("span[data-price-type='finalPrice'] span.price") or
                    card.select_one("span[class*='price-final'] span.price") or
                    card.select_one("span.special-price span.price") or
                    card.select_one("span[data-price-type='minPrice'] span.price") or
                    card.select_one("span.price")
                )
                if final_el:
                    price_pen = _parse_price_str(final_el.get_text(strip=True)) or 0.0

                orig_el = (
                    card.select_one("span[data-price-type='oldPrice'] span.price") or
                    card.select_one("span.old-price span.price") or
                    card.select_one("span[class*='regular-price'] span.price")
                )
                if orig_el:
                    price_orig = _parse_price_str(orig_el.get_text(strip=True)) or 0.0

                # [SC16] Validar rango
                if not _valid_price(price_pen):
                    continue

                discount = 0.0
                if price_orig > price_pen > 0:
                    discount = round((price_orig - price_pen) / price_orig * 100, 1)

                link_el  = (card.select_one("a.product-item-link") or
                            card.select_one("a[href*='hiraoka']"))
                item_url = link_el.get("href", "") if link_el else ""
                if item_url and not item_url.startswith("http"):
                    item_url = self.BASE + item_url

                brand_el = (
                    card.select_one("div.product-item-brand") or
                    card.select_one("span[class*='brand']") or
                    card.select_one("div[class*='brand']")
                )
                brand = brand_el.get_text(strip=True) if brand_el else ""

                stock_el  = (card.select_one("div.stock") or
                             card.select_one("span[class*='stock']"))
                available = True
                if stock_el:
                    available = "unavailable" not in stock_el.get("class", [])

                rating_el = (card.select_one("span.rating-result") or
                             card.select_one("div[class*='rating']"))
                rating = 0.0
                if rating_el:
                    style = rating_el.get("style", "")
                    m     = re.search(r"width:\s*([\d.]+)%", style)
                    if m:
                        rating = round(float(m.group(1)) / 20, 1)

                # [SC28] SKU desde data-product-id del card, o desde URL
                sku_attr = card.get("data-product-id") or card.get("data-id") or ""
                sku = f"hir_{sku_attr}" if sku_attr else _extract_sku_from_url(item_url)

                items.append({
                    "batch_id":       batch_id,
                    "source":         "hiraoka_benchmark",
                    "category":       category,
                    "sku":            sku,                        # [SC28]
                    "title":          title[:200],
                    "price_pen":      round(price_pen, 2),
                    "price_orig_pen": round(price_orig, 2),
                    "discount_pct":   discount,
                    "url":            item_url[:300],
                    "brand":          brand[:100],
                    "available":      available,
                    "rating":         rating,
                    "timestamp":      ts,
                })
            except Exception as e:
                log.debug(f"    parse Hiraoka card error: {e}")
                continue

        return items


# ══════════════════════════════════════════════════════════════════════════
# SCRAPER 4 — COOLBOX PE  [SC17]
# Tienda especializada en hardware/gaming — HTML estático
# ══════════════════════════════════════════════════════════════════════════
class CoolboxScraper:
    BASE = "https://www.coolbox.pe"

    CATEGORY_PATHS = {
        "CPU":         "/procesadores",
        "GPU":         "/tarjetas-de-video",
        "RAM":         "/memorias-ram",
        "SSD":         "/almacenamiento/discos-solidos-ssd",
        "MOTHERBOARD": "/placas-madre",
        "PSU":         "/fuentes-de-poder",
        "COOLER":      "/refrigeracion",
        "CASE":        "/cases",
    }

    def __init__(self):
        self._session = _make_session()

    def search(self, query: str, category: str, batch_id: str,
               max_pages: int = MAX_PAGES) -> list:
        items    = []
        cat_path = self.CATEGORY_PATHS.get(category)

        if cat_path:
            for page in range(1, max_pages + 1):
                log.info(f"  [Coolbox] {category} | categoría directa | pág {page}")
                page_items = self._fetch_category(cat_path, page, category, batch_id)
                items.extend(page_items)
                log.info(f"    → {len(page_items)} items (total: {len(items)})")
                if not page_items:
                    break
                time.sleep(DELAY_REQ)

        if not items:
            log.info(f"  [Coolbox] {category} | fallback búsqueda '{query[:30]}'")
            for page in range(1, min(max_pages, 3) + 1):
                page_items = self._fetch_search(query, page, category, batch_id)
                items.extend(page_items)
                log.info(f"    → {len(page_items)} items (total: {len(items)})")
                if not page_items:
                    break
                time.sleep(DELAY_REQ)

        return items

    def _fetch_category(self, cat_path, page, category, batch_id):
        try:
            url  = f"{self.BASE}{cat_path}?page={page}"
            resp = self._session.get(
                url, headers=_headers(self.BASE + "/"), timeout=25
            )
            if resp.status_code == 404:
                return []
            if resp.status_code != 200:
                log.warning(f"    Coolbox HTTP {resp.status_code}: {url}")
                return []
            return self._parse_html(resp.text, category, batch_id, base_url=url)
        except Exception as e:
            log.error(f"    Coolbox category error: {e}")
            return []

    def _fetch_search(self, query, page, category, batch_id):
        try:
            url  = f"{self.BASE}/search?q={requests.utils.quote(query)}&page={page}"
            resp = self._session.get(
                url, headers=_headers(self.BASE + "/"), timeout=25
            )
            if resp.status_code != 200:
                return []
            return self._parse_html(resp.text, category, batch_id, base_url=url)
        except Exception as e:
            log.error(f"    Coolbox search error: {e}")
            return []

    def _parse_html(self, html, category, batch_id, base_url=""):
        soup  = BeautifulSoup(html, "html.parser")
        items = []
        ts    = datetime.now(timezone.utc).isoformat()

        cards = []
        for sel in [
            "div.product-card",
            "div[class*='product-card']",
            "article.product-item",
            "div[class*='ProductCard']",
            "li.grid__item",
            "div.grid-product",
            "div[class*='product-grid-item']",
            "div[data-product-id]",
        ]:
            cards = soup.select(sel)
            if cards:
                break

        if not cards:
            log.debug(f"    Coolbox: sin tarjetas en {base_url}")
            return []

        for card in cards:
            try:
                title_el = (
                    card.select_one("h2.product-card__title") or
                    card.select_one("h3.product-card__title") or
                    card.select_one("a.product-card__title") or
                    card.select_one("span[class*='product-title']") or
                    card.select_one("h2[class*='title']") or
                    card.select_one("h3[class*='title']") or
                    card.select_one("a[class*='title']") or
                    card.select_one("p.grid-product__title")
                )
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title:
                    continue

                price_pen  = 0.0
                price_orig = 0.0

                price_el = (
                    card.select_one("span.product-card__price") or
                    card.select_one("span[class*='price--sale']") or
                    card.select_one("span[class*='price']") or
                    card.select_one("div[class*='price']") or
                    card.select_one("p.grid-product__price")
                )
                if price_el:
                    price_pen = _parse_price_str(price_el.get_text(strip=True)) or 0.0

                orig_el = (
                    card.select_one("span[class*='price--compare']") or
                    card.select_one("s[class*='price']") or
                    card.select_one("span.compare-price")
                )
                if orig_el:
                    price_orig = _parse_price_str(orig_el.get_text(strip=True)) or 0.0

                # [SC16] Validar rango
                if not _valid_price(price_pen):
                    continue

                discount = 0.0
                if price_orig > price_pen > 0:
                    discount = round((price_orig - price_pen) / price_orig * 100, 1)

                link_el  = card.select_one("a[href]")
                item_url = link_el.get("href", "") if link_el else ""
                if item_url and not item_url.startswith("http"):
                    item_url = self.BASE + item_url

                brand_el = (card.select_one("span[class*='brand']") or
                            card.select_one("div[class*='vendor']"))
                brand    = brand_el.get_text(strip=True) if brand_el else ""

                stock_el  = (card.select_one("span[class*='stock']") or
                             card.select_one("div[class*='badge']"))
                available = True
                if stock_el:
                    txt = stock_el.get_text(strip=True).lower()
                    available = not any(x in txt for x in ["agotado", "sin stock", "out of stock"])

                # [SC28] SKU desde data-product-id del card, o desde URL
                sku_attr = card.get("data-product-id") or card.get("data-id") or ""
                sku = f"cbx_{sku_attr}" if sku_attr else _extract_sku_from_url(item_url)

                items.append({
                    "batch_id":       batch_id,
                    "source":         "coolbox",
                    "category":       category,
                    "sku":            sku,                        # [SC28]
                    "title":          title[:200],
                    "price_pen":      round(price_pen, 2),
                    "price_orig_pen": round(price_orig, 2),
                    "discount_pct":   discount,
                    "url":            item_url[:300],
                    "brand":          brand[:100],
                    "available":      available,
                    "rating":         0.0,
                    "timestamp":      ts,
                })
            except Exception as e:
                log.debug(f"    parse Coolbox card error: {e}")
                continue

        return items


# ══════════════════════════════════════════════════════════════════════════
# SCRAPER 5 — COMPUMUNDO PE  [SC18]
# Hardware y componentes — HTML Magento 2
# [SC21] Deshabilitado por defecto via COMPUMUNDO_ENABLED=false
# [SC25] Si habilitado: verify=False para bypass SSL mismatch conocido
# ══════════════════════════════════════════════════════════════════════════
class CompumundoScraper:
    BASE = "https://www.compumundo.com.pe"

    CATEGORY_PATHS = {
        "CPU":         "/procesadores",
        "GPU":         "/tarjetas-de-video",
        "RAM":         "/memorias",
        "SSD":         "/almacenamiento/ssd",
        "MOTHERBOARD": "/placas-madre",
        "PSU":         "/fuentes-de-poder",
        "COOLER":      "/refrigeracion",
        "CASE":        "/cases",
    }

    def __init__(self):
        # [SC25] verify=False — SSL mismatch en www.compumundo.com.pe
        import urllib3
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._session = _make_session(verify_ssl=False)  # [SC25]

    def search(self, query: str, category: str, batch_id: str,
               max_pages: int = MAX_PAGES) -> list:
        items    = []
        cat_path = self.CATEGORY_PATHS.get(category)

        if cat_path:
            for page in range(1, max_pages + 1):
                log.info(f"  [Compumundo] {category} | categoría directa | pág {page}")
                page_items = self._fetch_category(cat_path, page, category, batch_id)
                items.extend(page_items)
                log.info(f"    → {len(page_items)} items (total: {len(items)})")
                if not page_items:
                    break
                time.sleep(DELAY_REQ)

        if not items:
            log.info(f"  [Compumundo] {category} | fallback búsqueda '{query[:30]}'")
            for page in range(1, min(max_pages, 3) + 1):
                page_items = self._fetch_search(query, page, category, batch_id)
                items.extend(page_items)
                log.info(f"    → {len(page_items)} items (total: {len(items)})")
                if not page_items:
                    break
                time.sleep(DELAY_REQ)

        return items

    def _fetch_category(self, cat_path, page, category, batch_id):
        try:
            url  = f"{self.BASE}{cat_path}?p={page}"
            resp = self._session.get(
                url, headers=_headers(self.BASE + "/"), timeout=25
            )
            if resp.status_code == 404:
                return []
            if resp.status_code != 200:
                log.warning(f"    Compumundo HTTP {resp.status_code}: {url}")
                return []
            return self._parse_html(resp.text, category, batch_id, base_url=url)
        except Exception as e:
            log.error(f"    Compumundo category error: {e}")
            return []

    def _fetch_search(self, query, page, category, batch_id):
        try:
            url  = (f"{self.BASE}/catalogsearch/result/"
                    f"?q={requests.utils.quote(query)}&p={page}")
            resp = self._session.get(
                url, headers=_headers(self.BASE + "/"), timeout=25
            )
            if resp.status_code != 200:
                return []
            return self._parse_html(resp.text, category, batch_id, base_url=url)
        except Exception as e:
            log.error(f"    Compumundo search error: {e}")
            return []

    def _parse_html(self, html, category, batch_id, base_url=""):
        """Parser Magento 2 — misma lógica que HiraokaScraper."""
        soup  = BeautifulSoup(html, "html.parser")
        items = []
        ts    = datetime.now(timezone.utc).isoformat()

        cards = []
        for sel in [
            "li.product-item",
            "div.product-item-info",
            "li[class*='item product']",
            "div[class*='product-item']",
            "article[class*='product']",
            "div[data-product-id]",
        ]:
            cards = soup.select(sel)
            if cards:
                break

        if not cards:
            log.debug(f"    Compumundo: sin tarjetas en {base_url}")
            return []

        for card in cards:
            try:
                title_el = (
                    card.select_one("a.product-item-link") or
                    card.select_one("strong.product-item-name a") or
                    card.select_one("a[class*='product-item-link']") or
                    card.select_one("span[class*='product-name']") or
                    card.select_one("h2.product-name a") or
                    card.select_one("h3[class*='product'] a")
                )
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title:
                    continue

                price_pen  = 0.0
                price_orig = 0.0

                final_el = (
                    card.select_one("span[data-price-type='finalPrice'] span.price") or
                    card.select_one("span.special-price span.price") or
                    card.select_one("span[data-price-type='minPrice'] span.price") or
                    card.select_one("span.price")
                )
                if final_el:
                    price_pen = _parse_price_str(final_el.get_text(strip=True)) or 0.0

                orig_el = (
                    card.select_one("span[data-price-type='oldPrice'] span.price") or
                    card.select_one("span.old-price span.price") or
                    card.select_one("span[class*='regular-price'] span.price")
                )
                if orig_el:
                    price_orig = _parse_price_str(orig_el.get_text(strip=True)) or 0.0

                # [SC16] Validar rango
                if not _valid_price(price_pen):
                    continue

                discount = 0.0
                if price_orig > price_pen > 0:
                    discount = round((price_orig - price_pen) / price_orig * 100, 1)

                link_el  = (card.select_one("a.product-item-link") or
                            card.select_one("a[href*='compumundo']"))
                item_url = link_el.get("href", "") if link_el else ""
                if item_url and not item_url.startswith("http"):
                    item_url = self.BASE + item_url

                brand_el = (
                    card.select_one("div.product-item-brand") or
                    card.select_one("span[class*='brand']") or
                    card.select_one("div[class*='manufacturer']")
                )
                brand = brand_el.get_text(strip=True) if brand_el else ""

                stock_el  = (card.select_one("div.stock") or
                             card.select_one("span[class*='stock']"))
                available = True
                if stock_el:
                    available = "unavailable" not in stock_el.get("class", [])

                # [SC28] SKU desde data-product-id del card, o desde URL
                sku_attr = card.get("data-product-id") or card.get("data-id") or ""
                sku = f"cmp_{sku_attr}" if sku_attr else _extract_sku_from_url(item_url)

                items.append({
                    "batch_id":       batch_id,
                    "source":         "compumundo",
                    "category":       category,
                    "sku":            sku,                        # [SC28]
                    "title":          title[:200],
                    "price_pen":      round(price_pen, 2),
                    "price_orig_pen": round(price_orig, 2),
                    "discount_pct":   discount,
                    "url":            item_url[:300],
                    "brand":          brand[:100],
                    "available":      available,
                    "rating":         0.0,
                    "timestamp":      ts,
                })
            except Exception as e:
                log.debug(f"    parse Compumundo card error: {e}")
                continue

        return items


# ══════════════════════════════════════════════════════════════════════════
# DEDUPLICACIÓN EN MEMORIA
# ══════════════════════════════════════════════════════════════════════════
def _dedup(records: list) -> list:
    """
    [SC24] float() con fallback 0.0 (sin cambios).
    [SC30] La clave de identidad ya NO incluye price_pen. Antes:
        key = f"{source}|{title[:100]}|{price}"
    rompía la deduplicación intra-batch apenas el precio cambiaba entre
    dos queries que traían el mismo producto (ej. "procesador intel core
    i5" y "procesador intel core i7" ambas devolviendo el mismo SKU con
    precio ligeramente distinto por timing de captura). El precio NUNCA
    debe formar parte de la identidad de un producto — mismo principio
    aplicado en main.py._make_dedup_key() [O27].

    Nueva prioridad de identidad: sku > url > title.
    """
    seen = set()
    out  = []
    for r in records:
        try:
            price = float(r.get("price_pen", 0) or 0)
        except (ValueError, TypeError):
            price = 0.0

        identity = r.get("sku") or r.get("url") or r.get("title", "")[:100]  # [SC30]
        key = f"{r.get('source')}|{identity}"
        fp  = hashlib.md5(key.encode()).hexdigest()[:12]

        if fp not in seen and _valid_price(price):
            seen.add(fp)
            out.append(r)
    return out


# ══════════════════════════════════════════════════════════════════════════
# INTERFAZ PÚBLICA
# ══════════════════════════════════════════════════════════════════════════
def scrape_competencia(
    batch_id: str,
    mode: str = "normal",       # [SC23] alinea firma con main.py
    sources: list = None,
    categories: list = None,
) -> list:
    """
    Scraper de precios de competencia PE.
    Retorna list[dict] compatible con save_batch() de main.py.

    [SC21] Compumundo excluido por defecto si COMPUMUNDO_ENABLED=false.
    [SC23] Parámetro mode agregado — main.py lo pasa a todos los scrapers.
    [SC27][SC28] Todos los productos ahora incluyen 'sku' derivado del
    ID real de la fuente (Falabella API) o del atributo data-product-id
    del card (Hiraoka/Coolbox/Compumundo), con fallback a un ID derivado
    de la URL — nunca del título+precio.

    sources disponibles: falabella, hiraoka, coolbox, compumundo
    (ripley: PENDIENTE — requiere playwright)
    """
    if sources is None:
        # [SC22] Excluir compumundo si COMPUMUNDO_ENABLED=false
        default_sources = ["falabella", "hiraoka", "coolbox"]
        if COMPUMUNDO_ENABLED:
            default_sources.append("compumundo")
        else:
            log.warning(
                "[Compumundo] DESHABILITADO (COMPUMUNDO_ENABLED=false) "
                "— SSL mismatch permanente. Omitido."
            )
        sources = default_sources

    if categories is None:
        categories = list(CATEGORY_QUERIES_PE.keys())

    scrapers = {}
    if "falabella"  in sources: scrapers["falabella"]  = FalabellaScraper()
    if "hiraoka"    in sources: scrapers["hiraoka"]    = HiraokaScraper()
    if "coolbox"    in sources: scrapers["coolbox"]    = CoolboxScraper()     # [SC17]
    if "compumundo" in sources: scrapers["compumundo"] = CompumundoScraper()  # [SC18][SC25]
    if "ripley"     in sources:
        log.warning("[Ripley] DESHABILITADO — 403 Cloudflare. Requiere playwright. Omitido.")

    all_records = []

    for category in categories:
        queries = CATEGORY_QUERIES_PE.get(category, [category.lower()])
        # [SC15] Limitar número de queries por categoría
        queries = queries[:MAX_QUERIES_PER_CAT]

        log.info(f"\n{'='*60}")
        log.info(f"CATEGORÍA: {category} ({len(queries)} queries / {MAX_QUERIES_PER_CAT} max)")
        log.info(f"{'='*60}")

        for query in queries:
            for src_name, scraper in scrapers.items():
                try:
                    items = scraper.search(query, category, batch_id, MAX_PAGES)
                    all_records.extend(items)
                except Exception as e:
                    log.error(f"  [{src_name}] error en '{query}': {e}")
                time.sleep(DELAY_REQ)
            time.sleep(DELAY_CAT)  # [SC20]

    unique_records = _dedup(all_records)

    log.info(
        f"\n[Competencia] TOTAL: {len(unique_records):,} registros únicos "
        f"(de {len(all_records):,} brutos)"
    )

    return [
        {k: r[k] for k in COMP_FIELDS_PUBLIC if k in r}
        for r in unique_records
    ]


# Alias para compatibilidad con código legacy
run_competencia = scrape_competencia


# ══════════════════════════════════════════════════════════════════════════
# STANDALONE
# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results  = scrape_competencia(batch_id)
    print(f"\nTotal: {len(results)} registros")
    if results:
        print("Ejemplo:", results[0])
