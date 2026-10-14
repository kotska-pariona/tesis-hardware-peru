"""
scraper_coolbox.py — Coolbox PE
API: VTEX REST /api/catalog_system/pub/products/search
IDs de categoría verificados desde /api/catalog_system/pub/category/tree/3
"""
from __future__ import annotations
import logging, time, requests
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_BASE   = "https://www.coolbox.pe"
_SOURCE = "coolbox_pe"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, */*",
    "Accept-Language": "es-PE,es;q=0.9",
    "Referer": "https://www.coolbox.pe/",
}

# hw_type → (vtex_category_id, fallback_slug)
# IDs verificados desde /api/catalog_system/pub/category/tree/3
_CATEGORIES = {
    "cpu":     (262, "computo/componentes-de-computo/procesadores"),
    "gpu":     (399, "computo/componentes-de-computo/tarjetas-de-video"),
    "ram":     (260, "computo/componentes-de-computo/memorias-ram"),
    "storage": (259, "computo/componentes-de-computo/discos-internos-y-ssd"),
    "mobo":    (396, "computo/componentes-de-computo/placas-madres"),
    "psu":     (298, "computo/componentes-de-computo/fuentes-de-poder"),
    "case":    (397, "computo/componentes-de-computo/cases-de-pc"),
    "cooling": (591, "computo/componentes-de-computo/sistemas-de-enfriamiento-y-ventiladores"),
    "monitor": (66,  "computo/monitores"),
    "laptop":  (65,  "computo/laptops"),
}

_PAGE_SIZE  = 49    # VTEX max por request
_MAX_ITEMS  = 500   # normal
_TEST_ITEMS = 49    # test = 1 página


def _fetch_page(cat_id: int, slug: str, from_: int, to_: int,
                session: requests.Session) -> list[dict] | None:
    # Método 1: por fC (categoryId) — más preciso
    url1 = f"{_BASE}/api/catalog_system/pub/products/search"
    p1   = {"fC": cat_id, "_from": from_, "_to": to_, "O": "OrderByScoreDESC"}
    # Método 2: por slug de ruta
    url2 = f"{_BASE}/api/catalog_system/pub/products/search/{slug}"
    p2   = {"_from": from_, "_to": to_}

    for url, params in [(url1, p1), (url2, p2)]:
        try:
            r = session.get(url, params=params, headers=_HEADERS, timeout=15)
            if r.status_code in (200, 206):
                data = r.json()
                if isinstance(data, list):
                    return data
        except Exception as e:
            log.debug(f"[CBX] {url}: {e}")

    log.debug(f"[CBX] cat={cat_id} from={from_}: todos los endpoints fallaron")
    return None


def _parse_products(raw: list[dict], hw_type: str, batch_id: str) -> list[dict]:
    ts  = datetime.now(timezone.utc).isoformat()
    out = []
    for p in raw:
        try:
            item0   = (p.get("items") or [{}])[0]
            seller0 = (item0.get("sellers") or [{}])[0]
            offer   = seller0.get("commertialOffer") or {}
            price   = float(offer.get("Price") or 0)
            if price <= 0:
                continue
            avail = int(offer.get("AvailableQuantity") or 0)
            out.append({
                "batch_id":   batch_id,
                "scraped_at": ts,
                "source":     _SOURCE,
                "hw_type":    hw_type,
                "sku":        str(p.get("productId") or ""),
                "title":      str(p.get("productName") or item0.get("name") or ""),
                "brand":      str(p.get("brand") or ""),
                "price_pen":  round(price, 2),
                "price_usd":  None,
                "url":        f"{_BASE}/{p.get('linkText', '')}/p",
                "in_stock":   avail > 0,
            })
        except Exception:
            continue
    return out


def scrape_coolbox(batch_id: str, mode: str = "normal") -> list[dict]:
    log.info(f"[CBX] Iniciando scrape — batch={batch_id} mode={mode}")
    max_items    = _TEST_ITEMS if mode == "test" else _MAX_ITEMS
    all_records: list[dict] = []
    session      = requests.Session()

    for hw_type, (cat_id, slug) in _CATEGORIES.items():
        label = slug.split("/")[-1].replace("-", " ").title()
        log.info(f"[CBX] Categoría: {label} (id={cat_id})")
        cat_records: list[dict] = []
        from_ = 0

        while from_ < max_items:
            to_  = min(from_ + _PAGE_SIZE, max_items) - 1
            raw  = _fetch_page(cat_id, slug, from_, to_, session)
            if not raw:
                log.debug(f"[CBX] cat={cat_id} from={from_}: early-stop")
                break
            parsed = _parse_products(raw, hw_type, batch_id)
            cat_records.extend(parsed)
            if len(raw) < _PAGE_SIZE:
                break
            from_ += _PAGE_SIZE
            time.sleep(0.3)

        log.info(f"[CBX] {label}: {len(cat_records)} items total")
        all_records.extend(cat_records)

    log.info(f"[CBX] Scrape completo — {len(all_records)} registros")
    return all_records
