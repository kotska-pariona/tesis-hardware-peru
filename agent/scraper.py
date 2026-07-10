#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  AGENTE AUTÓNOMO DE SCRAPING — ML PERÚ HARDWARE                            ║
║  Tesis: Sistema Híbrido DL + Computación Evolutiva                         ║
║  Autor: Kotska Rony Pariona Martinez                                        ║
║  Versión: C6 v2.0 — Agente IA + Batch 24h + Multi-fuente                  ║
║                                                                              ║
║  FUENTES:                                                                    ║
║    1. MercadoLibre Perú  (HTML scraping — sin token)                        ║
║    2. Falabella Perú     (JSON embed)                                        ║
║    3. Ripley Perú        (API pública)                                       ║
║    4. Hiraoka Perú       (ld+json)                                           ║
║                                                                              ║
║  ARQUITECTURA DEL AGENTE:                                                    ║
║    ┌─────────────────────────────────────────────────────┐                  ║
║    │  Scheduler (APScheduler / schedule)                 │                  ║
║    │    └── cada 24h → BatchOrchestrator                 │                  ║
║    │          ├── ScraperAgent (ML + Falabella + Ripley) │                  ║
║    │          ├── DataCleaner                            │                  ║
║    │          ├── MasterCSVWriter                        │                  ║
║    │          └── ReportGenerator                        │                  ║
║    └─────────────────────────────────────────────────────┘                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ══════════════════════════════════════════════════════════════════════════════
# 0. IMPORTS
# ══════════════════════════════════════════════════════════════════════════════
import os, sys, re, json, csv, time, random, logging, hashlib, argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    import schedule
    HAS_SCHEDULE = True
except ImportError:
    HAS_SCHEDULE = False

# ══════════════════════════════════════════════════════════════════════════════
# 1. CONFIGURACIÓN GLOBAL
# ══════════════════════════════════════════════════════════════════════════════
BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "ml_data"
LOG_DIR     = BASE_DIR / "ml_logs"
MASTER_CSV  = DATA_DIR / "MASTER_hardware_peru.csv"
STATE_FILE  = DATA_DIR / ".agent_state.json"

DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

SCHEMA = [
    "batch_id", "scraped_at", "source",
    "item_id", "category", "title",
    "price_pen", "original_price", "discount_pct",
    "seller", "brand", "condition",
    "sold_quantity", "available_qty",
    "rating", "reviews_count",
    "url", "fingerprint"
]

