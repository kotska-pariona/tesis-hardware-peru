#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agente Autonomo de Scraping - ML Peru Hardware
Tesis: Sistema Hibrido DL + Computacion Evolutiva
Autor: Kotska Rony Pariona Martinez - UNI 2026
Version: v3.2 - OAuth2 MercadoLibre + Falabella HTML + Hiraoka HTML
         bugfix: clean_price robusto (evita float crash con "1.2.3")
"""

import os, sys, re, json, csv, time, random, logging, hashlib, argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

import requests

try:
    from fake_useragent import UserAgent
    _UA = UserAgent()
    def random_ua(): return _UA.random
except Exception:
    def random_ua(): return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

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
# 2. CATEGORIAS
# ════════════════════════════════════════════════════════════════
CATEGORIES = {
    "CPU": {
        "ml_query"   : "procesador cpu amd intel",
        "ml_cat_id"  : "MPE1700",
        "falabella_q": "procesador cpu",
        "hiraoka_q"  : "procesador",
        "keywords"   : ["ryzen","intel","core","procesador","cpu","ghz","amd"],
        "exclude"    : ["pasta","soporte","cooler","ventilador","disipador","limpiador"],
    },
    "GPU": {
        "ml_query"   : "tarjeta de video gpu nvidia amd",
        "ml_cat_id"  : "MPE1658",
        "falabella_q": "tarjeta de video gpu",
        "hiraoka_q"  : "tarjeta video",
        "keywords"   : ["rtx","rx","gtx","radeon","geforce","nvidia","amd","gddr","vram"],
        "exclude"    : ["soporte","cable","adaptador","limpiador","funda"],
    },
    "RAM": {
        "ml_query"   : "memoria ram ddr4 ddr5",
        "ml_cat_id"  : "MPE1694",
        "falabella_q": "memoria ram ddr",
        "hiraoka_q"  : "memoria ram",
        "keywords"   : ["ddr4","ddr5","ddr3","gb","mhz","memoria","ram"],
        "exclude"    : [],
    },
    "SSD": {
        "ml_query"   : "disco ssd nvme m.2",
        "ml_cat_id"  : "MPE1672",
        "falabella_q": "ssd nvme m.2",
        "hiraoka_q"  : "disco ssd nvme",
        "keywords"   : ["ssd","nvme","m.2","pcie","sata","tb","gb"],
        "exclude"    : ["externo","usb","case","gabinete"],
    },
    "MOTHERBOARD": {
        "ml_query"   : "placa madre motherboard am5 lga",
        "ml_cat_id"  : "MPE1692",
        "falabella_q": "placa madre motherboard",
        "hiraoka_q"  : "placa madre",
        "keywords"   : ["motherboard","placa","am5","am4","lga","atx","b650","z790"],
        "exclude"    : ["limpiador","soporte"],
    },
    "PSU": {
        "ml_query"   : "fuente de poder psu 650w 750w 850w",
        "ml_cat_id"  : "MPE1691",
        "falabella_q": "fuente de poder psu",
        "hiraoka_q"  : "fuente poder",
        "keywords"   : ["watts","watt","80plus","modular","fuente","psu"],
        "exclude"    : ["cable","adaptador","ups","regleta"],
    },
    "COOLER": {
        "ml_query"   : "cooler disipador cpu refrigeracion liquida",
        "ml_cat_id"  : "MPE1659",
        "falabella_q": "cooler disipador cpu",
        "hiraoka_q"  : "cooler cpu",
        "keywords"   : ["cooler","disipador","aio","refrigeracion","fan","rgb"],
        "exclude"    : ["pasta","soporte"],
    },
    "CASE": {
        "ml_query"   : "gabinete pc gamer atx",
        "ml_cat_id"  : "MPE1661",
        "falabella_q": "gabinete pc gamer",
        "hiraoka_q"  : "gabinete pc",
        "keywords"   : ["gabinete","case","torre","atx","rgb","vidrio"],
        "exclude"    : [],
    },
}

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
        raw = f"{self.source}|{self.title}|{self.price_pen}"
        self.fingerprint = hashlib.md5(raw.encode()).hexdigest()

# ════════════════════════════════════════════════════════════════
# 5. HTTP CLIENT con OAuth2 para MercadoLibre
# ════════════════════════════════════════════════════════════════
class HttpClient:
    def __init__(self, logger):
        self.logger         = logger
        self.session        = requests.Session()
        self._ml_token      = None
        self._ml_token_exp  = 0
        self._app_id        = os.environ.get("ML_APP_ID", "")
        self._app_secret    = os.environ.get("ML_SECRET", "")

    def _get_ml_token(self) -> Optional[str]:
        """Obtiene Access Token via client_credentials (no requiere usuario)."""
        now = time.time()
        if self._ml_token and now < self._ml_token_exp - 60:
            return self._ml_token

        if not self._app_id or not self._app_secret:
            self.logger.warning("[ML-OAuth] ML_APP_ID o ML_SECRET no configurados")
            return None

        try:
            resp = requests.post(
                "https://api.mercadolibre.com/oauth/token",
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "Accept"      : "application/json"},
                data={
                    "grant_type"   : "client_credentials",
                    "client_id"    : self._app_id,
                    "client_secret": self._app_secret,
                },
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                self._ml_token     = data["access_token"]
                self._ml_token_exp = now + data.get("expires_in", 21600)
                self.logger.info("[ML-OAuth] Token obtenido OK (expira en %ds)", data.get("expires_in", 21600))
                return self._ml_token
            else:
                self.logger.error("[ML-OAuth] Error %d: %s", resp.status_code, resp.text[:200])
                return None
        except Exception as e:
            self.logger.error("[ML-OAuth] Excepcion: %s", e)
            return None

    def get_json(self, url: str, params: dict = None, use_ml_auth: bool = False) -> Optional[dict]:
        headers = {"Accept": "application/json", "User-Agent": random_ua()}
        if use_ml_auth:
            token = self._get_ml_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

        for attempt in range(1, MAX_RETRY + 1):
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=20)
                if r.status_code == 200:
                    return r.json()
                elif r.status_code == 401 and use_ml_auth:
                    self.logger.warning("[ML-OAuth] 401 - renovando token...")
                    self._ml_token = None
                    token = self._get_ml_token()
                    if token:
                        headers["Authorization"] = f"Bearer {token}"
                    continue
                else:
                    self.logger.warning("HTTP %d en %s. Intento %d/%d", r.status_code, url, attempt, MAX_RETRY)
                    if attempt < MAX_RETRY:
                        time.sleep(random.uniform(10, 20) * attempt)
            except Exception as e:
                self.logger.warning("Error en %s: %s. Intento %d/%d", url, e, attempt, MAX_RETRY)
                if attempt < MAX_RETRY:
                    time.sleep(random.uniform(5, 10))
        return None

    def get_html(self, url: str, params: dict = None) -> Optional[str]:
        headers = {
            "User-Agent"     : random_ua(),
            "Accept-Language": "es-PE,es;q=0.9",
            "Accept"         : "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer"        : "https://www.google.com/",
        }
        for attempt in range(1, MAX_RETRY + 1):
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=25)
                if r.status_code == 200:
                    return r.text
                else:
                    self.logger.warning("HTTP %d en %s. Intento %d/%d", r.status_code, url, attempt, MAX_RETRY)
                    if attempt < MAX_RETRY:
                        time.sleep(random.uniform(8, 15))
            except Exception as e:
                self.logger.warning("Error HTML %s: %s", url, e)
                if attempt < MAX_RETRY:
                    time.sleep(random.uniform(5, 10))
        return None

# ════════════════════════════════════════════════════════════════
# 6. DATA CLEANER  — v3.2: clean_price robusto
# ════════════════════════════════════════════════════════════════
class DataCleaner:
    @staticmethod
    def clean_price(val) -> float:
        """Extrae el primer número válido de un string de precio.
        Maneja: "S/ 1,299.00", "1.299,00", "S/.1299", "1,299", etc.
        """
        if val is None:
            return 0.0
        s = str(val).strip()
        # Detectar formato europeo/peruano con punto como separador de miles
        # Ej: "1.299,00" → "1299.00"
        if re.search(r'\d{1,3}(\.\d{3})+(,\d+)?$', s):
            s = s.replace(".", "").replace(",", ".")
        else:
            # Formato anglosajón: eliminar comas de miles "1,299.00" → "1299.00"
            s = s.replace(",", "")
        # Extraer primer número flotante válido del string limpio
        match = re.search(r'\d+(\.\d+)?', s)
        if match:
            try:
                return float(match.group())
            except ValueError:
                return 0.0
        return 0.0

    @staticmethod
    def clean_title(t: str) -> str:
        return re.sub(r"\s+", " ", str(t)).strip()[:250]

    @staticmethod
    def is_relevant(title: str, category: str) -> bool:
        t   = title.lower()
        cfg = CATEGORIES.get(category, {})
        kws = cfg.get("keywords", [])
        exc = cfg.get("exclude", [])
        if any(e in t for e in exc):
            return False
        return any(k in t for k in kws) if kws else True

# ════════════════════════════════════════════════════════════════
# 7. SCRAPER MERCADOLIBRE — OAuth2
# ════════════════════════════════════════════════════════════════
class MercadoLibreScraper:
    BASE = "https://api.mercadolibre.com/sites/MPE/search"

    def __init__(self, client: HttpClient, logger):
        self.client  = client
        self.logger  = logger
        self.cleaner = DataCleaner()

    def scrape(self, category: str, batch_id: str, max_pages: int) -> list:
        cfg   = CATEGORIES[category]
        query = cfg["ml_query"]
        items = []
        self.logger.info("[ML-API] Scrapeando %s - hasta %d paginas", category, max_pages)

        for page in range(max_pages):
            offset = page * 50
            params = {"q": query, "limit": 50, "offset": offset}
            if cfg.get("ml_cat_id"):
                params["category"] = cfg["ml_cat_id"]

            data = self.client.get_json(self.BASE, params=params, use_ml_auth=True)
            if not data or "results" not in data:
                self.logger.warning("[ML-API] Sin respuesta en pagina %d", page + 1)
                break

            results = data["results"]
            if not results:
                break

            for r in results:
                title = self.cleaner.clean_title(r.get("title", ""))
                if not self.cleaner.is_relevant(title, category):
                    continue
                price    = self.cleaner.clean_price(r.get("price"))
                orig     = self.cleaner.clean_price(r.get("original_price") or price)
                disc     = round((1 - price / orig) * 100, 1) if orig > price > 0 else 0.0
                seller   = r.get("seller", {}).get("nickname", "")
                attr_map = {a["id"]: a.get("value_name", "") for a in r.get("attributes", [])}
                item = HardwareItem(
                    batch_id       = batch_id,
                    scraped_at     = datetime.now(timezone.utc).isoformat(),
                    source         = "mercadolibre",
                    item_id        = str(r.get("id", "")),
                    category       = category,
                    title          = title,
                    price_pen      = price,
                    original_price = orig,
                    discount_pct   = disc,
                    seller         = seller,
                    brand          = attr_map.get("BRAND", ""),
                    condition      = r.get("condition", "new"),
                    sold_quantity  = int(r.get("sold_quantity") or 0),
                    available_qty  = int(r.get("available_quantity") or 0),
                    rating         = 0.0,
                    reviews_count  = 0,
                    url            = r.get("permalink", ""),
                )
                item.compute_fingerprint()
                items.append(item)

            self.logger.info("[ML-API] %s pag %d: %d items (total: %d)", category, page + 1, len(results), len(items))
            if len(results) < 50:
                break
            if page < max_pages - 1:
                time.sleep(random.uniform(*DELAY_PAGE))

        self.logger.info("[ML-API] %s TOTAL: %d items", category, len(items))
        return items

# ════════════════════════════════════════════════════════════════
# 8. SCRAPER FALABELLA — HTML con BeautifulSoup
# ════════════════════════════════════════════════════════════════
class FalabellaScraper:
    def __init__(self, client: HttpClient, logger):
        self.client  = client
        self.logger  = logger
        self.cleaner = DataCleaner()

    def scrape(self, category: str, batch_id: str, max_pages: int) -> list:
        if not HAS_BS4:
            self.logger.warning("[Falabella] BeautifulSoup no instalado, saltando")
            return []

        cfg   = CATEGORIES[category]
        query = cfg["falabella_q"]
        items = []
        self.logger.info("[Falabella] Scrapeando %s", category)

        for page in range(1, max_pages + 1):
            url  = (f"https://www.falabella.com.pe/falabella-pe/search"
                    f"?Ntt={requests.utils.quote(query)}&start={(page - 1) * 24}")
            html = self.client.get_html(url)
            if not html:
                self.logger.warning("[Falabella] Sin HTML en pag %d", page)
                break

            soup  = BeautifulSoup(html, "lxml")
            cards = (soup.select("div[class*='pod-']") or
                     soup.select("li.grid-pod") or
                     soup.select("div.pod"))
            if not cards:
                self.logger.info("[Falabella] Sin productos en pag %d", page)
                break

            page_items = 0
            for card in cards:
                try:
                    title_el = (card.select_one("[class*='pod-subTitle']") or
                                card.select_one("[class*='pod-title']") or
                                card.select_one("b.pod-subTitle"))
                    price_el = (card.select_one("[class*='prices-0']") or
                                card.select_one("span[class*='copy10']") or
                                card.select_one("[class*='price']"))
                    link_el  = card.select_one("a[href]")

                    if not title_el:
                        continue
                    title = self.cleaner.clean_title(title_el.get_text())
                    if not self.cleaner.is_relevant(title, category):
                        continue

                    price = self.cleaner.clean_price(price_el.get_text() if price_el else "0")
                    url_p = ("https://www.falabella.com.pe" + link_el["href"]) if link_el else ""

                    item = HardwareItem(
                        batch_id       = batch_id,
                        scraped_at     = datetime.now(timezone.utc).isoformat(),
                        source         = "falabella",
                        item_id        = hashlib.md5(title.encode()).hexdigest()[:12],
                        category       = category,
                        title          = title,
                        price_pen      = price,
                        original_price = price,
                        url            = url_p,
                    )
                    item.compute_fingerprint()
                    items.append(item)
                    page_items += 1
                except Exception as e:
                    self.logger.debug("[Falabella] Error parseando card: %s", e)

            self.logger.info("[Falabella] %s pag %d: %d items (total: %d)", category, page, page_items, len(items))
            if page_items == 0:
                break
            if page < max_pages:
                time.sleep(random.uniform(*DELAY_PAGE))

        return items

# ════════════════════════════════════════════════════════════════
# 9. SCRAPER HIRAOKA — HTML con BeautifulSoup
# ════════════════════════════════════════════════════════════════
class HiraokaScraper:
    def __init__(self, client: HttpClient, logger):
        self.client  = client
        self.logger  = logger
        self.cleaner = DataCleaner()

    def scrape(self, category: str, batch_id: str, max_pages: int) -> list:
        if not HAS_BS4:
            self.logger.warning("[Hiraoka] BeautifulSoup no instalado, saltando")
            return []

        cfg   = CATEGORIES[category]
        query = cfg["hiraoka_q"]
        items = []
        self.logger.info("[Hiraoka] Scrapeando %s", category)

        for page in range(1, max_pages + 1):
            url  = (f"https://www.hiraoka.com.pe/catalogsearch/result/"
                    f"?q={requests.utils.quote(query)}&p={page}")
            html = self.client.get_html(url)
            if not html:
                self.logger.warning("[Hiraoka] Sin HTML en pag %d", page)
                break

            soup  = BeautifulSoup(html, "lxml")
            cards = (soup.select("li.product-item") or
                     soup.select("div.product-item-info") or
                     soup.select("li[class*='product']"))
            if not cards:
                self.logger.info("[Hiraoka] Sin productos en pag %d", page)
                break

            page_items = 0
            for card in cards:
                try:
                    title_el = (card.select_one("a.product-item-link") or
                                card.select_one("strong.product-item-name a") or
                                card.select_one("[class*='product-name']"))
                    price_el = (card.select_one("span.price") or
                                card.select_one("[class*='price']"))
                    link_el  = (card.select_one("a.product-item-link") or
                                card.select_one("a[href]"))

                    if not title_el:
                        continue
                    title = self.cleaner.clean_title(title_el.get_text())
                    if not self.cleaner.is_relevant(title, category):
                        continue

                    price = self.cleaner.clean_price(price_el.get_text() if price_el else "0")
                    url_p = link_el["href"] if link_el else ""

                    item = HardwareItem(
                        batch_id       = batch_id,
                        scraped_at     = datetime.now(timezone.utc).isoformat(),
                        source         = "hiraoka",
                        item_id        = hashlib.md5(title.encode()).hexdigest()[:12],
                        category       = category,
                        title          = title,
                        price_pen      = price,
                        original_price = price,
                        url            = url_p,
                    )
                    item.compute_fingerprint()
                    items.append(item)
                    page_items += 1
                except Exception as e:
                    self.logger.debug("[Hiraoka] Error parseando card: %s", e)

            self.logger.info("[Hiraoka] %s pag %d: %d items (total: %d)", category, page, page_items, len(items))
            if page_items == 0:
                break
            if page < max_pages:
                time.sleep(random.uniform(*DELAY_PAGE))

        return items

# ════════════════════════════════════════════════════════════════
# 10. MASTER CSV WRITER
# ════════════════════════════════════════════════════════════════
class MasterCSVWriter:
    def __init__(self, logger):
        self.logger = logger

    def write_batch(self, items: list, batch_id: str) -> Path:
        batch_file = DATA_DIR / f"batch_{batch_id}.csv"
        with open(batch_file, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=SCHEMA)
            w.writeheader()
            for item in items:
                w.writerow(asdict(item))
        self.logger.info("Batch guardado: %s (%d items)", batch_file, len(items))
        return batch_file

    def update_master(self, batch_file: Path):
        rows = []
        if MASTER_CSV.exists():
            with open(MASTER_CSV, "r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

        fps      = {r["fingerprint"] for r in rows}
        new_rows = []
        with open(batch_file, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["fingerprint"] not in fps:
                    new_rows.append(r)
                    fps.add(r["fingerprint"])

        rows.extend(new_rows)
        with open(MASTER_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=SCHEMA)
            w.writeheader()
            w.writerows(rows)
        self.logger.info(
            "Master actualizado: %s (%d registros totales, +%d nuevos)",
            MASTER_CSV, len(rows), len(new_rows)
        )

# ════════════════════════════════════════════════════════════════
# 11. BATCH ORCHESTRATOR
# ════════════════════════════════════════════════════════════════
class BatchOrchestrator:
    def __init__(self, max_pages: int = 3, categories: list = None, sources: list = None):
        self.batch_id   = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.max_pages  = max_pages
        self.categories = list(categories) if categories else list(CATEGORIES.keys())  # ← FIX #5: list() seguro
        self.sources    = sources or ["mercadolibre", "falabella", "hiraoka"]
        self.logger     = setup_logger(self.batch_id)
        self.client     = HttpClient(self.logger)
        self.writer     = MasterCSVWriter(self.logger)
        self.cleaner    = DataCleaner()

        self.ml_scraper  = MercadoLibreScraper(self.client, self.logger) if "mercadolibre" in self.sources else None
        self.fal_scraper = FalabellaScraper(self.client, self.logger)    if "falabella"    in self.sources else None
        self.hir_scraper = HiraokaScraper(self.client, self.logger)      if "hiraoka"      in self.sources else None

    def run(self) -> dict:
        t0 = time.time()
        self.logger.info("=" * 70)
        self.logger.info("BATCH %s INICIADO", self.batch_id)
        self.logger.info("Categorias : %s", self.categories)
        self.logger.info("Fuentes    : %s", self.sources)
        self.logger.info("Max paginas: %d", self.max_pages)
        self.logger.info("=" * 70)

        all_items = []

        for idx, category in enumerate(self.categories):
            cat_items = []

            if self.ml_scraper:
                ml_items = self.ml_scraper.scrape(category, self.batch_id, self.max_pages)
                self.logger.info("  OK mercadolibre    -> %4d items brutos", len(ml_items))
                cat_items.extend(ml_items)
                time.sleep(random.uniform(*DELAY_REQ))

            if self.fal_scraper:
                fal_items = self.fal_scraper.scrape(category, self.batch_id, self.max_pages)
                self.logger.info("  OK falabella       -> %4d items brutos", len(fal_items))
                cat_items.extend(fal_items)
                time.sleep(random.uniform(*DELAY_REQ))

            if self.hir_scraper:
                hir_items = self.hir_scraper.scrape(category, self.batch_id, self.max_pages)
                self.logger.info("  OK hiraoka         -> %4d items brutos", len(hir_items))
                cat_items.extend(hir_items)

            self.logger.info("[%s] Total categoria: %d items", category, len(cat_items))
            all_items.extend(cat_items)

            # ← FIX #5: usar índice en vez de comparar con [-1]
            if idx < len(self.categories) - 1:
                time.sleep(random.uniform(*DELAY_CAT))

        batch_file = self.writer.write_batch(all_items, self.batch_id)
        self.writer.update_master(batch_file)

        elapsed = round(time.time() - t0, 1)
        self.logger.info("=" * 70)
        self.logger.info("BATCH %s COMPLETADO en %.1fs", self.batch_id, elapsed)
        self.logger.info("Items este batch : %d", len(all_items))
        self.logger.info("=" * 70)

        return {
            "batch_id"  : self.batch_id,
            "items"     : len(all_items),
            "elapsed_s" : elapsed,
            "batch_file": str(batch_file),
        }

# ════════════════════════════════════════════════════════════════
# 12. MAIN
# ════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="Agente Scraping Hardware Peru v3.2")
    parser.add_argument("--pages",      type=int,  default=int(os.environ.get("PAGES", 3)))
    parser.add_argument("--categories", nargs="+", default=None)
    parser.add_argument("--sources",    nargs="+", default=None)
    parser.add_argument("--once",       action="store_true")
    args = parser.parse_args()

    orchestrator = BatchOrchestrator(
        max_pages  = args.pages,
        categories = args.categories,
        sources    = args.sources,
    )
    result = orchestrator.run()
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
