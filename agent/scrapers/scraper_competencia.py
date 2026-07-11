"""
scraper_competencia.py  v3.0
════════════════════════════
Fuentes de PRECIO DE COMPETENCIA (referencia precio techo PE):
  - Falabella PE  (API JSON interna + fallback HTML)
  - Ripley PE     (PENDIENTE — 403 Cloudflare, requiere playwright)
  - Hiraoka PE    (HTML Magento 2 — búsqueda por texto, con fallback categoría)

Fixes v3.0 (sobre v2.0):
  - [SC1]  _headers()/_json_headers(): UA rotativo via fake_useragent
  - [SC2]  FalabellaScraper._parse_api: intenta data['results'] antes de recursión
  - [SC3]  RipleyScraper: movida a bloque comentado con nota de playwright
  - [SC4]  HiraokaScraper.search(): fallback a _fetch_search() si _fetch_category()=0
           → causa raíz del Hiraoka (competencia) = 0 registros
  - [SC5]  HiraokaScraper: paginación documentada como limitada (Hiraoka ignora ?p>1)
  - [SC6]  HiraokaScraper._parse_html: selectores unificados con scraper_local.py
  - [SC7]  _dedup(): fingerprint usa title[:100] en lugar de title[:60]
  - [SC8]  Warning de Ripley emitido UNA vez al inicio, no en cada iteración
  - [SC9]  __main__: datetime.now(timezone.utc) — naive datetime corregido
  - [SC10] COMP_FIELDS_PUBLIC aplicado en el retorno de scrape_competencia()
"""

import os
import re
import time
import json
import hashlib
import logging
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

# [SC1] UA rotativo — consistente con scraper_camel v3.0
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

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "data/raw"))
MAX_PAGES  = int(os.getenv("MAX_PAGES_COMP", "5"))
DELAY_REQ  = float(os.getenv("DELAY_REQ", "2.0"))
DELAY_CAT  = float(os.getenv("DELAY_CAT", "4.0"))


# ── [SC1] Helpers de headers con UA rotativo ──────────────────────────────
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


# ── Parser de precios robusto ─────────────────────────────────────────────
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

# [SC10] Esquema público — aplicado en el retorno de scrape_competencia()
COMP_FIELDS_PUBLIC = [
    "batch_id", "source", "category", "title",
    "price_pen", "price_orig_pen",
    "discount_pct", "url", "brand",
    "available", "rating", "timestamp",
]