# Categorías con URLs de todas las fuentes
CATEGORIES = {
    "CPU": {
        "ml_url"      : "https://listado.mercadolibre.com.pe/procesadores",
        "falabella_q" : "procesador cpu",
        "ripley_q"    : "procesador",
        "keywords"    : ["ryzen","intel","core","procesador","cpu","ghz","nucleos","amd"],
        "exclude"     : ["pasta","soporte","cooler","ventilador","disipador","limpiador"],
    },
    "GPU": {
        "ml_url"      : "https://listado.mercadolibre.com.pe/tarjetas-de-video",
        "falabella_q" : "tarjeta de video gpu",
        "ripley_q"    : "tarjeta video",
        "keywords"    : ["rtx","rx","gtx","radeon","geforce","nvidia","amd","gddr","vram"],
        "exclude"     : ["soporte","cable","adaptador","limpiador","funda"],
    },
    "RAM": {
        "ml_url"      : "https://listado.mercadolibre.com.pe/memorias-ram",
        "falabella_q" : "memoria ram ddr",
        "ripley_q"    : "memoria ram",
        "keywords"    : ["ddr4","ddr5","ddr3","gb","mhz","memoria","ram","kingston","corsair"],
        "exclude"     : [],
    },
    "SSD": {
        "ml_url"      : "https://listado.mercadolibre.com.pe/discos-solidos-ssd",
        "falabella_q" : "ssd nvme m.2",
        "ripley_q"    : "disco ssd",
        "keywords"    : ["ssd","nvme","m.2","pcie","sata","tb","gb","kingston","samsung","wd"],
        "exclude"     : ["externo","usb","case","gabinete"],
    },
    "MOTHERBOARD": {
        "ml_url"      : "https://listado.mercadolibre.com.pe/placas-madre",
        "falabella_q" : "placa madre motherboard",
        "ripley_q"    : "placa madre",
        "keywords"    : ["motherboard","placa","am5","am4","lga","atx","b650","z790","x670","b760"],
        "exclude"     : ["limpiador","soporte"],
    },
    "PSU": {
        "ml_url"      : "https://listado.mercadolibre.com.pe/fuentes-de-poder",
        "falabella_q" : "fuente de poder psu",
        "ripley_q"    : "fuente poder",
        "keywords"    : ["watts","watt","80plus","modular","fuente","psu","corsair","evga","seasonic"],
        "exclude"     : ["cable","adaptador","ups","regleta"],
    },
    "COOLER": {
        "ml_url"      : "https://listado.mercadolibre.com.pe/coolers-disipadores",
        "falabella_q" : "cooler disipador cpu",
        "ripley_q"    : "cooler cpu",
        "keywords"    : ["cooler","disipador","aio","refrigeracion","fan","rgb","noctua","be quiet"],
        "exclude"     : ["pasta","soporte"],
    },
    "CASE": {
        "ml_url"      : "https://listado.mercadolibre.com.pe/gabinetes-pc",
        "falabella_q" : "gabinete pc gamer",
        "ripley_q"    : "gabinete pc",
        "keywords"    : ["gabinete","case","torre","atx","rgb","vidrio","nzxt","corsair","lian li"],
        "exclude"     : [],
    },
}

DELAY_REQ  = (2, 5)    # entre requests
DELAY_PAGE = (5, 12)   # entre páginas
DELAY_CAT  = (15, 30)  # entre categorías
MAX_PAGES  = 20        # páginas por categoría por fuente
MAX_RETRY  = 3

