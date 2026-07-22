#!/usr/bin/env python3
"""
scraper_pcpartpicker.py  v4.0
PCPartPicker — Playwright + stealth para bypass Cloudflare JS Challenge

Cambios v4.0 (sobre v3.1):
  [PP10] Migración completa requests → Playwright (único fix real para CF)
  [PP11] _make_browser_context(): headless + AutomationControlled desactivado
         + navigator.webdriver = undefined via init_script
  [PP12] _get_products_playwright(): navega URL, espera tbody tr con timeout 15s
  [PP13] Visita '/' primero → extrae cf_clearance → inyecta en requests.Session
         para llamadas a la API de historial
  [PP14] Paginación via ?page=N directo (no /fetch — retorna HTML vacío)
  [PP15] _wait_for_cf_challenge(): espera hasta 20s si detecta "Just a moment"
  [PP16] Selectores CSS actualizados — inspeccionados en HTML real 2026
  [PP17] browser.close() en finally — evita procesos Chromium huérfanos
  [PP18] wait_for_selector(..., timeout=15_000) — tiempo para CF challenge
  [PP5]  price_usd validado con rango [PRICE_MIN_USD, PRICE_MAX_USD] (heredado)
  [PP6]  historial price_usd validado con mismo rango (heredado)
"""

import re
import json
import time
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────
BASE_URL               = "https://pcpartpicker.com"
API_BASE               = f"{BASE_URL}/api/v0"
REQUEST_DELAY          = 2.0        # segundos entre páginas
TIMEOUT                = 20         # requests timeout
PW_TIMEOUT_MS          = 20_000     # playwright timeout ms
CF_WAIT_MS             = 20_000     # espera máxima para CF challenge
MAX_PAGES_PER_CATEGORY = 5

# [PP5] Rango de precio válido en USD
PRICE_MIN_USD = 1.0
PRICE_MAX_USD = 15_000.0

# [PP4] UA consistente con el browser Playwright
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

CATEGORIES = {
    "cpu":                 "/products/cpu/",
    "video-card":          "/products/video-card/",
    "memory":              "/products/memory/",
    "internal-hard-drive": "/products/internal-hard-drive/",
    "motherboard":         "/products/motherboard/",
    "laptop":              "/products/laptop/",
    "monitor":             "/products/monitor/",
    "case":                "/products/case/",
    "power-supply":        "/products/power-supply/",
    "cpu-cooler":          "/products/cpu-cooler/",
}