# ══════════════════════════════════════════════════════════════════════════
# SCRAPER 1 — FALABELLA PE
# ══════════════════════════════════════════════════════════════════════════
class FalabellaScraper:
    API_BASE = "https://www.falabella.com.pe/s/browse/v1/listing/pe"

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
            params = {"Ntt": query, "page": page, "imageSize": "zoom", "zones": "15"}
            resp   = requests.get(
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
        items = []
        ts    = datetime.now(timezone.utc).isoformat()

        # [SC2] Intentar claves directas antes de recursión
        products = (
            data.get("results") or
            data.get("products") or
            data.get("data", {}).get("results") or
            data.get("data", {}).get("products") or
            []
        )

        # Fallback recursivo solo si las claves directas no funcionan
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

                discount = 0.0
                if price_orig > 0 and price_pen > 0 and price_orig > price_pen:
                    discount = round((price_orig - price_pen) / price_orig * 100, 1)

                brand    = p.get("brand") or p.get("brandName") or ""
                url_path = p.get("url") or p.get("pdpUrl") or p.get("productUrl") or ""
                url      = (f"https://www.falabella.com.pe{url_path}"
                            if url_path and not url_path.startswith("http") else url_path)
                rating    = float(p.get("rating") or p.get("averageRating") or 0)
                available = bool(p.get("available") or p.get("isAvailable") or p.get("stock"))

                if price_pen > 0 and title:
                    items.append({
                        "batch_id":       batch_id,
                        "source":         "falabella",
                        "category":       category,
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
            resp = requests.get(
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
                    if price > 0 and title:
                        items.append({
                            "batch_id": batch_id, "source": "falabella",
                            "category": category, "title": title[:200],
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
# [SC3] PENDIENTE: requiere playwright para bypass Cloudflare 403
# Clase conservada para implementación futura — NO se instancia en producción
# ══════════════════════════════════════════════════════════════════════════
# class RipleyScraper:
#     """
#     DESHABILITADO — Cloudflare JS Challenge bloquea requests estándar.
#     Implementación futura: usar playwright con stealth plugin.
#     Ver: https://playwright.dev/python/docs/intro
#     """
#     API_BASE = "https://simple.ripley.com.pe/api/search"
#     ... (implementación completa en scraper_ripley.py cuando se habilite)


# ══════════════════════════════════════════════════════════════════════════
# SCRAPER 3 — HIRAOKA PE
# ══════════════════════════════════════════════════════════════════════════
class HiraokaScraper:
    BASE = "https://www.hiraoka.com.pe"

    # [SC4] Paths de categoría — pueden ser 404. search() tiene fallback a _fetch_search()
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

    def search(self, query: str, category: str, batch_id: str,
               max_pages: int = MAX_PAGES) -> list:
        """
        [SC4] Estrategia de búsqueda con fallback:
          1. Intenta URL de categoría directa (_fetch_category)
          2. Si retorna 0, usa búsqueda por texto (_fetch_search) — igual que scraper_local
        [SC5] Nota: Hiraoka ignora ?p>1 (paginación AJAX) → máximo ~20 items/cat
        """
        items    = []
        cat_path = self.CATEGORY_PATHS.get(category)

        if cat_path:
            # Intento 1: URL de categoría directa
            for page in range(1, max_pages + 1):
                log.info(f"  [Hiraoka] {category} | categoría directa | pág {page}")
                page_items = self._fetch_category(cat_path, page, category, batch_id)
                items.extend(page_items)
                log.info(f"    → {len(page_items)} items (total: {len(items)})")
                if not page_items:
                    break
                time.sleep(DELAY_REQ)

            # [SC4] Fallback: si categoría directa no funcionó, usar búsqueda por texto
            if not items:
                log.info(f"  [Hiraoka] {category} | categoría directa=0 → fallback búsqueda")
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
            resp = requests.get(
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
            resp = requests.get(
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

        # [SC6] Selectores unificados con scraper_local.py
        # Orden: más específico → más genérico
        cards = []
        for sel in [
            "li.product-item",
            "div.product-item-info",
            "li[class*='item product']",
            "div[class*='product-item']",
            # Selectores adicionales del HTML actual de Hiraoka (Magento 2.4+)
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
                    # [SC6] Selectores adicionales para Magento 2.4+
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
                    # [SC6] Selectores adicionales
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

                if price_pen == 0:
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

                items.append({
                    "batch_id":       batch_id,
                    "source":         "hiraoka",
                    "category":       category,
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
# DEDUPLICACIÓN EN MEMORIA
# ══════════════════════════════════════════════════════════════════════════
def _dedup(records: list) -> list:
    """
    Elimina duplicados por fingerprint MD5 (source|title|price).
    [SC7] Usa title[:100] en lugar de title[:60] para evitar falsos duplicados.
    """
    seen = set()
    out  = []
    for r in records:
        # [SC7] title[:100] — reduce falsos duplicados en títulos largos
        key = f"{r.get('source')}|{r.get('title','')[:100]}|{r.get('price_pen',0)}"
        fp  = hashlib.md5(key.encode()).hexdigest()[:12]
        if fp not in seen and float(r.get("price_pen", 0)) > 0:
            seen.add(fp)
            out.append(r)
    return out


# ══════════════════════════════════════════════════════════════════════════
# INTERFAZ PÚBLICA
# ══════════════════════════════════════════════════════════════════════════
def scrape_competencia(
    batch_id: str,
    sources: list = None,
    categories: list = None,
) -> list:
    """
    Scraper de precios de competencia PE.
    Retorna list[dict] compatible con save_batch() de main.py.
    """
    if sources is None:
        # [SC8] 'ripley' removido del default hasta que esté habilitado
        sources = ["falabella", "hiraoka"]
    if categories is None:
        categories = list(CATEGORY_QUERIES_PE.keys())

    scrapers = {}
    if "falabella" in sources:
        scrapers["falabella"] = FalabellaScraper()
    if "ripley" in sources:
        # [SC8] Warning emitido UNA vez al inicio, no en cada iteración del loop
        log.warning("[Ripley] DESHABILITADO — 403 Cloudflare. Requiere playwright. Omitido.")
    if "hiraoka" in sources:
        scrapers["hiraoka"] = HiraokaScraper()

    all_records = []

    for category in categories:
        queries = CATEGORY_QUERIES_PE.get(category, [category.lower()])
        log.info(f"\n{'='*60}")
        log.info(f"CATEGORÍA: {category} ({len(queries)} queries)")
        log.info(f"{'='*60}")

        for query in queries:
            for src_name, scraper in scrapers.items():
                try:
                    items = scraper.search(query, category, batch_id, MAX_PAGES)
                    all_records.extend(items)
                except Exception as e:
                    log.error(f"  [{src_name}] error en '{query}': {e}")
                time.sleep(DELAY_REQ)
            time.sleep(DELAY_CAT)

    unique_records = _dedup(all_records)

    log.info(
        f"\n[Competencia] TOTAL: {len(unique_records):,} registros únicos "
        f"(de {len(all_records):,} brutos)"
    )

    # [SC10] Aplicar esquema público — excluye campos internos si los hubiera
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
    # [SC9] datetime con timezone explícita
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results  = scrape_competencia(batch_id)
    print(f"\nTotal: {len(results)} registros")
    if results:
        print("Ejemplo:", results[0])