# ══════════════════════════════════════════════════════════════════════════════
# 2. LOGGER
# ══════════════════════════════════════════════════════════════════════════════
def setup_logger(batch_id: str) -> logging.Logger:
    log_file = LOG_DIR / f"batch_{batch_id}.log"
    fmt = "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s"
    logging.basicConfig(
        level=logging.INFO, format=fmt,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("AgentIA")

# ══════════════════════════════════════════════════════════════════════════════
# 3. DATACLASS — ITEM ESTÁNDAR
# ══════════════════════════════════════════════════════════════════════════════
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

# ══════════════════════════════════════════════════════════════════════════════
# 4. HTTP CLIENT CON ANTI-BAN
# ══════════════════════════════════════════════════════════════════════════════
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

    def _headers(self, referer: str = "") -> dict:
        h = {
            "User-Agent"      : self._random_ua(),
            "Accept"          : "text/html,application/xhtml+xml,application/json,*/*;q=0.9",
            "Accept-Language" : "es-PE,es;q=0.9,en;q=0.7",
            "Accept-Encoding" : "gzip, deflate, br",
            "DNT"             : "1",
            "Connection"      : "keep-alive",
        }
        if referer:
            h["Referer"] = referer
        return h

    def get(self, url: str, referer: str = "", params: dict = None,
            json_mode: bool = False) -> Optional[requests.Response]:
        for attempt in range(1, MAX_RETRY + 1):
            try:
                time.sleep(random.uniform(*DELAY_REQ))
                r = self.session.get(
                    url, headers=self._headers(referer),
                    params=params, timeout=15, allow_redirects=True
                )
                if r.status_code == 200:
                    return r
                elif r.status_code == 429:
                    wait = 60 * attempt
                    self.log.warning(f"Rate limit (429). Esperando {wait}s...")
                    time.sleep(wait)
                elif r.status_code in (403, 503):
                    self.log.warning(f"HTTP {r.status_code} en {url[:60]}. Intento {attempt}/{MAX_RETRY}")
                    time.sleep(30 * attempt)
                else:
                    self.log.warning(f"HTTP {r.status_code} en {url[:60]}")
                    return None
            except requests.RequestException as e:
                self.log.error(f"Error de conexión (intento {attempt}): {e}")
                time.sleep(15 * attempt)
        return None

# ══════════════════════════════════════════════════════════════════════════════
# 5. SCRAPER — MERCADOLIBRE (HTML)
# ══════════════════════════════════════════════════════════════════════════════
class MLScraper:
    def __init__(self, http: HttpClient, logger):
        self.http = http
        self.log  = logger

    def _parse_price(self, text: str) -> float:
        if not text:
            return 0.0
        clean = re.sub(r"[^\d.,]", "", text).replace(".", "").replace(",", ".")
        try:
            return float(clean)
        except ValueError:
            return 0.0

    def _is_relevant(self, title: str, cat_cfg: dict) -> bool:
        t = title.lower()
        if any(ex in t for ex in cat_cfg.get("exclude", [])):
            return False
        return True  # ML ya filtra por categoría

    def scrape_category(self, category: str, cat_cfg: dict,
                        batch_id: str, max_pages: int = MAX_PAGES) -> list[HardwareItem]:
        items   = []
        base_url = cat_cfg["ml_url"]
        seen_ids = set()
        now_str  = datetime.now(timezone.utc).isoformat()

        self.log.info(f"[ML] Scrapeando {category} — hasta {max_pages} páginas")

        for page in range(max_pages):
            offset = page * 48
            url = base_url if page == 0 else f"{base_url}_Desde_{offset + 1}"

            resp = self.http.get(url, referer="https://www.mercadolibre.com.pe/")
            if not resp:
                self.log.warning(f"[ML] Sin respuesta en página {page+1} de {category}")
                break

            soup = BeautifulSoup(resp.text, "lxml")
            cards = soup.select("li.ui-search-layout__item")

            if not cards:
                self.log.info(f"[ML] Sin más resultados en página {page+1}")
                break

            page_items = 0
            for card in cards:
                try:
                    # Título
                    title_el = (card.select_one(".poly-component__title") or
                                card.select_one(".ui-search-item__title"))
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)

                    if not self._is_relevant(title, cat_cfg):
                        continue

                    # Link e ID
                    link_el = (card.select_one("a.poly-component__title") or
                               card.select_one("a.ui-search-item__title-label-grid"))
                    url_item = link_el["href"] if link_el else ""
                    item_id  = re.search(r"MPE\d+", url_item)
                    item_id  = item_id.group(0) if item_id else f"ML_{hashlib.md5(title.encode()).hexdigest()[:8]}"

                    if item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)

                    # Precio actual
                    price_el = card.select_one(".andes-money-amount__fraction")
                    cents_el = card.select_one(".andes-money-amount__cents")
                    price_str = (price_el.get_text(strip=True) if price_el else "0") +                                 ("." + cents_el.get_text(strip=True) if cents_el else "")
                    price = self._parse_price(price_str)

                    # Precio original
                    orig_el  = card.select_one(".andes-money-amount--previous .andes-money-amount__fraction")
                    orig_str = orig_el.get_text(strip=True) if orig_el else ""
                    original = self._parse_price(orig_str) if orig_str else price
                    discount = round((1 - price / original) * 100, 1) if original > price > 0 else 0.0

                    # Vendedor
                    seller_el = card.select_one(".poly-component__seller")
                    seller    = seller_el.get_text(strip=True) if seller_el else ""

                    # Rating
                    rating_el  = card.select_one(".poly-reviews__rating")
                    reviews_el = card.select_one(".poly-reviews__total")
                    rating     = float(rating_el.get_text(strip=True)) if rating_el else 0.0
                    reviews    = int(re.sub(r"\D", "", reviews_el.get_text()) or "0") if reviews_el else 0

                    # Brand desde título
                    brand = self._extract_brand(title)

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
                        condition      = "new",
                        rating         = rating,
                        reviews_count  = reviews,
                        url            = url_item,
                    )
                    item.compute_fingerprint()

                    if item.is_valid():
                        items.append(item)
                        page_items += 1

                except Exception as e:
                    self.log.debug(f"[ML] Error parseando card: {e}")
                    continue

            self.log.info(f"[ML] {category} pág {page+1}: {page_items} items (total: {len(items)})")
            time.sleep(random.uniform(*DELAY_PAGE))

        return items

    def _extract_brand(self, title: str) -> str:
        brands = ["Intel","AMD","NVIDIA","Kingston","Samsung","Corsair","G.Skill",
                  "Crucial","WD","Seagate","ASUS","MSI","Gigabyte","ASRock","EVGA",
                  "Seasonic","be quiet","Noctua","Cooler Master","NZXT","Lian Li",
                  "Fractal","Thermaltake","Deepcool","Arctic","PNY","XFX","Sapphire",
                  "PowerColor","Zotac","Palit","Gainward","Netac","Lexar","TeamGroup"]
        t = title.lower()
        for b in brands:
            if b.lower() in t:
                return b
        return ""