# ──────────────────────────────────────────────
# [PP11] Browser context con stealth básico
# ──────────────────────────────────────────────
def _make_browser_context(playwright):
    """
    Lanza Chromium headless con flags anti-detección.
    [PP11] navigator.webdriver = undefined via add_init_script
    """
    browser = playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--window-size=1920,1080",
        ],
    )
    context = browser.new_context(
        user_agent=_UA,
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
        timezone_id="America/New_York",
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    # [PP11] Ocultar webdriver
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        window.chrome = { runtime: {} };
    """)
    return browser, context


# ──────────────────────────────────────────────
# [PP15] Esperar resolución de CF challenge
# ──────────────────────────────────────────────
def _wait_for_cf_challenge(page, timeout_ms: int = CF_WAIT_MS):
    """
    Si la página muestra 'Just a moment' (CF challenge),
    espera hasta timeout_ms a que desaparezca.
    """
    try:
        # Si hay challenge, esperar a que el título cambie
        if "just a moment" in page.title().lower():
            logger.info("  [PCPartPicker] CF challenge detectado — esperando resolución...")
            page.wait_for_function(
                "() => !document.title.toLowerCase().includes('just a moment')",
                timeout=timeout_ms,
            )
            logger.info("  [PCPartPicker] CF challenge resuelto ✓")
            time.sleep(1.5)  # pausa extra post-challenge
    except PWTimeout:
        logger.warning("  [PCPartPicker] CF challenge no resuelto en tiempo — continuando")
    except Exception as e:
        logger.debug(f"  [PCPartPicker] _wait_for_cf_challenge: {e}")


# ──────────────────────────────────────────────
# [PP13] Extraer cookies CF del contexto Playwright
# ──────────────────────────────────────────────
def _extract_cf_cookies(context) -> dict:
    """
    Extrae cf_clearance y otras cookies CF del contexto Playwright
    para inyectarlas en requests.Session (historial API).
    """
    cookies = {}
    for c in context.cookies():
        if c["name"] in ("cf_clearance", "xcsrftoken", "__cf_bm"):
            cookies[c["name"]] = c["value"]
    return cookies


# ──────────────────────────────────────────────
# [P1] Session requests con cookies CF
# ──────────────────────────────────────────────
def _make_requests_session(cf_cookies: dict) -> requests.Session:
    session = requests.Session()
    retry   = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    session.headers.update({
        "User-Agent":      _UA,
        "Accept":          "application/json, text/html, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         "https://pcpartpicker.com/",
    })
    # [PP13] Inyectar cookies CF reales
    for name, value in cf_cookies.items():
        session.cookies.set(name, value, domain=".pcpartpicker.com")
    return session


# ──────────────────────────────────────────────
# [PP12] Scraping de productos con Playwright
# ──────────────────────────────────────────────
def _get_products_playwright(context, category: str, path: str) -> list:
    """
    [PP12] Navega cada página de categoría con Playwright.
    [PP14] Usa ?page=N directo (no /fetch).
    [PP16] Selectores CSS actualizados para HTML 2026.
    """
    products  = []
    page      = context.new_page()

    try:
        for page_num in range(1, MAX_PAGES_PER_CATEGORY + 1):
            url = f"{BASE_URL}{path}?page={page_num}"
            logger.debug(f"  [{category}] Navegando p{page_num}: {url}")

            try:
                page.goto(url, timeout=PW_TIMEOUT_MS, wait_until="domcontentloaded")
                _wait_for_cf_challenge(page)

                # [PP18] Esperar tabla de productos
                try:
                    page.wait_for_selector(
                        "#paginated_table tbody tr, tr.tr__product",
                        timeout=PW_TIMEOUT_MS,
                    )
                except PWTimeout:
                    logger.warning(
                        f"  [{category}] p{page_num}: timeout esperando tabla — "
                        f"¿CF no resuelto o página sin productos?"
                    )
                    if page_num == 1:
                        # Guardar HTML para diagnóstico
                        try:
                            html_preview = page.content()[:1000]
                            logger.debug(f"  HTML preview: {html_preview}")
                        except Exception:
                            pass
                    break

                html = page.content()
                soup = BeautifulSoup(html, "html.parser")

                # [PP16] Selectores actualizados
                rows = (
                    soup.select("tr.tr__product") or
                    soup.select("#paginated_table tbody tr") or
                    soup.select("div.productCard") or
                    soup.select("li.product__wrap")
                )

                if not rows:
                    logger.debug(f"  [{category}] p{page_num}: sin filas. Fin paginación.")
                    break

                page_products = []
                for row in rows:
                    try:
                        product = _parse_product_row(row, category)
                        if product:
                            page_products.append(product)
                    except Exception as e:
                        logger.debug(f"  Error parseando fila: {e}")
                        continue

                products.extend(page_products)
                logger.debug(f"  [{category}] p{page_num}: +{len(page_products)} productos")

                # Verificar si hay página siguiente
                next_btn = soup.select_one("a[rel='next'], .pagination__next:not(.disabled)")
                if not next_btn and page_num > 1:
                    logger.debug(f"  [{category}] Sin página siguiente. Fin.")
                    break

                time.sleep(REQUEST_DELAY)

            except PWTimeout:
                logger.warning(f"  [{category}] p{page_num}: timeout de navegación")
                break
            except Exception as e:
                logger.warning(f"  [{category}] p{page_num}: error — {e}")
                break

    finally:
        page.close()

    return products


# ──────────────────────────────────────────────
# Parser de fila (heredado v3.1 — selectores correctos)
# ──────────────────────────────────────────────
def _parse_product_row(row, category: str) -> Optional[dict]:
    name_tag = (
        row.select_one("p.td__name a") or
        row.select_one(".productCard__title a") or
        row.select_one("p.td__title a") or
        row.select_one("td.td__name a")
    )
    if not name_tag:
        return None

    name = name_tag.text.strip()
    if not name:
        return None

    href = name_tag.get("href", "")
    url  = f"{BASE_URL}{href}" if href.startswith("/") else href

    part_id_match = re.search(r"/product/([^/]+)/", href)
    part_id       = part_id_match.group(1) if part_id_match else ""

    price     = None
    price_tag = (
        row.select_one("td.td__price a") or
        row.select_one(".productCard__price") or
        row.select_one("td.td__finalPrice") or
        row.select_one("td.td__price")
    )
    if price_tag:
        price_text  = price_tag.text.strip().replace(",", "")
        price_match = re.search(r"\d+\.?\d*", price_text)
        if price_match:
            try:
                val = float(price_match.group())
                # [PP5] Validar rango
                if PRICE_MIN_USD <= val <= PRICE_MAX_USD:
                    price = val
                else:
                    logger.debug(
                        f"  [PCPartPicker] price={val} fuera de rango — {name[:40]}"
                    )
            except ValueError:
                pass

    rating     = None
    rating_tag = (
        row.select_one("td.td__rating") or
        row.select_one(".productCard__rating")
    )
    if rating_tag:
        m = re.search(r"([\d.]+)", rating_tag.text)
        if m:
            try:
                rating = float(m.group(1))
            except ValueError:
                pass

    reviews     = None
    reviews_tag = row.select_one("td.td__reviews")
    if reviews_tag:
        m = re.search(r"(\d+)", reviews_tag.text.replace(",", ""))
        if m:
            try:
                reviews = int(m.group(1))
            except ValueError:
                pass

    return {
        "name":     name,
        "url":      url,
        "part_id":  part_id,
        "category": category,
        "price":    price,
        "rating":   rating,
        "reviews":  reviews,
    }


# ──────────────────────────────────────────────
# HISTORIAL DE PRECIOS (requests + cookies CF)
# ──────────────────────────────────────────────
def _get_price_history(session: requests.Session, part_id: str) -> list:
    """
    [PP13] Usa session con cf_clearance real → API accesible.
    [PP6]  price_usd validado con rango [PRICE_MIN_USD, PRICE_MAX_USD].
    """
    if not part_id:
        return []

    url     = f"{API_BASE}/prices/{part_id}"
    history = []

    try:
        resp = session.get(url, timeout=TIMEOUT)

        if resp.status_code == 404:
            return []
        if resp.status_code in (401, 403):
            logger.warning(
                f"  [PCPartPicker] API /prices/ → {resp.status_code} "
                f"para {part_id}"
            )
            return []
        if resp.status_code >= 500:
            logger.warning(
                f"  [PCPartPicker] API error {resp.status_code} para {part_id}"
            )
            return []

        # Detectar CF aunque status=200
        content = resp.text.lower()
        if any(k in content for k in ["cloudflare", "just a moment", "cf-ray"]):
            logger.warning(
                f"  [PCPartPicker] CF en historial {part_id} — skip"
            )
            return []

        resp.raise_for_status()
        data        = resp.json()
        prices_data = data.get("prices", {})

        for retailer, price_points in prices_data.items():
            if isinstance(price_points, list):
                for point in price_points:
                    if isinstance(point, (list, tuple)) and len(point) >= 2:
                        try:
                            ts    = int(point[0])
                            price = float(point[1])
                            # [PP6] Validar rango
                            if PRICE_MIN_USD <= price <= PRICE_MAX_USD:
                                history.append({
                                    "retailer":  retailer,
                                    "timestamp": ts,
                                    "date":      datetime.fromtimestamp(
                                        ts, tz=timezone.utc
                                    ).strftime("%Y-%m-%d"),
                                    "price_usd": price,
                                })
                        except (ValueError, TypeError):
                            continue

    except requests.RequestException as e:
        logger.debug(f"  [PCPartPicker] Error historial {part_id}: {e}")
    except (json.JSONDecodeError, KeyError) as e:
        logger.debug(f"  [PCPartPicker] Error JSON {part_id}: {e}")

    return history


# ──────────────────────────────────────────────
# SCRAPER PRINCIPAL
# ──────────────────────────────────────────────
def scrape_pcpartpicker(batch_id: str, mode: str = "normal") -> list:
    """
    Scraper principal PCPartPicker v4.0 — Playwright + stealth.
    [PP10] Playwright para bypass CF JS Challenge.
    [PP13] Cookies CF extraídas y reutilizadas en requests.Session.
    [PP17] browser.close() en finally — evita Chromium huérfanos.
    """
    t_start     = time.time()
    all_records = []
    seen_parts  = set()
    now_iso     = datetime.now(timezone.utc).isoformat()

    with sync_playwright() as pw:
        logger.info("[PCPartPicker] Iniciando browser — obteniendo cookies CF...")
        browser, context = _make_browser_context(pw)

        try:  # [PP17]
            # [PP13] Visita home para obtener cf_clearance
            warmup_page = context.new_page()
            try:
                warmup_page.goto(BASE_URL, timeout=PW_TIMEOUT_MS, wait_until="domcontentloaded")
                _wait_for_cf_challenge(warmup_page)
                time.sleep(1.0)
            finally:
                warmup_page.close()

            cf_cookies = _extract_cf_cookies(context)
            cf_names   = list(cf_cookies.keys())
            logger.info(f"[PCPartPicker] Cookies CF obtenidas: {cf_names}")

            # Session requests con cookies CF para historial
            req_session = _make_requests_session(cf_cookies)

            # ── Scraping por categoría ──
            for category, path in CATEGORIES.items():
                logger.info(f"[PCPartPicker] Categoría: {category}")
                records_before = len(all_records)

                products = _get_products_playwright(context, category, path)
                logger.info(f"  Productos encontrados: {len(products)}")

                for product in products:
                    part_id = product.get("part_id", "")

                    if product.get("price"):
                        all_records.append({
                            "batch_id":   batch_id,
                            "timestamp":  now_iso,
                            "source":     "pcpartpicker_current",
                            "category":   category,
                            "part_id":    part_id,
                            "name":       product["name"],
                            "price_usd":  product["price"],
                            "price_date": now_iso[:10],
                            "retailer":   "pcpartpicker_best",
                            "rating":     product.get("rating"),
                            "reviews":    product.get("reviews"),
                            "url":        product["url"],
                        })

                    if part_id and part_id not in seen_parts:
                        seen_parts.add(part_id)
                        history = _get_price_history(req_session, part_id)
                        for point in history:
                            all_records.append({
                                "batch_id":   batch_id,
                                "timestamp":  now_iso,
                                "source":     "pcpartpicker_history",
                                "category":   category,
                                "part_id":    part_id,
                                "name":       product["name"],
                                "price_usd":  point["price_usd"],
                                "price_date": point["date"],
                                "retailer":   point["retailer"],
                                "rating":     product.get("rating"),
                                "reviews":    product.get("reviews"),
                                "url":        product["url"],
                            })
                        time.sleep(REQUEST_DELAY * 0.5)

                added = len(all_records) - records_before
                logger.info(f"  ✅ {category}: +{added} registros")
                time.sleep(REQUEST_DELAY)

            req_session.close()

        finally:
            context.close()   # [PP17]
            browser.close()   # [PP17]

    elapsed = time.time() - t_start
    logger.info(
        f"[PCPartPicker] TOTAL: {len(all_records)} registros "
        f"— ⏱ {elapsed/60:.1f} min"
    )
    return all_records


# ──────────────────────────────────────────────
# STANDALONE
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_batch = f"test_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    results    = scrape_pcpartpicker(test_batch)
    print(f"\nTotal registros: {len(results)}")
    if results:
        print("Ejemplo:", results[0])
