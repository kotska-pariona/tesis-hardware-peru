"""
scraper_competencia.py  v2.0
════════════════════════════
Fuentes de PRECIO DE COMPETENCIA (referencia precio techo PE):
  - Falabella PE  (API JSON interna + fallback HTML)
  - Ripley PE     (API JSON interna + fallback HTML)
  - Hiraoka PE    (HTML Magento 2 con URLs de categoría)

Fixes v2.0:
  - [FIX-1] Alias scrape_competencia() → interfaz compatible con main.py
  - [FIX-2] scrape_competencia() retorna list[dict] — no tupla
  - [FIX-3] logging.basicConfig() eliminado del top-level
  - [FIX-4] extract_products() depth reducido de 8 → 4
  - [FIX-5] zones='15' (Lima) unificado con scraper_local.py
  - [FIX-6] find_list() valida campos de producto antes de retornar
  - [FIX-7] _parse_price_str() robusta (misma lógica que scraper_local v2)
  - [FIX-8] 'fingerprint' excluido del retorno público
  - [FIX-9] 'price_original_pen' → 'price_orig_pen' (esquema unificado)
  - [FIX-10] DEFAULT MAX_PAGES reducido de 30 → 5
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

# FIX-3: Sin basicConfig() — logging configurado solo en main.py
log = logging.getLogger(__name__)

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "data/raw"))
# FIX-10: default reducido de 30 → 5
MAX_PAGES  = int(os.getenv("MAX_PAGES_COMP", "5"))
DELAY_REQ  = float(os.getenv("DELAY_REQ", "2.0"))
DELAY_CAT  = float(os.getenv("DELAY_CAT", "4.0"))


# ── FIX-7: Parser de precios robusto ──────────────────────────────────────
def _parse_price_str(text: str) -> Optional[float]:
    """Convierte texto de precio a float — maneja S/, $, puntos y comas."""
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
            clean = clean.replace(",", ".") if len(parts) == 2 and len(parts[1]) <= 2 else clean.replace(",", "")
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

# FIX-9: Esquema unificado con scraper_local.py (price_orig_pen, no price_original_pen)
# FIX-8: 'fingerprint' excluido del esquema público
COMP_FIELDS_PUBLIC = [
    "batch_id", "source", "category", "title",
    "price_pen", "price_orig_pen",   # FIX-9
    "discount_pct", "url", "brand",
    "available", "rating", "timestamp",
]


# ── Headers ───────────────────────────────────────────────────────────────
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


# ══════════════════════════════════════════════════════════════════════════
# SCRAPER 1 — FALABELLA PE
# ══════════════════════════════════════════════════════════════════════════
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
            # FIX-5: zones='15' (Lima)
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

        # FIX-4: depth reducido de 8 → 4
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
                            val   = pr.get("price") or pr.get("value") or 0
                            label = str(pr.get("label", "")).lower()
                            parsed = _parse_price_str(str(val))   # FIX-7
                            if parsed:
                                if "oferta" in label or "precio" in label or not label:
                                    price_pen  = parsed
                                elif "normal" in label or "original" in label:
                                    price_orig = parsed
                elif isinstance(prices_obj, dict):
                    for key in ["offerPrice", "salePrice", "normalPrice", "originalPrice", "price"]:
                        val = prices_obj.get(key)
                        if val:
                            parsed = _parse_price_str(str(val))   # FIX-7
                            if parsed:
                                price_pen = parsed
                                break
                    for key in ["normalPrice", "originalPrice", "regularPrice"]:
                        val = prices_obj.get(key)
                        if val:
                            parsed = _parse_price_str(str(val))   # FIX-7
                            if parsed:
                                price_orig = parsed
                                break

                if price_pen == 0:
                    for key in ["offerPrice", "salePrice", "price", "currentPrice"]:
                        val = p.get(key)
                        if val:
                            parsed = _parse_price_str(str(val))   # FIX-7
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
                        "batch_id":      batch_id,
                        "source":        "falabella",
                        "category":      category,
                        "title":         str(title)[:200],
                        "price_pen":     round(price_pen, 2),
                        "price_orig_pen": round(price_orig, 2),   # FIX-9
                        "discount_pct":  discount,
                        "url":           str(url)[:300],
                        "brand":         str(brand)[:100],
                        "available":     available,
                        "rating":        rating,
                        "timestamp":     ts,
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
                    if items:
                        return items
                except Exception:
                    pass
            soup  = BeautifulSoup(resp.text, "html.parser")
            items = []
            ts    = datetime.now(timezone.utc).isoformat()
            for card in soup.select("div[class*='product-card'],div[class*='ProductCard'],li[class*='search-results']"):
                try:
                    title_el = card.select_one("b[class*='pod-title'],span[class*='pod-title'],a[class*='pod-title']")
                    price_el = card.select_one("span[class*='copy10'],li[class*='prices-0'],span[class*='price']")
                    if not title_el or not price_el:
                        continue
                    title  = title_el.get_text(strip=True)
                    price  = _parse_price_str(price_el.get_text(strip=True)) or 0.0   # FIX-7
                    if price > 0 and title:
                        items.append({
                            "batch_id": batch_id, "source": "falabella",
                            "category": category, "title": title[:200],
                            "price_pen": price, "price_orig_pen": 0.0,   # FIX-9
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
# ══════════════════════════════════════════════════════════════════════════
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
                if items:
                    return items
        except Exception as e:
            log.debug(f"    Ripley API error: {e}")
        return self._fetch_html(query, page, category, batch_id)

    def _parse_api(self, data, category, batch_id):
        items    = []
        ts       = datetime.now(timezone.utc).isoformat()
        products = data.get("results") or data.get("products") or data.get("items") or []

        # FIX-6: find_list() valida que los dicts tengan campos de producto
        if not isinstance(products, list):
            def find_list(obj, depth=0):
                if depth > 5:
                    return []
                if isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
                    # FIX-6: verificar que sea lista de productos, no de categorías
                    if any(k in obj[0] for k in ["displayName", "name", "price", "prices"]):
                        return obj
                if isinstance(obj, dict):
                    for v in obj.values():
                        r = find_list(v, depth + 1)
                        if r:
                            return r
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
                    for key in ["offerPrice", "salePrice", "normalPrice", "price"]:
                        val = prices.get(key)
                        if val:
                            parsed = _parse_price_str(str(val))   # FIX-7
                            if parsed:
                                price_pen = parsed
                                break
                    for key in ["normalPrice", "originalPrice", "regularPrice"]:
                        val = prices.get(key)
                        if val:
                            parsed = _parse_price_str(str(val))   # FIX-7
                            if parsed:
                                price_orig = parsed
                                break
                elif isinstance(prices, list):
                    for pr in prices:
                        val    = pr.get("price") or pr.get("value") or 0
                        parsed = _parse_price_str(str(val))   # FIX-7
                        if parsed:
                            price_pen = parsed
                            break

                if price_pen == 0:
                    for key in ["offerPrice", "salePrice", "price", "normalPrice"]:
                        val = p.get(key)
                        if val:
                            parsed = _parse_price_str(str(val))   # FIX-7
                            if parsed:
                                price_pen = parsed
                                break

                discount = 0.0
                if price_orig > price_pen > 0:
                    discount = round((price_orig - price_pen) / price_orig * 100, 1)

                url_path  = p.get("url") or p.get("pdpUrl") or ""
                url       = (f"https://simple.ripley.com.pe{url_path}"
                             if url_path and not url_path.startswith("http") else url_path)
                rating    = float(p.get("rating") or p.get("averageRating") or 0)
                available = bool(p.get("available") or p.get("isAvailable") or p.get("stock"))

                if price_pen > 0 and title:
                    items.append({
                        "batch_id":      batch_id,
                        "source":        "ripley",
                        "category":      category,
                        "title":         str(title)[:200],
                        "price_pen":     round(price_pen, 2),
                        "price_orig_pen": round(price_orig, 2),   # FIX-9
                        "discount_pct":  discount,
                        "url":           str(url)[:300],
                        "brand":         str(brand)[:100],
                        "available":     available,
                        "rating":        rating,
                        "timestamp":     ts,
                    })
            except Exception as e:
                log.debug(f"    parse Ripley error: {e}")
        return items

    def _fetch_html(self, query, page, category, batch_id):
        try:
            url  = f"https://simple.ripley.com.pe/search?q={requests.utils.quote(query)}&page={page}"
            resp = requests.get(url, headers=_headers("https://simple.ripley.com.pe/"), timeout=20)
            if resp.status_code != 200:
                return []
            soup  = BeautifulSoup(resp.text, "html.parser")
            items = []
            ts    = datetime.now(timezone.utc).isoformat()
            for card in soup.select("div[class*='catalog-product'],div[class*='ProductCard']"):
                try:
                    title_el = card.select_one("div[class*='product-title'],span[class*='title']")
                    price_el = card.select_one("li[class*='price-sale'],span[class*='price']")
                    link_el  = card.select_one("a[href]")
                    if not title_el or not price_el:
                        continue
                    title    = title_el.get_text(strip=True)
                    price    = _parse_price_str(price_el.get_text(strip=True)) or 0.0   # FIX-7
                    href     = link_el.get("href", "") if link_el else ""
                    full_url = (f"https://simple.ripley.com.pe{href}"
                                if href and not href.startswith("http") else href)
                    if price > 0 and title:
                        items.append({
                            "batch_id": batch_id, "source": "ripley",
                            "category": category, "title": title[:200],
                            "price_pen": price, "price_orig_pen": 0.0,   # FIX-9
                            "discount_pct": 0.0, "url": full_url[:300],
                            "brand": "", "available": True,
                            "rating": 0.0, "timestamp": ts,
                        })
                except Exception:
                    continue
            return items
        except Exception as e:
            log.error(f"    Ripley HTML error: {e}")
            return []


# ══════════════════════════════════════════════════════════════════════════
# SCRAPER 3 — HIRAOKA PE
# ══════════════════════════════════════════════════════════════════════════
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
            for page in range(1, max_pages + 1):
                log.info(f"  [Hiraoka] {category} | categoría directa | pág {page}")
                page_items = self._fetch_category(cat_path, page, category, batch_id)
                items.extend(page_items)
                log.info(f"    → {len(page_items)} items (total: {len(items)})")
                if not page_items:
                    break
                time.sleep(DELAY_REQ)
        else:
            for page in range(1, min(max_pages, 10) + 1):
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

    def _fetch_search(self, query, page, category, batch_id):
        try:
            url  = f"{self.BASE}/catalogsearch/result/?q={requests.utils.quote(query)}&p={page}"
            resp = requests.get(url, headers=_headers(self.BASE + "/"), timeout=25)
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
        for sel in ["li.product-item", "div.product-item-info",
                    "div[class*='product-item']", "li[class*='item product']"]:
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
                    card.select_one("span[class*='product-name']")
                )
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title:
                    continue

                # FIX-7: usar _parse_price_str() en lugar de re.sub directo
                price_pen  = 0.0
                price_orig = 0.0

                final_el = (
                    card.select_one("span[data-price-type='finalPrice'] span.price") or
                    card.select_one("span[class*='price-final'] span.price") or
                    card.select_one("span.special-price span.price") or
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

                link_el  = card.select_one("a.product-item-link") or card.select_one("a[href*='hiraoka']")
                item_url = link_el.get("href", "") if link_el else ""
                if item_url and not item_url.startswith("http"):
                    item_url = self.BASE + item_url

                brand_el = (
                    card.select_one("div.product-item-brand") or
                    card.select_one("span[class*='brand']") or
                    card.select_one("div[class*='brand']")
                )
                brand = brand_el.get_text(strip=True) if brand_el else ""

                stock_el  = card.select_one("div.stock") or card.select_one("span[class*='stock']")
                available = True
                if stock_el:
                    available = "unavailable" not in stock_el.get("class", [])

                rating_el = card.select_one("span.rating-result") or card.select_one("div[class*='rating']")
                rating    = 0.0
                if rating_el:
                    style = rating_el.get("style", "")
                    m     = re.search(r"width:\s*([\d.]+)%", style)
                    if m:
                        rating = round(float(m.group(1)) / 20, 1)

                items.append({
                    "batch_id":      batch_id,
                    "source":        "hiraoka",
                    "category":      category,
                    "title":         title[:200],
                    "price_pen":     round(price_pen, 2),
                    "price_orig_pen": round(price_orig, 2),   # FIX-9
                    "discount_pct":  discount,
                    "url":           item_url[:300],
                    "brand":         brand[:100],
                    "available":     available,
                    "rating":        rating,
                    "timestamp":     ts,
                })
            except Exception as e:
                log.debug(f"    parse Hiraoka card error: {e}")
                continue

        return items


# ══════════════════════════════════════════════════════════════════════════
# DEDUPLICACIÓN EN MEMORIA
# ══════════════════════════════════════════════════════════════════════════

def _dedup(records: list) -> list:
    """Elimina duplicados por fingerprint MD5 (source|title|price)."""
    seen = set()
    out  = []
    for r in records:
        key = f"{r.get('source')}|{r.get('title','')[:60]}|{r.get('price_pen',0)}"
        fp  = hashlib.md5(key.encode()).hexdigest()[:12]
        if fp not in seen and float(r.get("price_pen", 0)) > 0:
            seen.add(fp)
            out.append(r)
    return out


# ══════════════════════════════════════════════════════════════════════════
# FIX-1 + FIX-2: scrape_competencia() — interfaz pública compatible con main.py
# ══════════════════════════════════════════════════════════════════════════

def scrape_competencia(
    batch_id: str,
    sources: list = None,
    categories: list = None,
) -> list:
    """
    Scraper de precios de competencia PE.
    FIX-1: Nombre correcto para main.py y __init__.py
    FIX-2: Retorna list[dict] — compatible con save_batch() de main.py
    """
    if sources is None:
        sources = ["falabella", "ripley", "hiraoka"]
    if categories is None:
        categories = list(CATEGORY_QUERIES_PE.keys())

    scrapers = {}
    if "falabella" in sources: scrapers["falabella"] = FalabellaScraper()
    # [FIX-4] Ripley DESHABILITADO — 403 Cloudflare
    if "ripley" in sources:
        log.warning("[Ripley] DESHABILITADO — 403 Cloudflare, omitido del scraping")
        # scrapers["ripley"] = RipleyScraper()
    if "hiraoka"   in sources: scrapers["hiraoka"]   = HiraokaScraper()

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

    # FIX-8: Deduplicar y excluir fingerprint del retorno
    unique_records = _dedup(all_records)

    log.info(f"\n[Competencia] TOTAL: {len(unique_records):,} registros únicos "
             f"(de {len(all_records):,} brutos)")
    return unique_records


# Alias para compatibilidad con código legacy que use run_competencia()
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
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    results  = scrape_competencia(batch_id)
    print(f"\nTotal: {len(results)} registros")
    if results:
        print("Ejemplo:", results[0])