# ══════════════════════════════════════════════════════════════════════════════
# 6. SCRAPER — FALABELLA (JSON embed)
# ══════════════════════════════════════════════════════════════════════════════
class FalabellaScraper:
    BASE = "https://www.falabella.com.pe/falabella-pe/search"

    def __init__(self, http: HttpClient, logger):
        self.http = http
        self.log  = logger

    def scrape_category(self, category: str, cat_cfg: dict,
                        batch_id: str, max_pages: int = 10) -> list[HardwareItem]:
        items   = []
        query   = cat_cfg.get("falabella_q", category)
        now_str = datetime.now(timezone.utc).isoformat()

        self.log.info(f"[Falabella] Scrapeando {category}")

        for page in range(1, max_pages + 1):
            url    = f"{self.BASE}?Ntt={requests.utils.quote(query)}&page={page}"
            resp   = self.http.get(url, referer="https://www.falabella.com.pe/")
            if not resp:
                break

            soup = BeautifulSoup(resp.text, "lxml")

            # Buscar JSON embed en __NEXT_DATA__ o script
            data = None
            for script in soup.find_all("script", {"id": "__NEXT_DATA__"}):
                try:
                    data = json.loads(script.string)
                    break
                except Exception:
                    pass

            if not data:
                # Fallback: parsear cards HTML
                cards = soup.select("[class*='pod-subPod']")
                if not cards:
                    break
                for card in cards:
                    try:
                        title_el = card.select_one("[class*='pod-title']")
                        price_el = card.select_one("[class*='prices-0']")
                        if not title_el or not price_el:
                            continue
                        title = title_el.get_text(strip=True)
                        price_str = re.sub(r"[^\d]", "", price_el.get_text())
                        price = float(price_str) if price_str else 0.0
                        if not title or price <= 0:
                            continue
                        link_el  = card.select_one("a")
                        url_item = "https://www.falabella.com.pe" + link_el["href"] if link_el else ""
                        item_id  = hashlib.md5(title.encode()).hexdigest()[:12]
                        item = HardwareItem(
                            batch_id=batch_id, scraped_at=now_str, source="falabella",
                            item_id=item_id, category=category, title=title,
                            price_pen=price, original_price=price, url=url_item,
                        )
                        item.compute_fingerprint()
                        if item.is_valid():
                            items.append(item)
                    except Exception:
                        continue
                self.log.info(f"[Falabella] {category} pág {page}: {len(items)} total")
                time.sleep(random.uniform(*DELAY_PAGE))
                continue

            # Extraer desde JSON
            try:
                results = (data.get("props", {})
                               .get("pageProps", {})
                               .get("searchResults", {})
                               .get("products", []))
                if not results:
                    break
                for prod in results:
                    try:
                        title  = prod.get("displayName", "")
                        prices = prod.get("prices", [{}])
                        price  = float(prices[0].get("originalPrice", 0) or 0)
                        orig   = float(prices[0].get("normalPrice", price) or price)
                        disc   = round((1 - price/orig)*100, 1) if orig > price > 0 else 0.0
                        brand  = prod.get("brand", "")
                        sku    = prod.get("skuId", hashlib.md5(title.encode()).hexdigest()[:12])
                        slug   = prod.get("slug", "")
                        url_i  = f"https://www.falabella.com.pe/falabella-pe/product/{sku}/{slug}"
                        item   = HardwareItem(
                            batch_id=batch_id, scraped_at=now_str, source="falabella",
                            item_id=f"FAL_{sku}", category=category, title=title,
                            price_pen=price, original_price=orig, discount_pct=disc,
                            brand=brand, url=url_i,
                        )
                        item.compute_fingerprint()
                        if item.is_valid():
                            items.append(item)
                    except Exception:
                        continue
            except Exception as e:
                self.log.debug(f"[Falabella] Error JSON: {e}")

            self.log.info(f"[Falabella] {category} pág {page}: {len(items)} total")
            time.sleep(random.uniform(*DELAY_PAGE))

        return items

