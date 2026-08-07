
import time
import random
import json
import pandas as pd
import requests
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

BASE_DIR    = Path(__file__).resolve().parent.parent
OUTPUT_PATH = BASE_DIR / "data" / "raw" / "scrape_internacional.csv"

# ── Productos a buscar (hardware PC) ─────────────────────────────────
PRODUCTOS_BUSCAR = [
    # (query_busqueda,        hw_type,       categoria)
    ("RTX 4060 graphics card",    "gpu",         "GPU"),
    ("RTX 4070 graphics card",    "gpu",         "GPU"),
    ("RTX 5070 graphics card",    "gpu",         "GPU"),
    ("RX 7600 graphics card",     "gpu",         "GPU"),
    ("Ryzen 5 7600 processor",    "cpu",         "CPU"),
    ("Ryzen 7 9700X processor",   "cpu",         "CPU"),
    ("Core i5 13600K processor",  "cpu",         "CPU"),
    ("Core i7 13700K processor",  "cpu",         "CPU"),
    ("DDR5 32GB RAM kit",         "ram",         "RAM"),
    ("DDR4 16GB RAM kit",         "ram",         "RAM"),
    ("NVMe SSD 1TB M.2",          "ssd",         "SSD"),
    ("Samsung 990 Pro SSD",       "ssd",         "SSD"),
    ("B650 motherboard ATX",      "motherboard", "Motherboard"),
    ("Z790 motherboard Intel",    "motherboard", "Motherboard"),
    ("750W 80 Plus Gold PSU",     "psu",         "PSU"),
    ("850W modular power supply", "psu",         "PSU"),
    ("27 inch 1440p monitor",     "monitor",     "Monitor"),
    ("144hz gaming monitor",      "monitor",     "Monitor"),
    ("240mm AIO liquid cooler",   "cooler",      "Cooler"),
    ("Noctua NH-D15 CPU cooler",  "cooler",      "Cooler"),
]

# ── Headers rotativos (anti-bot básico) ──────────────────────────────
HEADERS_POOL = [
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Safari/605.1.15"
        ),
        "Accept-Language": "en-US,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml",
    },
]

def _get_headers():
    return random.choice(HEADERS_POOL)

def _sleep():
    """Pausa aleatoria entre 2-5 segundos (scraping ético)."""
    time.sleep(random.uniform(2.0, 5.0))

# ─────────────────────────────────────────────────────────────────────
# SCRAPER EBAY
# ─────────────────────────────────────────────────────────────────────

def scrape_ebay(query: str, hw_type: str, categoria: str,
                max_items: int = 10) -> list:
    """
    Scraping de eBay Buy It Now (precio fijo, no subasta).
    URL: https://www.ebay.com/sch/i.html?_nkw=QUERY&LH_BIN=1&_sop=15
    LH_BIN=1  → Buy It Now only
    _sop=15   → Sort by Best Match
    """
    resultados = []
    url = (
        f"https://www.ebay.com/sch/i.html"
        f"?_nkw={requests.utils.quote(query)}"
        f"&LH_BIN=1&_sop=15&_ipg=25"
    )

    try:
        resp = requests.get(url, headers=_get_headers(), timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        items = soup.select("li.s-item")
        for item in items[:max_items]:
            try:
                # Título
                title_el = item.select_one(".s-item__title")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if title.lower().startswith("shop on ebay"):
                    continue

                # Precio
                price_el = item.select_one(".s-item__price")
                if not price_el:
                    continue
                price_text = price_el.get_text(strip=True)
                # Limpiar: "$1,234.56" → 1234.56
                price_clean = (price_text
                               .replace("$", "")
                               .replace(",", "")
                               .split(" ")[0]
                               .split("to")[0]
                               .strip())
                price_usd = float(price_clean)
                if price_usd <= 0:
                    continue

                # Shipping
                ship_el = item.select_one(".s-item__shipping")
                shipping_usd = 0.0
                if ship_el:
                    ship_text = ship_el.get_text(strip=True).lower()
                    if "free" in ship_text:
                        shipping_usd = 0.0
                    else:
                        import re
                        nums = re.findall(r"\d+\.?\d*", ship_text)
                        shipping_usd = float(nums[0]) if nums else 20.0
                else:
                    shipping_usd = 20.0  # default si no aparece

                # URL del item
                link_el = item.select_one("a.s-item__link")
                item_url = link_el["href"] if link_el else ""

                # SKU sintético: hash del título
                import hashlib
                sku = "ebay_" + hashlib.md5(title.encode()).hexdigest()[:10]

                resultados.append({
                    "sku":          sku,
                    "title":        title[:120],
                    "price_usd":    round(price_usd, 2),
                    "shipping_usd": round(shipping_usd, 2),
                    "price_pen":    0.0,   # no aplica para fuentes internacionales
                    "source":       "ebay_usa",
                    "category":     categoria,
                    "hw_type":      hw_type,
                    "url":          item_url[:200],
                    "timestamp":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "brand":        "",
                    "rating":       0.0,
                    "reviews":      0,
                })

            except (ValueError, AttributeError, KeyError):
                continue

    except requests.RequestException as e:
        print(f"      ⚠️  eBay error [{query[:30]}]: {e}")

    return resultados


# ─────────────────────────────────────────────────────────────────────
# SCRAPER AMAZON
# ─────────────────────────────────────────────────────────────────────

def scrape_amazon(query: str, hw_type: str, categoria: str,
                  max_items: int = 10) -> list:
    """
    Scraping de Amazon.com resultados de búsqueda.
    Nota: Amazon tiene anti-bot agresivo.
    Usar con delays largos o considerar Amazon Product API.
    """
    resultados = []
    url = (
        f"https://www.amazon.com/s"
        f"?k={requests.utils.quote(query)}"
        f"&s=price-asc-rank"   # ordenar por precio ascendente
    )

    try:
        resp = requests.get(url, headers=_get_headers(), timeout=20)

        # Amazon puede redirigir a CAPTCHA
        if "captcha" in resp.url.lower() or resp.status_code == 503:
            print(f"      ⚠️  Amazon CAPTCHA detectado [{query[:30]}] — omitiendo")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select('[data-component-type="s-search-result"]')

        for item in items[:max_items]:
            try:
                # Título
                title_el = item.select_one("h2 a span")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)

                # Precio (Amazon usa estructura .a-price)
                price_whole = item.select_one(".a-price-whole")
                price_frac  = item.select_one(".a-price-fraction")
                if not price_whole:
                    continue
                price_str = (
                    price_whole.get_text(strip=True).replace(",", "").replace(".", "")
                    + "."
                    + (price_frac.get_text(strip=True) if price_frac else "00")
                )
                price_usd = float(price_str)
                if price_usd <= 0:
                    continue

                # Rating
                rating_el = item.select_one(".a-icon-alt")
                rating = 0.0
                if rating_el:
                    import re
                    nums = re.findall(r"\d+\.?\d*", rating_el.get_text())
                    rating = float(nums[0]) if nums else 0.0

                # Reviews
                rev_el = item.select_one('[aria-label*="stars"] + span')
                reviews = 0
                if rev_el:
                    import re
                    nums = re.findall(r"[\d,]+", rev_el.get_text())
                    reviews = int(nums[0].replace(",", "")) if nums else 0

                # URL
                link_el = item.select_one("h2 a")
                item_url = ("https://www.amazon.com" + link_el["href"]
                            if link_el else "")

                import hashlib
                sku = "amz_" + hashlib.md5(title.encode()).hexdigest()[:10]

                resultados.append({
                    "sku":          sku,
                    "title":        title[:120],
                    "price_usd":    round(price_usd, 2),
                    "shipping_usd": 0.0,   # Amazon Prime = gratis
                    "price_pen":    0.0,
                    "source":       "amazon_usa",
                    "category":     categoria,
                    "hw_type":      hw_type,
                    "url":          item_url[:200],
                    "timestamp":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "brand":        "",
                    "rating":       round(rating, 1),
                    "reviews":      reviews,
                })

            except (ValueError, AttributeError, KeyError):
                continue

    except requests.RequestException as e:
        print(f"      ⚠️  Amazon error [{query[:30]}]: {e}")

    return resultados


