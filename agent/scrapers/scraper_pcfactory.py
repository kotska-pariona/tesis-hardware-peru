"""Scraper PC Factory PE v3.3"""
import asyncio, time
from datetime import datetime
from pathlib import Path
import pandas as pd
import requests
from playwright.async_api import async_playwright

BASE_API   = "https://api.pcfactory.com.pe"
BANNERS_EP = BASE_API + "/pcfactory-services-catalogo/v1/catalogo/productos/banners"
SITE_URL   = "https://www.pcfactory.com.pe"
CHUNK_SIZE = 20
SCROLL_PAUSE = 2.0

CATEGORIES = {
    "cpu":     "/categoria/componentes-para-pc/procesadores",
    "gpu":     "/categoria/componentes-para-pc/tarjetas-graficas",
    "ram":     "/categoria/componentes-para-pc/memorias-ram",
    "storage": "/categoria/componentes-para-pc/memorias-almacenamiento",
    "mobo":    "/categoria/componentes-para-pc/placas-madre",
    "psu":     "/categoria/componentes-para-pc/fuentes-de-poder-psu",
    "case":    "/categoria/componentes-para-pc/gabinetes-para-pc",
    "cooling": "/categoria/componentes-para-pc/sistemas-refrigeracion-cpu",
    "monitor": "/categoria/monitores-y-proyectores/monitores",
    "laptop":  "/categoria/computadores-tablets/laptops",
}

HEADERS_API = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, */*",
    "Referer": "https://www.pcfactory.com.pe/",
    "Origin":  "https://www.pcfactory.com.pe",
}

# JS ejecutado en el browser: .products__item ES el <a>, leemos su href directamente
JS_IDS = (
    "() => {"
    "  const s = new Set();"
    "  document.querySelectorAll('.products__item').forEach(el => {"
    "    const m = (el.href || '').match(/\\/producto\\/(\\d+)/);"
    "    if (m) s.add(+m[1]);"
    "  });"
    "  return [...s];"
    "}"
)

def clean_price(val):
    if val is None:
        return None
    try:
        return float(str(val).replace("S/", "").replace(",", "").strip())
    except Exception:
        return None

def get_main_image(imagenes):
    if not imagenes:
        return ""
    if isinstance(imagenes, dict):
        first = imagenes.get("0", {})
        if isinstance(first, dict):
            for res in ["500", "400", "350", "250", "150"]:
                if res in first:
                    return first[res]
            return next(iter(first.values()), "")
    if isinstance(imagenes, list) and imagenes:
        first = imagenes[0]
        if isinstance(first, dict):
            return first.get("url", first.get("250", ""))
        return str(first)
    return ""

def fetch_products_by_ids(ids):
    results = []
    for i in range(0, len(ids), CHUNK_SIZE):
        chunk = ids[i:i + CHUNK_SIZE]
        params = [("productsIds", pid) for pid in chunk]
        try:
            r = requests.get(BANNERS_EP, params=params, headers=HEADERS_API, timeout=15)
            if r.status_code == 200:
                results.extend(r.json())
            else:
                print("    banners", r.status_code)
        except Exception as e:
            print("    fetch error:", e)
        time.sleep(0.3)
    return results

def parse_product(raw, hw_type, link):
    precio  = raw.get("precio",  {}) or {}
    marca   = raw.get("marca",   {}) or {}
    familia = raw.get("familia", {}) or {}
    return {
        "source":          "pcfactory",
        "hw_type":         hw_type,
        "product_id":      str(raw.get("id", "")),
        "name":            raw.get("nombre", "").strip(),
        "brand":           marca.get("nombre", "").strip(),
        "category":        familia.get("nombre", "").strip(),
        "slug":            link.lstrip("/"),
        "price_normal":    clean_price(precio.get("normal")),
        "price_cash":      clean_price(precio.get("efectivo")),
        "price_debit":     clean_price(precio.get("debito")),
        "price_reference": clean_price(precio.get("referencia")),
        "price_discount":  clean_price(precio.get("descuento")),
        "url":             SITE_URL + "/producto/" + str(raw.get("id", "")),
        "image":           get_main_image(raw.get("imagenes")),
        "scraped_at":      datetime.now().isoformat(),
    }

async def scrape_category_ids(link, hw_type):
    """Navega con ?size=200 para cargar todos los productos en una sola pagina."""
    ids = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=HEADERS_API["User-Agent"],
            extra_http_headers={"Accept-Language": "es-PE,es;q=0.9"}
        )
        page = await ctx.new_page()
        try:
            full_url = SITE_URL + link + "?size=200"
            print("    ->", full_url)
            await page.goto(full_url, wait_until="networkidle", timeout=45000)
            if page.url.rstrip("/").replace("?size=200", "") == SITE_URL.rstrip("/"):
                print("    WARN: redirigió al home")
                return []
            await page.wait_for_selector(".products__item", timeout=20000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2.0)
            n = await page.evaluate("document.querySelectorAll('.products__item').length")
            print("    items en DOM:", n)
            raw_ids = await page.evaluate(JS_IDS)
            ids = [i for i in raw_ids if i]
            print("    OK", len(ids), "IDs unicos")
        except Exception as e:
            print("    ERROR:", e)
        finally:
            await browser.close()
    return ids

async def scrape_all():
    all_products = []
    for hw_type, link in CATEGORIES.items():
        print()
        print("=" * 50)
        print("  [" + hw_type.upper() + "]", link)
        print("=" * 50)
        ids = await scrape_category_ids(link, hw_type)
        if not ids:
            print("  Sin IDs — saltando")
            continue
        raws = fetch_products_by_ids(ids)
        print("    API ->", len(raws), "productos")
        for raw in raws:
            all_products.append(parse_product(raw, hw_type, link))
        print("  OK", len(raws), "procesados")
        await asyncio.sleep(1)
    df = pd.DataFrame(all_products)
    print("TOTAL:", len(df))
    return df

def run():
    return asyncio.run(scrape_all())

if __name__ == "__main__":
    import sys
    test_hw = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--cat=")), None)
    if "--test" in sys.argv or test_hw:
        hw   = test_hw or "cpu"
        link = CATEGORIES.get(hw, CATEGORIES["cpu"])
        async def test():
            print("=== TEST [" + hw.upper() + "]", link)
            ids = await scrape_category_ids(link, hw)
            print("IDs[:10]:", ids[:10])
            if not ids:
                return
            raws = fetch_products_by_ids(ids[:8])
            print()
            for raw in raws:
                p  = parse_product(raw, hw, link)
                pn = p["price_normal"] or 0
                pc = p["price_cash"]   or 0
                print(
                    str(p["product_id"]).ljust(7),
                    ("S/" + str(round(pn, 2))).rjust(10),
                    ("S/" + str(round(pc, 2))).rjust(10),
                    p["brand"].ljust(14),
                    p["name"][:40]
                )
            if raws:
                p0 = parse_product(raws[0], hw, link)
                print("Imagen:", p0["image"])
                print("URL:   ", p0["url"])
        asyncio.run(test())
    else:
        df  = run()
        out = Path("data/raw/pcfactory_latest.csv")
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False, encoding="utf-8-sig")
        print("Guardado:", out, "(", len(df), "filas)")
        print(df[["hw_type", "name", "price_normal", "price_cash", "brand"]].head(10).to_string())