# ══════════════════════════════════════════════════════════════════════════════
# 7. SCRAPER — RIPLEY (API pública)
# ══════════════════════════════════════════════════════════════════════════════
class RipleyScraper:
    API = "https://simple.ripley.com.pe/api/2.0/page/search"

    def __init__(self, http: HttpClient, logger):
        self.http = http
        self.log  = logger

    def scrape_category(self, category: str, cat_cfg: dict,
                        batch_id: str, max_pages: int = 10) -> list[HardwareItem]:
        items   = []
        query   = cat_cfg.get("ripley_q", category)
        now_str = datetime.now(timezone.utc).isoformat()

        self.log.info(f"[Ripley] Scrapeando {category}")

        for page in range(1, max_pages + 1):
            params = {"query": query, "page": page, "perPage": 40}
            resp   = self.http.get(self.API, params=params,
                                   referer="https://simple.ripley.com.pe/")
            if not resp:
                break
            try:
                data     = resp.json()
                products = data.get("products", [])
                if not products:
                    break
                for prod in products:
                    try:
                        title  = prod.get("name", "")
                        price  = float(prod.get("offerPrice", 0) or 0)
                        orig   = float(prod.get("normalPrice", price) or price)
                        disc   = round((1 - price/orig)*100, 1) if orig > price > 0 else 0.0
                        brand  = prod.get("brand", "")
                        sku    = prod.get("partNumber", hashlib.md5(title.encode()).hexdigest()[:12])
                        url_i  = "https://simple.ripley.com.pe" + prod.get("url", "")
                        rating = float(prod.get("rating", 0) or 0)
                        reviews= int(prod.get("reviewCount", 0) or 0)
                        item   = HardwareItem(
                            batch_id=batch_id, scraped_at=now_str, source="ripley",
                            item_id=f"RIP_{sku}", category=category, title=title,
                            price_pen=price, original_price=orig, discount_pct=disc,
                            brand=brand, rating=rating, reviews_count=reviews, url=url_i,
                        )
                        item.compute_fingerprint()
                        if item.is_valid():
                            items.append(item)
                    except Exception:
                        continue
            except Exception as e:
                self.log.debug(f"[Ripley] Error JSON: {e}")
                break

            self.log.info(f"[Ripley] {category} pág {page}: {len(items)} total")
            time.sleep(random.uniform(*DELAY_PAGE))

        return items

