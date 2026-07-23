r"""
scraper_ripley.py — Ripley PE v1.2
════════════════════════════════════════════════════════════════════
Fixes v1.2 (sobre v1.1):
  [R5] Docstrings con patrones regex (\d, \w, etc.) convertidos a
       raw strings (r\"\"\"...\"\"\") — Python 3.12 emite
       SyntaxWarning: invalid escape sequence para backslashes en
       docstrings normales. Afectaba línea 1 (módulo) y línea 84
       (_parse_product). Sin este fix el intérprete muestra warnings
       en cada import, contaminando logs de producción.

Fixes v1.1 (sobre v1.0):
  [R1] Regex de product_id extendido: -(\d{13})p  y  pmp(\d{10,})
  [R2] Log de productos descartados por ID vacío (auditoría)
  [R3] Firma scrape_ripley(batch_id, mode=) compatible con [O17]
  [R4] Campos canónicos: title, sku, price_orig_pen, price_currency

Fuente : https://simple.ripley.com.pe
Método : requests + BeautifulSoup (server-side HTML)
Estructura confirmada (diagnóstico 2026-07-23):
  a.product-link
    └─ div > div > article.product-item-horizontal
         ├─ p.product-item-horizontal__name
         ├─ span.product-item-horizontal__brand
         ├─ span.product-price-price
         ├─ span.product-price-old-price
         ├─ span.product-price-discount
         └─ div.product-stars--container[aria-label]
"""

import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

BASE_URL = "https://simple.ripley.com.pe"

CATEGORIES = {
    "laptops":             "/tecnologia/computacion/laptops",
    "computadoras":        "/tecnologia/computacion/computadoras-de-escritorio",
    "monitores":           "/tecnologia/computacion/monitores",
    "disco_duro_memorias": "/tecnologia/computacion/disco-duro-y-memorias",
    "tablets":             "/tecnologia/computacion/tablets",
}

MAX_PAGES_PER_CATEGORY = 25
DELAY_BETWEEN_PAGES    = 1.5

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-PE,es;q=0.9",
    "Referer":         "https://simple.ripley.com.pe/",
}


def _parse_price(text: str) -> float | None:
    """'S/ 3,299.00' -> 3299.0"""
    if not text:
        return None
    clean = re.sub(r"[^\d.]", "", text.replace(",", ""))
    try:
        return float(clean) if clean else None
    except ValueError:
        return None


def _parse_product(link_tag, category: str, batch_id: str) -> dict | None:
    r"""
    Recibe el <a class='product-link'> y extrae todos los campos.
    Estructura confirmada:
      a.product-link > div > div > article.product-item-horizontal

    [R1] Regex extendido para capturar ambos patrones de product_id:
         -(\d{13})p  y  pmp(\d{10,})
    [R4] Campos alineados con FIELD_ORDER canónico de main.py v5.11.
    [R5] Docstring convertido a raw string — evita SyntaxWarning en
         Python 3.12 por backslashes en \d.
    """
    try:
        # ── URL e ID ──────────────────────────────────────────────────
        href = link_tag.get("href", "")
        url_clean = BASE_URL + href.split("?")[0] if href else ""

        # [R1] Doble patrón: clásico (-\d{13}p) y nuevo (pmp\d{10,})
        id_m = (
            re.search(r"-(\d{13})p", href)
            or re.search(r"pmp(\d{10,})", href)
        )
        product_id = id_m.group(1) if id_m else ""

        # ── Artículo interno ──────────────────────────────────────────
        # select_one busca en profundidad — funciona aunque article
        # no sea hijo directo del <a> (confirmado en diagnóstico)
        article = link_tag.select_one("article.product-item-horizontal")
        if not article:
            return None

        # ── Nombre ────────────────────────────────────────────────────
        name_tag = article.select_one("p.product-item-horizontal__name")
        title = ""
        if name_tag:
            title = name_tag.get("title") or name_tag.get_text(strip=True)
        if not title:
            return None

        # ── Marca ─────────────────────────────────────────────────────
        brand_tag = article.select_one("span.product-item-horizontal__brand")
        brand = brand_tag.get_text(strip=True) if brand_tag else ""

        # ── Precio actual ─────────────────────────────────────────────
        price_tag = article.select_one("span.product-price-price")
        price_pen = (
            _parse_price(price_tag.get_text(strip=True)) if price_tag else None
        )

        # ── Precio original ───────────────────────────────────────────
        orig_tag = article.select_one("span.product-price-old-price")
        price_orig_pen = (
            _parse_price(orig_tag.get_text(strip=True)) if orig_tag else None
        )

        # ── Descuento % ('-23%' -> 23) ────────────────────────────────
        disc_tag = article.select_one("span.product-price-discount")
        discount = None
        if disc_tag:
            dm = re.search(r"(\d+)", disc_tag.get_text())
            discount = int(dm.group(1)) if dm else None

        # ── Rating ────────────────────────────────────────────────────
        stars = article.select_one("div.product-stars--container")
        rating = None
        if stars:
            aria = stars.get("aria-label", "")
            sm = re.search(r"([\d.]+)", aria)
            rating = float(sm.group(1)) if sm else None

        # ── Timestamp y price_date ─────────────────────────────────────
        now        = datetime.now(timezone.utc)
        timestamp  = now.isoformat()
        price_date = now.strftime("%Y-%m-%d")

        # [R4] Campos alineados con FIELD_ORDER canónico
        return {
            "batch_id":       batch_id,
            "timestamp":      timestamp,
            "source":         "ripley_pe",
            "category":       category,
            "sku":            product_id,
            "brand":          brand,
            "title":          title,
            "price_pen":      price_pen,
            "price_orig_pen": price_orig_pen,
            "price_usd":      None,
            "price_date":     price_date,
            "discount_pct":   discount,
            "price_currency": "PEN",
            "rating":         rating,
            "reviews":        None,
            "retailer":       "Ripley PE",
            "url":            url_clean,
        }
    except Exception as e:
        logger.debug(f"  [ripley] Error parseando producto: {e}")
        return None


