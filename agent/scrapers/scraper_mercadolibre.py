#!/usr/bin/env python3
"""
scraper_mercadolibre.py  v2.1
Mercado Libre Perú — API pública gratuita (sin API key)

ENDPOINT:
  https://api.mercadolibre.com/sites/MPE/search
  ?q=<keyword>&limit=50&offset=<n>&condition=all

Fixes v2.1 (sobre v2.0):
  [ML1] scrape_mercadolibre(): parámetro mode agregado — alinea firma con main.py
        (main.py pasa mode= a todos los scrapers)
  [ML2] scrape_mercadolibre(): session cerrada en finally — evita TCP huérfanas
        (consistente con [L11] de scraper_local y [I18] de scraper_importacion)
  [ML3] scrape_mercadolibre(): log de tiempo total al finalizar
        (consistente con [M4]/[M18]/[K10]/[L13] del resto de scrapers)
  [ML4] _fetch_page(): parámetro category_id agregado — permite filtrar por
        categoría MeLi (MPE1648=CPU, MPE1144=GPU, etc.) cuando está disponible
        → reduce resultados irrelevantes y mejora precisión por categoría
  [ML5] MELI_QUERIES: dict ampliado a (query, category_id) — category_id=None
        para categorías sin ID MeLi verificado
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

# [ML5] (query, category_id) — category_id=None si no hay ID MeLi verificado
# IDs verificados: https://api.mercadolibre.com/sites/MPE/categories
MELI_QUERIES = {
    "cpu":         ("procesador intel amd ryzen",        "MPE1648"),
    "gpu":         ("tarjeta de video nvidia amd",       "MPE1144"),
    "ram":         ("memoria ram ddr4 ddr5",             "MPE1651"),
    "ssd":         ("disco solido ssd nvme",             "MPE175604"),
    "motherboard": ("placa madre motherboard",           "MPE1646"),
    "psu":         ("fuente de poder 80 plus",           "MPE1653"),
    "cooler":      ("cooler cpu disipador",              "MPE1649"),
    "case":        ("case gabinete pc",                  "MPE1655"),
    "monitor":     ("monitor gaming 144hz",              "MPE1000"),
    "laptop":      ("laptop gamer",                      "MPE1652"),
    "teclado":     ("teclado mecanico gaming",           None),
    "mouse":       ("mouse gamer",                       None),
    "auriculares": ("audifonos gamer",                   None),
    "celular":     ("smartphone samsung xiaomi",         "MPE1051"),
    "tablet":      ("tablet android",                    "MPE1118"),
    "smartwatch":  ("smartwatch reloj inteligente",      None),
}

# ── Sesión ────────────────────────────────────────────────────────────────
def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=2.0,
        # [M1] urllib3 maneja 429 con backoff — no se duplica aquí
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
    return ""

# ── Fetch ─────────────────────────────────────────────────────────────────
def _fetch_page(
    session: requests.Session,
    query: str,
    offset: int,
    category_id: Optional[str] = None,   # [ML4]
) -> dict:
    """
    Llama a la API pública de MeLi.
    [M1]  El retry de 429 lo maneja urllib3 Retry con backoff.
    [ML4] category_id opcional — filtra por categoría MeLi cuando está disponible.
    """
    params = {
        "q":         query,
        "limit":     ITEMS_PER_PAGE,
        "offset":    offset,
        "condition": "all",
        "sort":      "relevance",
    }
    # [ML4] Agregar category_id solo si está disponible
    if category_id:
        params["category"] = category_id

    try:
        r = session.get(MELI_API_BASE, params=params, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json()
        # [M1] 429 ya manejado por urllib3 Retry — solo loguear si llega aquí
        logger.debug(
            f"  [MeLi] HTTP {r.status_code} "
            f"q='{query}' offset={offset}"
        )
    except Exception as e:
        logger.debug(f"  [MeLi] Error q='{query}' offset={offset}: {e}")
    return {}

# ── Parser ────────────────────────────────────────────────────────────────
def _parse_item(
    item: dict, category: str, batch_id: str, now_iso: str
) -> Optional[dict]:
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
        seller          = item.get("seller", {})
        seller_id       = str(seller.get("id", ""))
        seller_nickname = seller.get("nickname", "")

        # [M3] is_official_store: heurística por nickname
        # MeLi official stores tienen nickname en mayúsculas con guión
        # Ej: 'LENOVO-OFICIAL', 'SAMSUNG-PERU', 'ASUS-STORE'
        # seller_reputation NO disponible en /search endpoint
        is_official_store = bool(
            seller_nickname and
            re.search(
                r"OFICIAL|STORE|PERU|OFICIAL-PE",
                seller_nickname, re.IGNORECASE
            )
        )

        # [M4] tags como proxy de popularidad — sold_quantity NO en /search
        tags            = item.get("tags", [])
        is_best_seller  = "best_seller" in tags
        is_good_seller  = "good_seller" in tags

        available_qty = int(item.get("available_quantity", 0) or 0)

        shipping      = item.get("shipping", {})
        free_shipping = bool(shipping.get("free_shipping", False))

        # Atributos: brand, model
        attrs = {
            a.get("id"): a.get("value_name")
            for a in item.get("attributes", [])
            if a.get("id") and a.get("value_name")
        }
        brand = (attrs.get("BRAND") or attrs.get("brand") or
                 _extract_brand(title))
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
            "condition":         condition,
            "available_qty":     available_qty,
            "free_shipping":     free_shipping,
            "is_official_store": is_official_store,   # [M3]
            "is_best_seller":    is_best_seller,      # [M4]
            "is_good_seller":    is_good_seller,      # [M4]
            "seller_id":         seller_id,
            "seller_nickname":   seller_nickname[:100],
            "rating":            0.0,
            "reviews":           None,
            "url":               str(permalink)[:300],
        }
    except (TypeError, ValueError, KeyError, ZeroDivisionError) as e:
        logger.debug(
            f"  [MeLi] Parse error item {item.get('id','?')}: {e}"
        )
        return None

# ── Scraper principal ─────────────────────────────────────────────────────
def scrape_mercadolibre(batch_id: str, mode: str = "normal") -> list:
    """
    Scraper principal MeLi PE — API pública /search.
    [ML1] Parámetro mode agregado — main.py lo pasa a todos los scrapers.
    [ML2] Session cerrada en finally — evita TCP huérfanas.
    [ML3] Log de tiempo total al finalizar.
    """
    logger.info("══════════════════════════════════════════════════")
    logger.info("  SCRAPING MERCADO LIBRE PE  v2.1")
    logger.info("══════════════════════════════════════════════════")

    t_start     = time.time()   # [ML3]
    all_records = []
    now_iso     = datetime.now(timezone.utc).isoformat()
    session     = _make_session()

    try:   # [ML2] session cerrada en finally
        for cat_name, query_tuple in MELI_QUERIES.items():
            # [ML5] Desempaquetar (query, category_id)
            query, category_id = query_tuple

            logger.info(
                f"\n[MeLi PE] CATEGORÍA: {cat_name} → \"{query}\" "
                f"(cat_id={category_id or 'N/A'})"
            )
            cat_records = []
            seen_ids    = set()
            offset      = 0
            empty_pages = 0

            while offset <= MAX_OFFSET:
                # [ML4] Pasar category_id al fetch
                data = _fetch_page(session, query, offset, category_id)

                if not data:
                    empty_pages += 1
                    if empty_pages >= 2:
                        logger.info(
                            f"  offset={offset}: early-stop (sin datos)"
                        )
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

                if offset + ITEMS_PER_PAGE >= min(
                    total_available,
                    MAX_OFFSET + ITEMS_PER_PAGE
                ):
                    logger.info("  → Todos los items disponibles obtenidos")
                    break

                offset += ITEMS_PER_PAGE
                time.sleep(REQUEST_DELAY)

            all_records.extend(cat_records)
            logger.info(
                f"  ✅ {cat_name}: {len(cat_records)} registros únicos"
            )

    finally:
        session.close()   # [ML2]

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
        logger.info(
            f"[MeLi PE] Dedup global: -{dupes_global} "
            f"duplicados entre categorías"
        )

    # [ML3] Log de tiempo total
    elapsed = time.time() - t_start
    logger.info(
        f"[MeLi PE] TOTAL: {len(unique)} registros únicos — "
        f"⏱ {elapsed/60:.1f} min"
    )
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
            ex = next(
                (r for r in results if r["condition"] == cond), None
            )
            if ex:
                print(f"\nEjemplo [{cond}]:")
                print(json.dumps(ex, ensure_ascii=False, indent=2))
