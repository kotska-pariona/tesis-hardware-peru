#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agente Autonomo de Scraping - ML Peru Hardware
Tesis: Sistema Hibrido DL + Computacion Evolutiva
Autor: Kotska Rony Pariona Martinez - UNI 2026
Version: v3.0 - API Oficial MercadoLibre + Falabella JSON + Hiraoka mejorado
"""

import os, sys, re, json, csv, time, random, logging, hashlib, argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

import requests
from fake_useragent import UserAgent

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

# ════════════════════════════════════════════════════════════════
# 1. RUTAS
# ════════════════════════════════════════════════════════════════
BASE_DIR   = Path(__file__).parent.parent
DATA_DIR   = BASE_DIR / "data" / "raw"
LOG_DIR    = BASE_DIR / "logs"
MASTER_CSV = DATA_DIR / "MASTER_hardware_peru.csv"
STATE_FILE = DATA_DIR / ".agent_state.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

SCHEMA = [
    "batch_id", "scraped_at", "source",
    "item_id", "category", "title",
    "price_pen", "original_price", "discount_pct",
    "seller", "brand", "condition",
    "sold_quantity", "available_qty",
    "rating", "reviews_count",
    "url", "fingerprint"
]

# ════════════════════════════════════════════════════════════════
# 2. CONFIGURACION DE CATEGORIAS
#    ml_query   : termino de busqueda para API MercadoLibre
#    ml_cat_id  : ID de categoria ML Peru (opcional, mejora precision)
#    falabella_q: termino para Falabella
#    hiraoka_q  : termino para Hiraoka
# ════════════════════════════════════════════════════════════════
CATEGORIES = {
    "CPU": {
        "ml_query"   : "procesador cpu amd intel",
        "ml_cat_id"  : "MPE1700",   # Procesadores
        "falabella_q": "procesador cpu",
        "hiraoka_q"  : "procesador",
        "keywords"   : ["ryzen","intel","core","procesador","cpu","ghz","amd"],
        "exclude"    : ["pasta","soporte","cooler","ventilador","disipador","limpiador"],
    },
    "GPU": {
        "ml_query"   : "tarjeta de video gpu nvidia amd",
        "ml_cat_id"  : "MPE1658",   # Tarjetas de Video
        "falabella_q": "tarjeta de video gpu",
        "hiraoka_q"  : "tarjeta video",
        "keywords"   : ["rtx","rx","gtx","radeon","geforce","nvidia","amd","gddr","vram"],
        "exclude"    : ["soporte","cable","adaptador","limpiador","funda"],
    },
    "RAM": {
        "ml_query"   : "memoria ram ddr4 ddr5",
        "ml_cat_id"  : "MPE1694",   # Memorias RAM
        "falabella_q": "memoria ram ddr",
        "hiraoka_q"  : "memoria ram",
        "keywords"   : ["ddr4","ddr5","ddr3","gb","mhz","memoria","ram"],
        "exclude"    : [],
    },
    "SSD": {
        "ml_query"   : "disco ssd nvme m.2",
        "ml_cat_id"  : "MPE1672",   # Discos SSD
        "falabella_q": "ssd nvme m.2",
        "hiraoka_q"  : "disco ssd nvme",
        "keywords"   : ["ssd","nvme","m.2","pcie","sata","tb","gb"],
        "exclude"    : ["externo","usb","case","gabinete"],
    },
    "MOTHERBOARD": {
        "ml_query"   : "placa madre motherboard am5 lga",
        "ml_cat_id"  : "MPE1692",   # Placas Madre
        "falabella_q": "placa madre motherboard",
        "hiraoka_q"  : "placa madre",
        "keywords"   : ["motherboard","placa","am5","am4","lga","atx","b650","z790"],
        "exclude"    : ["limpiador","soporte"],
    },
    "PSU": {
        "ml_query"   : "fuente de poder psu 650w 750w 850w",
        "ml_cat_id"  : "MPE1691",   # Fuentes de Poder
        "falabella_q": "fuente de poder psu",
        "hiraoka_q"  : "fuente poder",
        "keywords"   : ["watts","watt","80plus","modular","fuente","psu"],
        "exclude"    : ["cable","adaptador","ups","regleta"],
    },
    "COOLER": {
        "ml_query"   : "cooler disipador cpu refrigeracion liquida",
        "ml_cat_id"  : "MPE1659",   # Coolers
        "falabella_q": "cooler disipador cpu",
        "hiraoka_q"  : "cooler cpu",
        "keywords"   : ["cooler","disipador","aio","refrigeracion","fan","rgb"],
        "exclude"    : ["pasta","soporte"],
    },
    "CASE": {
        "ml_query"   : "gabinete pc gamer atx",
        "ml_cat_id"  : "MPE1661",   # Gabinetes
        "falabella_q": "gabinete pc gamer",
        "hiraoka_q"  : "gabinete pc",
        "keywords"   : ["gabinete","case","torre","atx","rgb","vidrio"],
        "exclude"    : [],
    },
}

# Tiempos de espera (segundos)
DELAY_REQ  = (1, 3)
DELAY_PAGE = (2, 5)
DELAY_CAT  = (5, 10)
MAX_PAGES  = 20
MAX_RETRY  = 3

# ════════════════════════════════════════════════════════════════
# 3. LOGGER
# ════════════════════════════════════════════════════════════════
def setup_logger(batch_id: str) -> logging.Logger:
    log_file = LOG_DIR / f"batch_{batch_id}.log"
    fmt      = "%(asctime)s [%(levelname)-8s] %(name)s - %(message)s"
    logger   = logging.getLogger(f"AgentIA.{batch_id}")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter(fmt))
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter(fmt))
        logger.addHandler(fh)
        logger.addHandler(sh)
        logger.propagate = False
    return logger

# ════════════════════════════════════════════════════════════════
# 4. DATACLASS
# ════════════════════════════════════════════════════════════════
@dataclass
class HardwareItem:
    batch_id       : str   = ""
    scraped_at     : str   = ""
    source         : str   = ""
    item_id        : str   = ""
    category       : str   = ""
    title          : str   = ""
    price_pen      : float = 0.0
    original_price : float = 0.0
    discount_pct   : float = 0.0
    seller         : str   = ""
    brand          : str   = ""
    condition      : str   = "new"
    sold_quantity  : int   = 0
    available_qty  : int   = 0
    rating         : float = 0.0
    reviews_count  : int   = 0
    url            : str   = ""
    fingerprint    : str   = ""

    def compute_fingerprint(self):
        raw = f"{self.source}|{self.item_id}|{self.title}|{self.price_pen}"
        self.fingerprint = hashlib.md5(raw.encode()).hexdigest()

    def is_valid(self) -> bool:
        return bool(self.title) and self.price_pen > 0

# ════════════════════════════════════════════════════════════════
# 5. HTTP CLIENT
# ════════════════════════════════════════════════════════════════
class HttpClient:
    UA_FALLBACKS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
    ]

    def __init__(self, logger):
        self.log = logger
        try:
            self._ua = UserAgent()
        except Exception:
            self._ua = None
        self.session = requests.Session()

    def _random_ua(self) -> str:
        if self._ua:
            try:
                return self._ua.random
            except Exception:
                pass
        return random.choice(self.UA_FALLBACKS)

    def _headers(self, referer: str = "", json_api: bool = False) -> dict:
        h = {
            "User-Agent"      : self._random_ua(),
            "Accept-Language" : "es-PE,es;q=0.9,en;q=0.7",
            "Accept-Encoding" : "gzip, deflate, br",
            "DNT"             : "1",
            "Connection"      : "keep-alive",
        }
        if json_api:
            h["Accept"] = "application/json"
        else:
            h["Accept"] = "text/html,application/xhtml+xml,*/*;q=0.9"
        if referer:
            h["Referer"] = referer
        return h

    def get(self, url: str, referer: str = "", params: dict = None,
            json_mode: bool = False) -> Optional[requests.Response]:
        for attempt in range(1, MAX_RETRY + 1):
            try:
                time.sleep(random.uniform(*DELAY_REQ))
                r = self.session.get(
                    url,
                    headers=self._headers(referer, json_api=json_mode),
                    params=params,
                    timeout=20,
                    allow_redirects=True
                )
                if r.status_code == 200:
                    return r
                elif r.status_code == 429:
                    wait = 60 * attempt
                    self.log.warning(f"Rate limit 429. Esperando {wait}s...")
                    time.sleep(wait)
                elif r.status_code in (403, 503):
                    self.log.warning(
                        f"HTTP {r.status_code} en {url[:70]}. Intento {attempt}/{MAX_RETRY}")
                    time.sleep(20 * attempt)
                else:
                    self.log.warning(f"HTTP {r.status_code} en {url[:70]}")
                    return None
            except requests.RequestException as e:
                self.log.error(f"Error conexion (intento {attempt}): {e}")
                time.sleep(10 * attempt)
        return None

# ════════════════════════════════════════════════════════════════
# 6. SCRAPER — MERCADOLIBRE (API OFICIAL v2)
#
#  Endpoint: https://api.mercadolibre.com/sites/MPE/search
#  Docs    : https://developers.mercadolibre.com.pe/
#  - No requiere token para busquedas publicas
#  - Devuelve JSON limpio con todos los campos necesarios
#  - Limite: 50 items por request, offset maximo 1000
# ════════════════════════════════════════════════════════════════
class MLScraper:
    API_BASE   = "https://api.mercadolibre.com/sites/MPE/search"
    ITEM_BASE  = "https://www.mercadolibre.com.pe"
    LIMIT      = 50   # maximo permitido por la API

    BRANDS = [
        "Intel","AMD","NVIDIA","Kingston","Samsung","Corsair","G.Skill",
        "Crucial","WD","Seagate","ASUS","MSI","Gigabyte","ASRock","EVGA",
        "Seasonic","be quiet","Noctua","Cooler Master","NZXT","Lian Li",
        "Fractal","Thermaltake","Deepcool","Arctic","PNY","XFX","Sapphire",
        "PowerColor","Zotac","Palit","Gainward","Netac","Lexar","TeamGroup",
        "Patriot","HyperX","Adata","Transcend","Toshiba","Hitachi",
    ]

    def __init__(self, http: HttpClient, logger):
        self.http = http
        self.log  = logger

    def _extract_brand(self, title: str, attributes: list = None) -> str:
        # Primero buscar en atributos de la API (mas preciso)
        if attributes:
            for attr in attributes:
                if attr.get("id") == "BRAND":
                    return attr.get("value_name", "")
        # Fallback: buscar en titulo
        t = title.lower()
        for b in self.BRANDS:
            if b.lower() in t:
                return b
        return ""

    def _is_relevant(self, title: str, cat_cfg: dict) -> bool:
        t = title.lower()
        return not any(ex in t for ex in cat_cfg.get("exclude", []))

    def scrape_category(self, category: str, cat_cfg: dict,
                        batch_id: str, max_pages: int = MAX_PAGES) -> list:
        items    = []
        query    = cat_cfg["ml_query"]
        cat_id   = cat_cfg.get("ml_cat_id", "")
        seen_ids = set()
        now_str  = datetime.now(timezone.utc).isoformat()
        max_items = max_pages * self.LIMIT

        self.log.info(f"[ML-API] Scrapeando {category} - hasta {max_pages} paginas")

        for page in range(max_pages):
            offset = page * self.LIMIT

            # La API tiene limite de offset=1000
            if offset >= 1000:
                break

            params = {
                "q"     : query,
                "limit" : self.LIMIT,
                "offset": offset,
            }
            # Agregar filtro de categoria si esta disponible
            if cat_id:
                params["category"] = cat_id

            resp = self.http.get(
                self.API_BASE,
                referer="https://www.mercadolibre.com.pe/",
                params=params,
                json_mode=True
            )

            if not resp:
                self.log.warning(f"[ML-API] Sin respuesta en pagina {page+1}")
                break

            try:
                data    = resp.json()
                results = data.get("results", [])
                paging  = data.get("paging", {})
                total   = paging.get("total", 0)
            except Exception as e:
                self.log.error(f"[ML-API] Error parseando JSON: {e}")
                break

            if not results:
                self.log.info(f"[ML-API] Sin mas resultados en offset {offset}")
                break

            page_count = 0
            for prod in results:
                try:
                    item_id = prod.get("id", "")
                    if not item_id or item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)

                    title = prod.get("title", "")
                    if not title or not self._is_relevant(title, cat_cfg):
                        continue

                    # Precios
                    price    = float(prod.get("price", 0) or 0)
                    orig_raw = prod.get("original_price")
                    original = float(orig_raw) if orig_raw else price
                    discount = round((1 - price / original) * 100, 1)                                if original > price > 0 else 0.0

                    # Vendedor
                    seller_info = prod.get("seller", {})
                    seller      = seller_info.get("nickname", "")

                    # Condicion
                    condition_raw = prod.get("condition", "new")
                    condition     = "new" if condition_raw == "new" else "used"

                    # Cantidad vendida
                    sold_qty = int(prod.get("sold_quantity", 0) or 0)

                    # Stock disponible
                    avail = int(prod.get("available_quantity", 0) or 0)

                    # URL del producto
                    url_item = prod.get("permalink", "")

                    # Atributos (marca, modelo, etc.)
                    attributes = prod.get("attributes", [])
                    brand      = self._extract_brand(title, attributes)

                    # Thumbnail (no se guarda pero util para debug)
                    # thumbnail = prod.get("thumbnail", "")

                    item = HardwareItem(
                        batch_id       = batch_id,
                        scraped_at     = now_str,
                        source         = "mercadolibre",
                        item_id        = item_id,
                        category       = category,
                        title          = title,
                        price_pen      = price,
                        original_price = original,
                        discount_pct   = discount,
                        seller         = seller,
                        brand          = brand,
                        condition      = condition,
                        sold_quantity  = sold_qty,
                        available_qty  = avail,
                        url            = url_item,
                    )
                    item.compute_fingerprint()
                    if item.is_valid():
                        items.append(item)
                        page_count += 1

                except Exception as e:
                    self.log.debug(f"[ML-API] Error item: {e}")
                    continue

            self.log.info(
                f"[ML-API] {category} pag {page+1}: {page_count} items "
                f"(total acum: {len(items)}, disponibles: {total})"
            )

            # Si ya obtuvimos todos los disponibles, parar
            if offset + self.LIMIT >= min(total, max_items):
                break

            time.sleep(random.uniform(*DELAY_PAGE))

        self.log.info(f"[ML-API] {category} TOTAL: {len(items)} items")
        return items

# ════════════════════════════════════════════════════════════════
# 7. SCRAPER — FALABELLA (API interna JSON)
# ════════════════════════════════════════════════════════════════
class FalabellaScraper:
    # Falabella expone una API interna que devuelve JSON directamente
    API_URL = "https://www.falabella.com.pe/s/browse/v1/listing/pe"

    def __init__(self, http: HttpClient, logger):
        self.http = http
        self.log  = logger

    def scrape_category(self, category: str, cat_cfg: dict,
                        batch_id: str, max_pages: int = 5) -> list:
        items    = []
        query    = cat_cfg.get("falabella_q", category)
        now_str  = datetime.now(timezone.utc).isoformat()
        seen_ids = set()

        self.log.info(f"[Falabella] Scrapeando {category}")

        for page in range(1, max_pages + 1):
            params = {
                "categoryId"  : "cat10001",
                "page"        : page,
                "ruleContext" : "ELECTRONICS",
                "zones"       : "15",
                "query"       : query,
            }

            resp = self.http.get(
                self.API_URL,
                referer="https://www.falabella.com.pe/",
                params=params,
                json_mode=True
            )

            if not resp:
                self.log.info(f"[Falabella] Sin respuesta pag {page}, intentando URL alternativa")
                # Fallback: URL de busqueda estandar
                items.extend(self._scrape_html(category, cat_cfg, batch_id,
                                               max_pages=min(3, max_pages)))
                break

            try:
                data     = resp.json()
                products = (data.get("data", {})
                               .get("results", [{}])[0]
                               .get("products", []))
                if not products:
                    self.log.info(f"[Falabella] Sin productos en pag {page}")
                    break
            except Exception as e:
                self.log.debug(f"[Falabella] Error JSON API: {e}")
                items.extend(self._scrape_html(category, cat_cfg, batch_id,
                                               max_pages=min(3, max_pages)))
                break

            page_count = 0
            for prod in products:
                try:
                    title = prod.get("displayName", "")
                    if not title:
                        continue

                    # Precios
                    prices   = prod.get("prices", [])
                    price    = 0.0
                    original = 0.0
                    for p in prices:
                        label = p.get("label", "").lower()
                        val   = float(p.get("price", [0])[0] or 0)
                        if "oferta" in label or "internet" in label:
                            price = val
                        elif "normal" in label or "original" in label:
                            original = val
                    if price == 0.0 and prices:
                        price = float(prices[0].get("price", [0])[0] or 0)
                    if original == 0.0:
                        original = price
                    discount = round((1 - price / original) * 100, 1)                                if original > price > 0 else 0.0

                    brand   = prod.get("brand", "")
                    sku     = prod.get("skuId", hashlib.md5(title.encode()).hexdigest()[:12])
                    item_id = f"FAL_{sku}"
                    if item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)

                    slug    = prod.get("slug", "")
                    url_i   = f"https://www.falabella.com.pe/falabella-pe/product/{sku}/{slug}"
                    rating  = float(prod.get("rating", {}).get("average", 0) or 0)
                    reviews = int(prod.get("rating", {}).get("count", 0) or 0)

                    item = HardwareItem(
                        batch_id       = batch_id,
                        scraped_at     = now_str,
                        source         = "falabella",
                        item_id        = item_id,
                        category       = category,
                        title          = title,
                        price_pen      = price,
                        original_price = original,
                        discount_pct   = discount,
                        brand          = brand,
                        rating         = rating,
                        reviews_count  = reviews,
                        url            = url_i,
                    )
                    item.compute_fingerprint()
                    if item.is_valid():
                        items.append(item)
                        page_count += 1

                except Exception as e:
                    self.log.debug(f"[Falabella] Error producto: {e}")
                    continue

            self.log.info(f"[Falabella] {category} pag {page}: {page_count} nuevos (total: {len(items)})")
            time.sleep(random.uniform(*DELAY_PAGE))

        return items

    def _scrape_html(self, category: str, cat_cfg: dict,
                     batch_id: str, max_pages: int = 3) -> list:
        """Fallback HTML para Falabella si la API falla."""
        items    = []
        query    = cat_cfg.get("falabella_q", category)
        now_str  = datetime.now(timezone.utc).isoformat()
        seen_ids = set()
        base_url = "https://www.falabella.com.pe/falabella-pe/search"

        for page in range(1, max_pages + 1):
            url  = f"{base_url}?Ntt={requests.utils.quote(query)}&page={page}"
            resp = self.http.get(url, referer="https://www.falabella.com.pe/")
            if not resp:
                break

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "lxml")

            # Intentar __NEXT_DATA__
            for script in soup.find_all("script", {"id": "__NEXT_DATA__"}):
                try:
                    data    = json.loads(script.string)
                    results = (data.get("props", {})
                                   .get("pageProps", {})
                                   .get("searchResults", {})
                                   .get("products", []))
                    for prod in results:
                        title  = prod.get("displayName", "")
                        prices = prod.get("prices", [{}])
                        price  = float(prices[0].get("originalPrice", 0) or 0)
                        orig   = float(prices[0].get("normalPrice", price) or price)
                        disc   = round((1 - price/orig)*100, 1) if orig > price > 0 else 0.0
                        brand  = prod.get("brand", "")
                        sku    = prod.get("skuId", hashlib.md5(title.encode()).hexdigest()[:12])
                        item_id = f"FAL_{sku}"
                        if item_id in seen_ids or not title or price <= 0:
                            continue
                        seen_ids.add(item_id)
                        slug  = prod.get("slug", "")
                        url_i = f"https://www.falabella.com.pe/falabella-pe/product/{sku}/{slug}"
                        item  = HardwareItem(
                            batch_id=batch_id, scraped_at=now_str, source="falabella",
                            item_id=item_id, category=category, title=title,
                            price_pen=price, original_price=orig, discount_pct=disc,
                            brand=brand, url=url_i,
                        )
                        item.compute_fingerprint()
                        if item.is_valid():
                            items.append(item)
                except Exception:
                    pass
            time.sleep(random.uniform(*DELAY_PAGE))

        return items

# ════════════════════════════════════════════════════════════════
# 8. SCRAPER — HIRAOKA (API GraphQL / JSON)
# ════════════════════════════════════════════════════════════════
class HiraokaScraper:
    # Hiraoka usa Magento 2 con endpoints de busqueda accesibles
    SEARCH_URL = "https://www.hiraoka.com.pe/catalogsearch/result/index/"
    API_URL    = "https://www.hiraoka.com.pe/graphql"

    def __init__(self, http: HttpClient, logger):
        self.http = http
        self.log  = logger

    def scrape_category(self, category: str, cat_cfg: dict,
                        batch_id: str, max_pages: int = 5) -> list:
        items   = []
        query   = cat_cfg.get("hiraoka_q", category)
        now_str = datetime.now(timezone.utc).isoformat()

        self.log.info(f"[Hiraoka] Scrapeando {category}")

        # Intentar GraphQL primero
        gql_items = self._scrape_graphql(category, query, batch_id, now_str, max_pages)
        if gql_items:
            self.log.info(f"[Hiraoka] GraphQL exitoso: {len(gql_items)} items")
            return gql_items

        # Fallback: HTML con ld+json
        for page in range(1, max_pages + 1):
            url  = f"{self.SEARCH_URL}?q={requests.utils.quote(query)}&p={page}"
            resp = self.http.get(url, referer="https://www.hiraoka.com.pe/")
            if not resp:
                break

            from bs4 import BeautifulSoup
            soup       = BeautifulSoup(resp.text, "lxml")
            page_items = self._parse_ldjson(soup, category, batch_id, now_str)

            if not page_items:
                page_items = self._parse_html_cards(soup, category, batch_id, now_str)

            items.extend(page_items)
            self.log.info(f"[Hiraoka] {category} pag {page}: {len(page_items)} items (total: {len(items)})")

            if not page_items:
                break
            time.sleep(random.uniform(*DELAY_PAGE))

        return items

    def _scrape_graphql(self, category: str, query: str,
                        batch_id: str, now_str: str, max_pages: int) -> list:
        """Consulta GraphQL de Magento 2 (Hiraoka)."""
        items    = []
        seen_ids = set()
        page_size = 20

        gql_query = """
        query SearchProducts($search: String!, $pageSize: Int!, $currentPage: Int!) {
          products(search: $search, pageSize: $pageSize, currentPage: $currentPage) {
            total_count
            items {
              sku
              name
              url_key
              price_range {
                minimum_price {
                  regular_price { value currency }
                  final_price   { value currency }
                  discount      { amount_off percent_off }
                }
              }
              ... on PhysicalProductInterface {
                weight
              }
            }
          }
        }
        """

        for page in range(1, max_pages + 1):
            try:
                payload = {
                    "query"    : gql_query,
                    "variables": {
                        "search"     : query,
                        "pageSize"   : page_size,
                        "currentPage": page,
                    }
                }
                time.sleep(random.uniform(*DELAY_REQ))
                resp = self.http.session.post(
                    self.API_URL,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept"      : "application/json",
                        "Referer"     : "https://www.hiraoka.com.pe/",
                        "User-Agent"  : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0",
                    },
                    timeout=20
                )
                if not resp or resp.status_code != 200:
                    break

                data     = resp.json()
                products = data.get("data", {}).get("products", {}).get("items", [])
                if not products:
                    break

                for prod in products:
                    try:
                        sku     = prod.get("sku", "")
                        title   = prod.get("name", "")
                        url_key = prod.get("url_key", "")
                        url_i   = f"https://www.hiraoka.com.pe/{url_key}.html"

                        price_range = prod.get("price_range", {})
                        min_price   = price_range.get("minimum_price", {})
                        final       = min_price.get("final_price", {})
                        regular     = min_price.get("regular_price", {})
                        discount_d  = min_price.get("discount", {})

                        price    = float(final.get("value", 0) or 0)
                        original = float(regular.get("value", 0) or price)
                        discount = float(discount_d.get("percent_off", 0) or 0)

                        item_id = f"HIR_{sku}"
                        if item_id in seen_ids or not title or price <= 0:
                            continue
                        seen_ids.add(item_id)

                        item = HardwareItem(
                            batch_id       = batch_id,
                            scraped_at     = now_str,
                            source         = "hiraoka",
                            item_id        = item_id,
                            category       = category,
                            title          = title,
                            price_pen      = price,
                            original_price = original,
                            discount_pct   = round(discount, 1),
                            url            = url_i,
                        )
                        item.compute_fingerprint()
                        if item.is_valid():
                            items.append(item)
                    except Exception:
                        continue

                total = data.get("data", {}).get("products", {}).get("total_count", 0)
                if page * page_size >= total:
                    break
                time.sleep(random.uniform(*DELAY_PAGE))

            except Exception as e:
                self.log.debug(f"[Hiraoka] GraphQL error: {e}")
                break

        return items

    def _parse_ldjson(self, soup, category: str, batch_id: str, now_str: str) -> list:
        """Parsear ld+json Schema.org/Product."""
        items = []
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, list):
                    products = data
                elif data.get("@type") == "ItemList":
                    products = [e.get("item", {}) for e in data.get("itemListElement", [])]
                else:
                    products = [data]

                for prod in products:
                    if prod.get("@type") not in ("Product", "product"):
                        continue
                    title  = prod.get("name", "")
                    offers = prod.get("offers", {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    price  = float(offers.get("price", 0) or 0)
                    brand  = prod.get("brand", {})
                    brand  = brand.get("name", "") if isinstance(brand, dict) else str(brand)
                    url_i  = prod.get("url", "")
                    sku    = prod.get("sku", hashlib.md5(title.encode()).hexdigest()[:12])
                    if not title or price <= 0:
                        continue
                    item = HardwareItem(
                        batch_id=batch_id, scraped_at=now_str, source="hiraoka",
                        item_id=f"HIR_{sku}", category=category, title=title,
                        price_pen=price, original_price=price, brand=brand, url=url_i,
                    )
                    item.compute_fingerprint()
                    if item.is_valid():
                        items.append(item)
            except Exception:
                continue
        return items

    def _parse_html_cards(self, soup, category: str, batch_id: str, now_str: str) -> list:
        """Fallback HTML cards Magento 2."""
        items = []
        for card in soup.select(".product-item-info"):
            try:
                from bs4 import BeautifulSoup
                title_el = card.select_one(".product-item-name")
                price_el = card.select_one(".price")
                if not title_el or not price_el:
                    continue
                title     = title_el.get_text(strip=True)
                price_str = re.sub(r"[^\d]", "", price_el.get_text())
                price     = float(price_str) if price_str else 0.0
                link_el   = card.select_one("a.product-item-link")
                url_i     = link_el["href"] if link_el else ""
                sku       = hashlib.md5(title.encode()).hexdigest()[:12]
                item = HardwareItem(
                    batch_id=batch_id, scraped_at=now_str, source="hiraoka",
                    item_id=f"HIR_{sku}", category=category, title=title,
                    price_pen=price, original_price=price, url=url_i,
                )
                item.compute_fingerprint()
                if item.is_valid():
                    items.append(item)
            except Exception:
                continue
        return items

# ════════════════════════════════════════════════════════════════
# 9. DATA CLEANER
# ════════════════════════════════════════════════════════════════
class DataCleaner:
    PRICE_LIMITS = {
        "CPU"        : (100,   25_000),
        "GPU"        : (200,   80_000),
        "RAM"        : (50,    20_000),
        "SSD"        : (50,    15_000),
        "MOTHERBOARD": (150,   30_000),
        "PSU"        : (80,    10_000),
        "COOLER"     : (30,    5_000),
        "CASE"       : (80,    8_000),
    }

    def clean(self, items: list) -> list:
        seen_fps = set()
        clean    = []
        for item in items:
            if item.fingerprint in seen_fps:
                continue
            seen_fps.add(item.fingerprint)
            lo, hi = self.PRICE_LIMITS.get(item.category, (1, 999_999))
            if not (lo <= item.price_pen <= hi):
                continue
            item.title = re.sub(r"\s+", " ", item.title).strip()
            clean.append(item)
        return clean

# ════════════════════════════════════════════════════════════════
# 10. CSV WRITER
# ════════════════════════════════════════════════════════════════
class MasterCSVWriter:
    def __init__(self, master_path: Path, logger):
        self.path = master_path
        self.log  = logger

    def write_batch(self, items: list, batch_id: str) -> Path:
        batch_path = DATA_DIR / f"batch_{batch_id}.csv"
        self._write_csv(batch_path, items, write_header=True)
        self.log.info(f"Batch guardado: {batch_path} ({len(items)} items)")

        header_needed = not self.path.exists()
        self._write_csv(self.path, items, write_header=header_needed, mode="a")
        self.log.info(f"Master actualizado: {self.path}")

        return batch_path

    def _write_csv(self, path: Path, items: list,
                   write_header: bool = True, mode: str = "w"):
        with open(path, mode, newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=SCHEMA)
            if write_header:
                writer.writeheader()
            for item in items:
                writer.writerow(asdict(item))

    def master_stats(self) -> dict:
        if not self.path.exists():
            return {"status": "no_data", "path": str(self.path)}
        try:
            import pandas as pd
            df = pd.read_csv(self.path)
            date_min = df["scraped_at"].dropna().min()
            date_max = df["scraped_at"].dropna().max()
            return {
                "total_records" : len(df),
                "unique_items"  : df["item_id"].nunique(),
                "categories"    : df["category"].value_counts().to_dict(),
                "sources"       : df["source"].value_counts().to_dict(),
                "batches"       : df["batch_id"].nunique(),
                "date_range"    : f"{str(date_min)[:10]} - {str(date_max)[:10]}",
            }
        except Exception as e:
            return {"error": str(e)}

# ════════════════════════════════════════════════════════════════
# 11. BATCH ORCHESTRATOR
# ════════════════════════════════════════════════════════════════
class BatchOrchestrator:
    def __init__(self):
        self.batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log      = setup_logger(self.batch_id)
        self.http     = HttpClient(self.log)
        self.cleaner  = DataCleaner()
        self.writer   = MasterCSVWriter(MASTER_CSV, self.log)
        self.scrapers = {
            "mercadolibre": MLScraper(self.http, self.log),
            "falabella"   : FalabellaScraper(self.http, self.log),
            "hiraoka"     : HiraokaScraper(self.http, self.log),
        }

    def run_batch(self, categories: list = None, sources: list = None,
                  max_pages: int = MAX_PAGES) -> dict:
        cats      = categories or list(CATEGORIES.keys())
        srcs      = sources    or list(self.scrapers.keys())
        all_items = []

        self.log.info("=" * 70)
        self.log.info(f"BATCH {self.batch_id} INICIADO")
        self.log.info(f"Categorias : {cats}")
        self.log.info(f"Fuentes    : {srcs}")
        self.log.info(f"Max paginas: {max_pages}")
        self.log.info("=" * 70)

        t_start = time.time()

        for cat_name in cats:
            cat_cfg   = CATEGORIES[cat_name]
            cat_items = []

            for src_name in srcs:
                scraper = self.scrapers.get(src_name)
                if not scraper:
                    continue
                try:
                    raw = scraper.scrape_category(
                        cat_name, cat_cfg, self.batch_id, max_pages)
                    cat_items.extend(raw)
                    self.log.info(f"  OK {src_name:15} -> {len(raw):4d} items brutos")
                except Exception as e:
                    self.log.error(f"  ERROR {src_name}: {e}")

            clean = self.cleaner.clean(cat_items)
            all_items.extend(clean)
            self.log.info(
                f"[{cat_name}] Brutos: {len(cat_items)} -> Limpios: {len(clean)}")
            time.sleep(random.uniform(*DELAY_CAT))

        batch_path = self.writer.write_batch(all_items, self.batch_id)
        elapsed    = round(time.time() - t_start, 1)
        stats      = self.writer.master_stats()

        self.log.info("=" * 70)
        self.log.info(f"BATCH {self.batch_id} COMPLETADO en {elapsed}s")
        self.log.info(f"Items este batch : {len(all_items)}")
        self.log.info(f"Master total     : {stats.get('total_records', '?')} registros")
        self.log.info(f"Archivo batch    : {batch_path}")
        self.log.info("=" * 70)

        self._save_state(len(all_items), elapsed, stats)

        return {
            "batch_id"    : self.batch_id,
            "items"       : len(all_items),
            "elapsed_s"   : elapsed,
            "batch_file"  : str(batch_path),
            "master_stats": stats,
        }

    def _save_state(self, items: int, elapsed: float, stats: dict):
        state = {
            "last_batch"     : self.batch_id,
            "last_run"       : datetime.now().isoformat(),
            "last_items"     : items,
            "last_elapsed_s" : elapsed,
            "master_stats"   : stats,
        }
        STATE_FILE.write_text(
            json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

# ════════════════════════════════════════════════════════════════
# 12. ENTRY POINT
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Agente IA - Scraper ML Peru Hardware v3.0")
    parser.add_argument("--once",       action="store_true", help="Un batch y salir")
    parser.add_argument("--pages",      type=int, default=MAX_PAGES)
    parser.add_argument("--categories", nargs="+", default=None,
                        choices=list(CATEGORIES.keys()))
    parser.add_argument("--sources",    nargs="+", default=None,
                        choices=["mercadolibre","falabella","hiraoka"])
    parser.add_argument("--stats",      action="store_true", help="Ver estadisticas")
    args = parser.parse_args()

    if args.stats:
        writer = MasterCSVWriter(MASTER_CSV, logging.getLogger())
        print(json.dumps(writer.master_stats(), indent=2, ensure_ascii=False))
        sys.exit(0)

    orch   = BatchOrchestrator()
    result = orch.run_batch(
        categories=args.categories,
        sources=args.sources,
        max_pages=max(1, args.pages)
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
