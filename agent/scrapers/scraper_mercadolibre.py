#!/usr/bin/env python3
"""
scraper_mercadolibre.py  v2.0
Mercado Libre Perú — API pública gratuita (sin API key)

ENDPOINT:
  https://api.mercadolibre.com/sites/MPE/search
  ?q=<keyword>&limit=50&offset=<n>&condition=all

Fixes v2.0 (sobre v1.0):
  - [M1] _fetch_page: eliminado retry manual de 429 — urllib3 Retry ya lo maneja
  - [M2] _extract_brand: fallback '' en lugar de title.split()[0]
  - [M3] seller_type: reemplazado por is_official_store (nickname heurística)
         seller_reputation NO disponible en /search endpoint
  - [M4] sold_qty: reemplazado por tags (best_seller/good_seller)
         sold_quantity NO disponible en /search endpoint
  - [M5] thumbnail: eliminado del registro
  - [M6] __main__: datetime.now(timezone.utc)
"""

import re
import time
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────
MELI_API_BASE  = "https://api.mercadolibre.com/sites/MPE/search"
MELI_SITE      = "MPE"
REQUEST_DELAY  = 1.5
ITEMS_PER_PAGE = 50
MAX_OFFSET     = 1000
TIMEOUT        = (10, 25)

MELI_QUERIES = {
    "cpu":         "procesador intel amd ryzen",
    "gpu":         "tarjeta de video nvidia amd",
    "ram":         "memoria ram ddr4 ddr5",
    "ssd":         "disco solido ssd nvme",
    "motherboard": "placa madre motherboard",
    "psu":         "fuente de poder 80 plus",
    "cooler":      "cooler cpu disipador",
    "case":        "case gabinete pc",
    "monitor":     "monitor gaming 144hz",
    "laptop":      "laptop gamer",
    "teclado":     "teclado mecanico gaming",
    "mouse":       "mouse gamer",
    "auriculares": "audifonos gamer",
    "celular":     "smartphone samsung xiaomi",
    "tablet":      "tablet android",
    "smartwatch":  "smartwatch reloj inteligente",
}

# ── Sesión ────────────────────────────────────────────────────────────────
def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=2.0,
        # [M1] urllib3 maneja 429 con backoff — no se necesita retry manual
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    session.headers.update({
        "User-Agent":      "Mozilla/5.0 (compatible; TesisHardwarePE/1.0)",
        "Accept":          "application/json",
        "Accept-Language": "es-PE,es;q=0.9",
    })
    return session

