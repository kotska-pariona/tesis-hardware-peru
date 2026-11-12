#!/usr/bin/env python3
"""
Ripley PE Scraper v1.0
Método: __NEXT_DATA__ SSR + paginación por offset
Fuente: simple.ripley.com.pe
"""

import requests, re, json, time, csv, os, logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ripley_pe")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
}

DELAY_OK    = 1.2
DELAY_RETRY = 5.0
MAX_RETRIES = 3

HW_CATEGORIES = [
    ("laptop",        "tecnologia/computacion/laptops"),
    ("desktop",       "tecnologia/computacion/computadoras-de-escritorio"),
    ("monitor",       "tecnologia/computacion/monitores"),
    ("tablet",        "tecnologia/computacion/tablets"),
    ("impresora",     "escolar/tecnologia/impresoras-y-tintas"),
    ("laptop_gamer",  "escolar/tecnologia/laptops-gamer"),
    ("monitor_gamer", "tecnologia/computacion-gamer/monitores-gamer"),
    ("disco_memoria", "tecnologia/computacion/disco-duro-y-memorias"),
    ("componentes",   "tecnologia/computacion-gamer/componentes"),
]

FIELDNAMES = [
    "sku", "name", "brand", "category", "hw_type",
    "price", "original_price", "currency",
    "discount_pct", "in_stock",
    "rating_score", "rating_count",
    "seller", "url", "image_url",
    "source", "scraped_at",
]


def fetch_page(slug, offset, session):
    params = f"?offset={offset}&limit=48"
    url    = f"https://simple.ripley.com.pe/{slug}{params}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                m = re.search(
                    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                    r.text, re.DOTALL
                )
                if m:
                    data = json.loads(m.group(1))
                    fp   = (data.get("props", {})
                               .get("pageProps", {})
                               .get("findabilityProps", {}))
                    return fp
                else:
                    log.warning(f"Sin __NEXT_DATA__ en {url}")
                    return None
            elif r.status_code == 429:
                log.warning(f"Rate limit (429) — esperando {DELAY_RETRY*2}s")
                time.sleep(DELAY_RETRY * 2)
            else:
                log.warning(f"HTTP {r.status_code} en {url} (intento {attempt})")
                time.sleep(DELAY_RETRY)
        except requests.RequestException as e:
            log.warning(f"Error de red: {e} (intento {attempt})")
            time.sleep(DELAY_RETRY)

    log.error(f"Fallo tras {MAX_RETRIES} intentos: {url}")
    return None


def parse_product(p, hw_type, scraped_at):
    sku   = p.get("sku", "")
    slug  = p.get("slug", "") or sku
    url   = f"https://simple.ripley.com.pe/{slug}" if slug else ""

    price    = p.get("priceNumber")       or p.get("price", "")
    orig     = p.get("masterPriceNumber") or p.get("oldPrice", "")
    currency = p.get("currency", "PEN")
    discount = p.get("discount")          or p.get("discountSalePrice", "")

    rr    = p.get("rating_reviews") or {}
    score = rr.get("score", "")
    count = rr.get("count", "")

    images = p.get("images", [])
    image  = images[0] if images else p.get("primaryImage", "")

    seller = p.get("seller", "")
    if not seller:
        shop   = p.get("shop") or {}
        seller = shop.get("shopName", "")

    return {
        "sku":            sku,
        "name":           p.get("name", ""),
        "brand":          p.get("brand", ""),
        "category":       p.get("categoryCode", ""),
        "hw_type":        hw_type,
        "price":          price,
        "original_price": orig,
        "currency":       currency,
        "discount_pct":   discount,
        "in_stock":       p.get("inStock", ""),
        "rating_score":   score,
        "rating_count":   count,
        "seller":         seller,
        "url":            url,
        "image_url":      image,
        "source":         "ripley_pe",
        "scraped_at":     scraped_at,
    }


def scrape_category(hw_type, slug, writer, session, start_offset=0):
    log.info(f"▶ [{hw_type}] /{slug}  (desde offset={start_offset})")

    fp0 = fetch_page(slug, start_offset, session)
    if not fp0 or not isinstance(fp0, dict):
        log.error(f"  No se pudo obtener pagina inicial de {slug}")
        return 0

    data0 = fp0.get("data")
    if not data0:
        log.error(f"  findabilityProps sin 'data' en {slug}")
        return 0

    total      = data0.get("total", 0)
    limit      = data0.get("limit", 48)
    pages      = (total + limit - 1) // limit
    scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Calcular pagina de inicio
    start_page = start_offset // limit

    log.info(f"  Total: {total:,} productos | {pages} paginas | inicio pag {start_page+1}")

    count = 0
    for page_num in range(start_page, pages):
        offset = page_num * limit

        if page_num == start_page:
            fp = fp0   # reutilizar la primera
        else:
            time.sleep(DELAY_OK)
            fp = fetch_page(slug, offset, session)

        # Validacion robusta
        if not fp or not isinstance(fp, dict):
            log.warning(f"  fp=None en pag {page_num+1}/{pages} — reintentando...")
            time.sleep(DELAY_RETRY)
            fp = fetch_page(slug, offset, session)
            if not fp or not isinstance(fp, dict):
                log.warning(f"  Saltando pag {page_num+1}/{pages} (offset={offset})")
                continue

        fp_data = fp.get("data")
        if not fp_data:
            log.warning(f"  Sin 'data' en pag {page_num+1} — saltando")
            continue

        products = fp_data.get("products", [])
        for p in products:
            row = parse_product(p, hw_type, scraped_at)
            writer.writerow(row)
            count += 1

        log.info(f"  Pag {page_num+1:>3}/{pages} | +{len(products):>2} prods | acum={count:,}")

    log.info(f"  OK [{hw_type}] {count:,} productos")
    return count


def main():
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir  = Path("data/raw")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"batch_{ts}_ripley_pe.csv"

    log.info("=" * 55)
    log.info("Ripley PE Scraper v1.0")
    log.info(f"Output: {out_file}")
    log.info(f"Categorias: {len(HW_CATEGORIES)}")
    log.info("=" * 55)

    session     = requests.Session()
    total_count = 0

    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()

        for hw_type, slug in HW_CATEGORIES:
            n = scrape_category(hw_type, slug, writer, session)
            total_count += n
            time.sleep(DELAY_OK * 2)

    log.info("=" * 55)
    log.info("SCRAPING COMPLETO")
    log.info(f"   Archivo  : {out_file}")
    log.info(f"   Productos: {total_count:,}")
    log.info("=" * 55)
    return str(out_file)


if __name__ == "__main__":
    main()
