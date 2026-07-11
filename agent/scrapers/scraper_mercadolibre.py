#!/usr/bin/env python3
"""
scraper_mercadolibre.py  v1.0
Mercado Libre Perú — API pública gratuita (sin API key)

ENDPOINT:
  https://api.mercadolibre.com/sites/MPE/search
  ?q=<keyword>&limit=50&offset=<n>&condition=all

VENTAJAS para la tesis:
  - Precios de mercado primario Y secundario (new/used)
  - Campo sold_qty → indicador de demanda real
  - Vendedores locales Lima → complementa Falabella/Hiraoka
  - Sin autenticación requerida (rate limit: ~60 req/min)

CATEGORÍAS: 12 hardware + electrónica (mismas que Falabella para comparación)
ESTIMADO:   ~3,000–5,000 registros únicos/run
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
MELI_SITE      = "MPE"          # Mercado Libre Perú
REQUEST_DELAY  = 1.5            # MeLi permite ~60 req/min → 1s mínimo
ITEMS_PER_PAGE = 50             # máximo permitido por MeLi API
MAX_OFFSET     = 1000           # MeLi limita a offset 1000 (20 páginas × 50)
TIMEOUT        = (10, 25)

# Queries: mismas categorías que Falabella para poder comparar precios
MELI_QUERIES = {
    "cpu":            "procesador intel amd ryzen",
    "gpu":            "tarjeta de video nvidia amd",
    "ram":            "memoria ram ddr4 ddr5",
    "ssd":            "disco solido ssd nvme",
    "motherboard":    "placa madre motherboard",
    "psu":            "fuente de poder 80 plus",
    "cooler":         "cooler cpu disipador",
    "case":           "case gabinete pc",
    "monitor":        "monitor gaming 144hz",
    "laptop":         "laptop gamer",
    "teclado":        "teclado mecanico gaming",
    "mouse":          "mouse gamer",
    "auriculares":    "audifonos gamer",
    "celular":        "smartphone samsung xiaomi",
    "tablet":         "tablet android",
    "smartwatch":     "smartwatch reloj inteligente",
}

# ── Sesión ────────────────────────────────────────────────────────────────
def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=2.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    session.headers.update({
        "User-Agent":    "Mozilla/5.0 (compatible; TesisHardwarePE/1.0)",
        "Accept":        "application/json",
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
    "Intel","AMD","Nvidia","ASUS","MSI","Gigabyte","Corsair","Kingston",
    "Crucial","G.Skill","Samsung","WD","Seagate","Noctua","Cooler Master",
    "Thermaltake","NZXT","Seasonic","Lenovo","HP","Dell","Acer","Apple",
    "Xiaomi","Motorola","Huawei","Honor","Sony","LG","Logitech","Razer",
    "HyperX","SteelSeries","JBL","Bose","Sennheiser",
]
_BRAND_RE = re.compile(
    r"\b(" + "|".join(re.escape(b) for b in KNOWN_BRANDS) + r")\b",
    re.IGNORECASE,
)

def _extract_brand(title: str, seller_brand: str = "") -> str:
    if seller_brand and len(seller_brand) > 1:
        return seller_brand.strip()[:100]
    m = _BRAND_RE.search(title or "")
    return m.group(1).upper() if m else (title.split()[0].capitalize() if title else "Unknown")

# ── Fetch ─────────────────────────────────────────────────────────────────
def _fetch_page(session: requests.Session, query: str, offset: int) -> dict:
    """
    Llama a la API pública de MeLi.
    Retorna el JSON completo o {} si falla.
    """
    params = {
        "q":         query,
        "limit":     ITEMS_PER_PAGE,
        "offset":    offset,
        "condition": "all",          # new + used
        "sort":      "relevance",
    }
    try:
        r = session.get(MELI_API_BASE, params=params, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 429:
            logger.warning(f"  [MeLi] Rate limit hit — esperando 10s")
            time.sleep(10)
            r2 = session.get(MELI_API_BASE, params=params, timeout=TIMEOUT)
            if r2.status_code == 200:
                return r2.json()
        else:
            logger.debug(f"  [MeLi] HTTP {r.status_code} q='{query}' offset={offset}")
    except Exception as e:
        logger.debug(f"  [MeLi] Error q='{query}' offset={offset}: {e}")
    return {}

# ── Parser ────────────────────────────────────────────────────────────────
def _parse_item(item: dict, category: str, batch_id: str, now_iso: str) -> Optional[dict]:
    """
    Normaliza un item de la API de MeLi al esquema unificado.
    Campos extra relevantes para tesis: condition, sold_qty, seller_type.
    """
    try:
        item_id   = item.get("id", "")
        title     = item.get("title", "").strip()
        if not title or not item_id:
            return None

        price_pen = _parse_price(item.get("price"))
        if not price_pen:
            return None

        # Precio original (si tiene descuento)
        orig_price = _parse_price(item.get("original_price"))
        discount   = 0.0
        if orig_price and orig_price > price_pen:
            discount = round((orig_price - price_pen) / orig_price * 100, 1)

        # Condición: new / used / not_specified
        condition = item.get("condition", "not_specified")

        # Vendedor
        seller     = item.get("seller", {})
        seller_id  = str(seller.get("id", ""))
        # Tipo de vendedor: official_store / normal / platinum / gold_pro etc.
        seller_type = seller.get("seller_reputation", {}).get("power_seller_status") or "normal"

        # Cantidad vendida (muy útil para análisis de demanda)
        sold_qty = item.get("sold_quantity", 0) or 0

        # Stock disponible
        available_qty = item.get("available_quantity", 0) or 0

        # Envío gratis
        shipping     = item.get("shipping", {})
        free_shipping = bool(shipping.get("free_shipping", False))

        # Atributos: brand, model, etc.
        attrs = {a.get("id"): a.get("value_name")
                 for a in item.get("attributes", [])
                 if a.get("id") and a.get("value_name")}
        brand = attrs.get("BRAND") or attrs.get("brand") or _extract_brand(title)
        model = attrs.get("MODEL") or attrs.get("model") or ""

        # URL
        permalink = item.get("permalink", "")

        # Thumbnail
        thumbnail = item.get("thumbnail", "")

        return {
            "batch_id":       batch_id,
            "timestamp":      now_iso,
            "source":         "mercadolibre_pe",
            "category":       category,
            "sku":            item_id,
            "brand":          str(brand)[:100],
            "model":          str(model)[:100],
            "title":          str(title)[:200],
            "price_pen":      price_pen,
            "price_orig_pen": orig_price or 0.0,
            "discount_pct":   discount,
            "condition":      condition,          # ← EXTRA: new/used
            "sold_qty":       int(sold_qty),      # ← EXTRA: demanda
            "available_qty":  int(available_qty), # ← EXTRA: stock
            "free_shipping":  free_shipping,      # ← EXTRA: logística
            "seller_type":    seller_type,        # ← EXTRA: tipo vendedor
            "seller_id":      seller_id,
            "rating":         0.0,                # MeLi no expone rating en search
            "reviews":        None,
            "url":            str(permalink)[:300],
            "thumbnail":      str(thumbnail)[:200],
        }
    except (TypeError, ValueError, KeyError, ZeroDivisionError) as e:
        logger.debug(f"  [MeLi] Parse error item {item.get('id','?')}: {e}")
        return None

# ── Scraper principal ─────────────────────────────────────────────────────
def scrape_mercadolibre(batch_id: str) -> list:
    logger.info("══════════════════════════════════════════════════")
    logger.info("  SCRAPING MERCADO LIBRE PE  v1.0")
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

            # Total disponible en MeLi para esta query
            total_available = data.get("paging", {}).get("total", 0)
            items = data.get("results", [])

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

            # Si ya obtuvimos todos los disponibles, parar
            if offset + ITEMS_PER_PAGE >= min(total_available, MAX_OFFSET + ITEMS_PER_PAGE):
                logger.info(f"  → Todos los items disponibles obtenidos")
                break

            offset += ITEMS_PER_PAGE
            time.sleep(REQUEST_DELAY)

        all_records.extend(cat_records)
        logger.info(f"  ✅ {cat_name}: {len(cat_records)} registros únicos")

    # Dedup global por sku (mismo item puede aparecer en 2 queries)
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
    test_batch = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results    = scrape_mercadolibre(test_batch)
    print(f"\nTotal registros: {len(results)}")
    if results:
        import json
        # Mostrar un ejemplo de cada condición
        for cond in ["new", "used"]:
            ex = next((r for r in results if r["condition"] == cond), None)
            if ex:
                print(f"\nEjemplo [{cond}]:")
                print(json.dumps(ex, ensure_ascii=False, indent=2))