# ══════════════════════════════════════════════════════════════════════════════
# 8. DATA CLEANER
# ══════════════════════════════════════════════════════════════════════════════
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

    def clean(self, items: list[HardwareItem]) -> list[HardwareItem]:
        seen_fps = set()
        clean    = []
        for item in items:
            # Deduplicar por fingerprint
            if item.fingerprint in seen_fps:
                continue
            seen_fps.add(item.fingerprint)

            # Validar precio por categoría
            lo, hi = self.PRICE_LIMITS.get(item.category, (1, 999_999))
            if not (lo <= item.price_pen <= hi):
                continue

            # Limpiar título
            item.title = re.sub(r"\s+", " ", item.title).strip()

            clean.append(item)
        return clean

# ══════════════════════════════════════════════════════════════════════════════
# 9. CSV WRITER — MASTER ACUMULATIVO
# ══════════════════════════════════════════════════════════════════════════════
class MasterCSVWriter:
    def __init__(self, master_path: Path, logger):
        self.path = master_path
        self.log  = logger

    def write_batch(self, items: list[HardwareItem], batch_id: str) -> Path:
        # Archivo del batch
        batch_path = DATA_DIR / f"batch_{batch_id}.csv"
        self._write_csv(batch_path, items, write_header=True)
        self.log.info(f"Batch guardado: {batch_path} ({len(items)} items)")

        # Master acumulativo
        header_needed = not self.path.exists()
        self._write_csv(self.path, items, write_header=header_needed, mode="a")
        self.log.info(f"Master actualizado: {self.path}")

        return batch_path

    def _write_csv(self, path: Path, items: list[HardwareItem],
                   write_header: bool = True, mode: str = "w"):
        with open(path, mode, newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=SCHEMA)
            if write_header:
                writer.writeheader()
            for item in items:
                writer.writerow(asdict(item))

    def master_stats(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            import pandas as pd
            df = pd.read_csv(self.path)
            return {
                "total_records" : len(df),
                "unique_items"  : df["item_id"].nunique(),
                "categories"    : df["category"].value_counts().to_dict(),
                "sources"       : df["source"].value_counts().to_dict(),
                "batches"       : df["batch_id"].nunique(),
                "date_range"    : f"{df['scraped_at'].min()[:10]} → {df['scraped_at'].max()[:10]}",
            }
        except Exception:
            return {"error": "pandas no disponible"}

# ══════════════════════════════════════════════════════════════════════════════
# 10. BATCH ORCHESTRATOR — EL CEREBRO DEL AGENTE
# ══════════════════════════════════════════════════════════════════════════════
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
            "ripley"      : RipleyScraper(self.http, self.log),
        }

    def run_batch(self, categories: list = None, sources: list = None,
                  max_pages: int = MAX_PAGES) -> dict:
        cats    = categories or list(CATEGORIES.keys())
        srcs    = sources    or list(self.scrapers.keys())
        all_items = []

        self.log.info("=" * 70)
        self.log.info(f"BATCH {self.batch_id} INICIADO")
        self.log.info(f"Categorías : {cats}")
        self.log.info(f"Fuentes    : {srcs}")
        self.log.info(f"Max páginas: {max_pages}")
        self.log.info("=" * 70)

        t_start = time.time()

        for cat_name in cats:
            cat_cfg = CATEGORIES[cat_name]
            cat_items = []

            for src_name in srcs:
                scraper = self.scrapers[src_name]
                try:
                    raw = scraper.scrape_category(
                        cat_name, cat_cfg, self.batch_id, max_pages
                    )
                    cat_items.extend(raw)
                    self.log.info(f"  ✓ {src_name:15} → {len(raw):4d} items brutos")
                except Exception as e:
                    self.log.error(f"  ✗ {src_name}: {e}")

            # Limpiar y deduplicar por categoría
            clean = self.cleaner.clean(cat_items)
            all_items.extend(clean)
            self.log.info(f"[{cat_name}] Brutos: {len(cat_items)} → Limpios: {len(clean)}")

            time.sleep(random.uniform(*DELAY_CAT))

        # Guardar
        batch_path = self.writer.write_batch(all_items, self.batch_id)
        elapsed    = round(time.time() - t_start, 1)

        # Estadísticas
        stats = self.writer.master_stats()
        self.log.info("=" * 70)
        self.log.info(f"BATCH {self.batch_id} COMPLETADO en {elapsed}s")
        self.log.info(f"Items este batch : {len(all_items)}")
        self.log.info(f"Master total     : {stats.get('total_records', '?')} registros")
        self.log.info(f"Items únicos     : {stats.get('unique_items', '?')}")
        self.log.info(f"Archivo batch    : {batch_path}")
        self.log.info("=" * 70)

        # Guardar estado del agente
        self._save_state(len(all_items), elapsed, stats)

        return {
            "batch_id"   : self.batch_id,
            "items"      : len(all_items),
            "elapsed_s"  : elapsed,
            "batch_file" : str(batch_path),
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
        STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

# ══════════════════════════════════════════════════════════════════════════════
# 11. SCHEDULER — AGENTE AUTÓNOMO 24H
# ══════════════════════════════════════════════════════════════════════════════
def run_agent_loop(interval_hours: int = 24, max_pages: int = MAX_PAGES,
                   categories: list = None, sources: list = None):
    """Corre el agente indefinidamente, un batch cada interval_hours horas."""
    print(f"""
╔══════════════════════════════════════════════════════════╗
║  AGENTE IA — ML PERÚ HARDWARE SCRAPER                   ║
║  Intervalo : cada {interval_hours}h                                  ║
║  Páginas   : {max_pages} por categoría/fuente                 ║
║  Categorías: {len(categories or CATEGORIES)} activas                          ║
║  Fuentes   : ML + Falabella + Ripley                     ║
║  Ctrl+C para detener                                     ║
╚══════════════════════════════════════════════════════════╝
    """)

    def job():
        orch = BatchOrchestrator()
        orch.run_batch(categories=categories, sources=sources, max_pages=max_pages)

    # Ejecutar inmediatamente al inicio
    job()

    if HAS_SCHEDULE:
        schedule.every(interval_hours).hours.do(job)
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        # Fallback manual
        while True:
            wait = interval_hours * 3600
            print(f"Próximo batch en {interval_hours}h. Durmiendo...")
            time.sleep(wait)
            job()

# ══════════════════════════════════════════════════════════════════════════════
# 12. ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Agente IA — Scraper autónomo ML Perú Hardware"
    )
    parser.add_argument("--once",       action="store_true",
                        help="Ejecutar solo un batch y salir")
    parser.add_argument("--interval",   type=int, default=24,
                        help="Horas entre batches (default: 24)")
    parser.add_argument("--pages",      type=int, default=MAX_PAGES,
                        help="Páginas por categoría (default: 20)")
    parser.add_argument("--categories", nargs="+", default=None,
                        choices=list(CATEGORIES.keys()),
                        help="Categorías a scrapear (default: todas)")
    parser.add_argument("--sources",    nargs="+", default=None,
                        choices=["mercadolibre","falabella","ripley"],
                        help="Fuentes a usar (default: todas)")
    parser.add_argument("--stats",      action="store_true",
                        help="Mostrar estadísticas del Master CSV y salir")

    args = parser.parse_args()

    if args.stats:
        writer = MasterCSVWriter(MASTER_CSV, logging.getLogger())
        stats  = writer.master_stats()
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.once:
        orch = BatchOrchestrator()
        result = orch.run_batch(
            categories=args.categories,
            sources=args.sources,
            max_pages=args.pages
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        run_agent_loop(
            interval_hours=args.interval,
            max_pages=args.pages,
            categories=args.categories,
            sources=args.sources,
        )