# ── Helpers ───────────────────────────────────────────────────────────────
def _parse_price(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(str(val).replace(",", ""))
        return round(f, 2) if f > 0 else None
    except (ValueError, TypeError):
        return None

KNOWN_BRANDS = [
    "Intel", "AMD", "Nvidia", "ASUS", "MSI", "Gigabyte", "Corsair",
    "Kingston", "Crucial", "G.Skill", "Samsung", "WD", "Seagate",
    "Noctua", "Cooler Master", "Thermaltake", "NZXT", "Seasonic",
    "Lenovo", "HP", "Dell", "Acer", "Apple", "Xiaomi", "Motorola",
    "Huawei", "Honor", "Sony", "LG", "Logitech", "Razer",
    "HyperX", "SteelSeries", "JBL", "Bose", "Sennheiser",
]
_BRAND_RE = re.compile(
    r"\b(" + "|".join(re.escape(b) for b in KNOWN_BRANDS) + r")\b",
    re.IGNORECASE,
)

def _extract_brand(title: str, seller_brand: str = "") -> str:
    if seller_brand and len(seller_brand) > 1:
        return seller_brand.strip()[:100]
    m = _BRAND_RE.search(title or "")
    if m:
        return m.group(1).upper()
    # [M2] Fallback '' — evita usar title.split()[0] que genera brands incorrectos
    # (ej: 'Procesador Intel...' → 'Procesador' como brand)
    return ""

# ── Fetch ─────────────────────────────────────────────────────────────────
def _fetch_page(session: requests.Session, query: str, offset: int) -> dict:
    """
    Llama a la API pública de MeLi.
    [M1] El retry de 429 lo maneja urllib3 Retry con backoff — no se duplica aquí.
    """
    params = {
        "q":         query,
        "limit":     ITEMS_PER_PAGE,
        "offset":    offset,
        "condition": "all",
        "sort":      "relevance",
    }
    try:
        r = session.get(MELI_API_BASE, params=params, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json()
        # [M1] 429 ya manejado por urllib3 Retry — solo loguear si llega aquí
        logger.debug(f"  [MeLi] HTTP {r.status_code} q='{query}' offset={offset}")
    except Exception as e:
        logger.debug(f"  [MeLi] Error q='{query}' offset={offset}: {e}")
    return {}

# ── Parser ────────────────────────────────────────────────────────────────
def _parse_item(item: dict, category: str, batch_id: str, now_iso: str) -> Optional[dict]:
    """
    Normaliza un item de la API de MeLi al esquema unificado.

    Campos disponibles en /search (verificados contra API docs):
      ✅ condition, available_quantity, free_shipping, original_price
      ✅ attributes[BRAND/MODEL], tags, seller.nickname
      ❌ sold_quantity  → solo en /items/{id}
      ❌ seller_reputation → solo en /users/{id}
    """
    try:
        item_id = item.get("id", "")
        title   = item.get("title", "").strip()
        if not title or not item_id:
            return None

        price_pen = _parse_price(item.get("price"))
        if not price_pen:
            return None

        orig_price = _parse_price(item.get("original_price"))
        discount   = 0.0
        if orig_price and orig_price > price_pen:
            discount = round((orig_price - price_pen) / orig_price * 100, 1)

        condition = item.get("condition", "not_specified")

        # Vendedor
        seller    = item.get("seller", {})
        seller_id = str(seller.get("id", ""))
        seller_nickname = seller.get("nickname", "")

        # [M3] is_official_store: heurística por nickname (formato 'MARCA-OFICIAL')
        # MeLi official stores tienen nickname en mayúsculas con guión
        # Ej: 'LENOVO-OFICIAL', 'SAMSUNG-PERU', 'ASUS-STORE'
        # seller_reputation NO disponible en /search endpoint
        is_official_store = bool(
            seller_nickname and
            re.search(r"OFICIAL|STORE|PERU|OFICIAL-PE", seller_nickname, re.IGNORECASE)
        )

        # [M4] tags como proxy de popularidad — sold_quantity NO disponible en /search
        # MeLi incluye tags: ['best_seller', 'good_seller', 'loyalty_discount_eligible', ...]
        tags         = item.get("tags", [])
        is_best_seller  = "best_seller"  in tags
        is_good_seller  = "good_seller"  in tags

        available_qty = int(item.get("available_quantity", 0) or 0)

        shipping      = item.get("shipping", {})
        free_shipping = bool(shipping.get("free_shipping", False))

        # Atributos: brand, model
        attrs = {
            a.get("id"): a.get("value_name")
            for a in item.get("attributes", [])
            if a.get("id") and a.get("value_name")
        }
        brand = attrs.get("BRAND") or attrs.get("brand") or _extract_brand(title)
        model = attrs.get("MODEL") or attrs.get("model") or ""

        permalink = item.get("permalink", "")
        # [M5] thumbnail eliminado — no aporta al análisis ROI/precio

        return {
            "batch_id":          batch_id,
            "timestamp":         now_iso,
            "source":            "mercadolibre_pe",
            "category":          category,
            "sku":               item_id,
            "brand":             str(brand)[:100],
            "model":             str(model)[:100],
            "title":             str(title)[:200],
            "price_pen":         price_pen,
            "price_orig_pen":    orig_price or 0.0,
            "discount_pct":      discount,
            "condition":         condition,           # ✅ new/used/not_specified
            "available_qty":     available_qty,       # ✅ stock disponible
            "free_shipping":     free_shipping,       # ✅ envío gratis
            "is_official_store": is_official_store,   # [M3] heurística nickname
            "is_best_seller":    is_best_seller,      # [M4] tag MeLi
            "is_good_seller":    is_good_seller,      # [M4] tag MeLi
            "seller_id":         seller_id,
            "seller_nickname":   seller_nickname[:100],
            "rating":            0.0,   # MeLi no expone rating en /search
            "reviews":           None,
            "url":               str(permalink)[:300],
        }
    except (TypeError, ValueError, KeyError, ZeroDivisionError) as e:
        logger.debug(f"  [MeLi] Parse error item {item.get('id','?')}: {e}")
        return None

# ── Scraper principal ─────────────────────────────────────────────────────
def scrape_mercadolibre(batch_id: str) -> list:
    logger.info("══════════════════════════════════════════════════")
    logger.info("  SCRAPING MERCADO LIBRE PE  v2.0")
    logger.info("══════════════════════════════════════════════════")

    all_records = []
    now_iso     = datetime.now(timezone.utc).isoformat()
    session     = _make_session()

    for cat_name, query in MELI_QUERIES.items():
        logger.info(f"\n[MeLi PE] CATEGORÍA: {cat_name} → \"{query}\"")
        cat_records = []
        seen_ids    = set()
        offset      = 0
        empty_pages = 0

        while offset <= MAX_OFFSET:
            data = _fetch_page(session, query, offset)

            if not data:
                empty_pages += 1
                if empty_pages >= 2:
                    logger.info(f"  offset={offset}: early-stop (sin datos)")
                    break
                offset += ITEMS_PER_PAGE
                time.sleep(REQUEST_DELAY)
                continue

            total_available = data.get("paging", {}).get("total", 0)
            items           = data.get("results", [])

            if not items:
                logger.info(f"  offset={offset}: 0 items → fin")
                break

            empty_pages = 0
            added = 0
            dupes = 0

            for item in items:
                iid = item.get("id", "")
                if iid in seen_ids:
                    dupes += 1
                    continue
                seen_ids.add(iid)
                record = _parse_item(item, cat_name, batch_id, now_iso)
                if record:
                    cat_records.append(record)
                    added += 1

            logger.info(
                f"  offset={offset:>4}: +{len(items)} raw → "
                f"+{added} válidos, {dupes} dupes "
                f"(total MeLi: {total_available:,})"
            )

            if offset + ITEMS_PER_PAGE >= min(total_available, MAX_OFFSET + ITEMS_PER_PAGE):
                logger.info("  → Todos los items disponibles obtenidos")
                break

            offset += ITEMS_PER_PAGE
            time.sleep(REQUEST_DELAY)

        all_records.extend(cat_records)
        logger.info(f"  ✅ {cat_name}: {len(cat_records)} registros únicos")

    # Dedup global por sku (item_id MeLi — único por item)
    seen_global = set()
    unique      = []
    for r in all_records:
        key = r["sku"]
        if key not in seen_global:
            seen_global.add(key)
            unique.append(r)

    dupes_global = len(all_records) - len(unique)
    if dupes_global:
        logger.info(f"[MeLi PE] Dedup global: -{dupes_global} duplicados entre categorías")

    logger.info(f"[MeLi PE] TOTAL: {len(unique)} registros únicos")
    return unique


# ── Standalone ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    # [M6] datetime con timezone explícita
    test_batch = f"test_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    results    = scrape_mercadolibre(test_batch)
    print(f"\nTotal registros: {len(results)}")
    if results:
        import json
        for cond in ["new", "used"]:
            ex = next((r for r in results if r["condition"] == cond), None)
            if ex:
                print(f"\nEjemplo [{cond}]:")
                print(json.dumps(ex, ensure_ascii=False, indent=2))