def _scrape_category(
    session: requests.Session,
    cat_name: str,
    cat_path: str,
    batch_id: str,
) -> list[dict]:
    """Scrape todas las páginas de una categoria."""
    results  = []
    seen_ids = set()

    for page in range(1, MAX_PAGES_PER_CATEGORY + 1):
        url = f"{BASE_URL}{cat_path}?page={page}"
        try:
            r = session.get(url, timeout=20)
            if r.status_code != 200:
                logger.warning(
                    f"  [{cat_name}] p{page} -> HTTP {r.status_code}, deteniendo"
                )
                break

            soup  = BeautifulSoup(r.text, "html.parser")
            links = soup.select("a.product-link")

            if not links:
                logger.info(f"  [{cat_name}] p{page} -> sin links, fin")
                break

            new_in_page   = 0
            skipped_no_id = 0   # [R2] auditoria

            for link in links:
                prod = _parse_product(link, cat_name, batch_id)
                if not prod:
                    continue
                if not prod["sku"]:
                    skipped_no_id += 1   # [R2]
                    continue
                if prod["sku"] in seen_ids:
                    continue
                seen_ids.add(prod["sku"])
                results.append(prod)
                new_in_page += 1

            # [R2] Log extendido con auditoria de descartados
            logger.info(
                f"  [{cat_name}] p{page} -> {len(links)} links, "
                f"+{new_in_page} nuevos, "
                f"{skipped_no_id} sin ID "
                f"(total: {len(results)})"
            )

            if new_in_page == 0:
                logger.info(
                    f"  [{cat_name}] Solo duplicados en p{page}, deteniendo"
                )
                break

            time.sleep(DELAY_BETWEEN_PAGES)

        except Exception as e:
            logger.error(f"  [{cat_name}] p{page} ERROR: {e}")
            break

    return results


def scrape_ripley(batch_id: str, mode: str = "normal") -> list[dict]:
    """Entry point principal — llamado desde main.py (orquestador v5.11).
    [R3] Firma actualizada: batch_id + mode= para compatibilidad [O17].
    """
    logger.info(f"[Ripley PE] Iniciando scraper v1.2 (mode={mode})...")
    t0 = time.time()

    session = requests.Session()
    session.headers.update(HEADERS)

    all_results: list[dict] = []
    for cat_name, cat_path in CATEGORIES.items():
        logger.info(f"[Ripley PE] Categoria: {cat_name}")
        cat_results = _scrape_category(session, cat_name, cat_path, batch_id)
        logger.info(f"  v {cat_name}: {len(cat_results)} registros")
        all_results.extend(cat_results)

    elapsed = (time.time() - t0) / 60
    logger.info(
        f"[Ripley PE] TOTAL: {len(all_results)} registros — {elapsed:.1f} min"
    )
    return all_results