# ─────────────────────────────────────────────────────────────────────
# MAIN SCRAPER
# ─────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*60)
    print("  HDS-ROI — Scraper Internacional v1.0")
    print("  Fuentes: eBay USA + Amazon USA")
    print("="*60)

    todos_resultados = []
    total_productos  = len(PRODUCTOS_BUSCAR)

    for i, (query, hw_type, categoria) in enumerate(PRODUCTOS_BUSCAR, 1):
        print(f"\n  [{i:02d}/{total_productos}] {hw_type.upper():<12} {query[:40]}")

        # ── eBay ──────────────────────────────────────────────────────
        print(f"         eBay USA  ...", end=" ", flush=True)
        res_ebay = scrape_ebay(query, hw_type, categoria, max_items=8)
        print(f"{len(res_ebay)} items")
        todos_resultados.extend(res_ebay)
        _sleep()

        # ── Amazon ────────────────────────────────────────────────────
        print(f"         Amazon USA...", end=" ", flush=True)
        res_amz = scrape_amazon(query, hw_type, categoria, max_items=5)
        print(f"{len(res_amz)} items")
        todos_resultados.extend(res_amz)
        _sleep()

    # ── Guardar ───────────────────────────────────────────────────────
    if not todos_resultados:
        print("\n  ❌ Sin resultados. Verifica conexión a internet.")
        return

    df_nuevo = pd.DataFrame(todos_resultados)
    print(f"\n  Total scraped: {len(df_nuevo)} registros")
    print(f"  Distribución HW: {df_nuevo['hw_type'].value_counts().to_dict()}")
    print(f"  Precios medios:")
    print(df_nuevo.groupby(["hw_type","source"])["price_usd"].median()
            .round(2).to_string())

    # Agregar al MASTER existente
    master_path = BASE_DIR / "data" / "raw" / "MASTER_hardware_peru.csv"
    if master_path.exists():
        df_master = pd.read_csv(master_path, low_memory=False)
        print(f"\n  MASTER actual: {len(df_master):,} registros")

        # Evitar duplicados por sku + timestamp
        df_combined = pd.concat([df_master, df_nuevo], ignore_index=True)
        df_combined = df_combined.drop_duplicates(
            subset=["sku", "price_usd", "source"], keep="last")
        df_combined.to_csv(master_path, index=False)
        print(f"  MASTER actualizado: {len(df_combined):,} registros")
    else:
        df_nuevo.to_csv(OUTPUT_PATH, index=False)
        print(f"  Guardado en: {OUTPUT_PATH}")

    print("\n" + "="*60)
    print("  ✅ Scraping completado")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()