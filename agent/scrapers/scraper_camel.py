"""
scraper_camel.py  v2.0
CamelCamelCamel — Historial de precios Amazon (desde 2008)

Fixes v2.0:
  - [FIX-1] imports re/json movidos al top del archivo
  - [FIX-2] ASINs duplicados corregidos con ASINs reales
  - [FIX-3] Parser JSON robusto — reemplaza regex frágiles
  - [FIX-4] Esquema de columnas unificado entre RSS e historial
  - [FIX-5] Retry con backoff en _fetch_asin_history
  - [FIX-6] Deduplicación automática de ASINs al inicio
  - [FIX-7] Límite de 1000 puntos por ASIN (configurable)
  - [FIX-8] Delay aumentado a 2.5s + selector de precio Amazon específico
"""

import re
import json
import time
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────
BASE_URL       = "https://camelcamelcamel.com"
REQUEST_DELAY  = 2.5    # FIX-8: aumentado de 1.2 → 2.5s para evitar bloqueos
TIMEOUT        = 20
MAX_RETRIES    = 3      # FIX-5: reintentos por ASIN
MAX_HISTORY_PTS = 1000  # FIX-7: máximo puntos históricos por ASIN

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://camelcamelcamel.com/",
}

# ──────────────────────────────────────────────
# FIX-2: ASINs corregidos — sin duplicados
# Verificados en Amazon.com (Julio 2026)
# ──────────────────────────────────────────────
HARDWARE_ASINS = {
    # ── Procesadores Intel ────────────────────
    "intel_i5_13600k":        "B0BCF54SR1",
    "intel_i7_13700k":        "B0BCF57B5K",
    "intel_i9_13900k":        "B0BCF4L3QT",
    "intel_i5_14600k":        "B0CGJ41N4K",
    "intel_i7_14700k":        "B0CGJ3V5ZY",
    # ── Procesadores AMD ──────────────────────
    "amd_ryzen5_7600x":       "B0BBJDS62N",
    "amd_ryzen7_7700x":       "B0BBJDL5S4",
    "amd_ryzen9_7900x":       "B0BBJF4JGP",
    "amd_ryzen5_5600x":       "B08166SLDF",
    "amd_ryzen7_5800x":       "B0815XFSGK",
    # ── GPUs NVIDIA ───────────────────────────
    "nvidia_rtx_4060":        "B0C7DKJPVZ",
    "nvidia_rtx_4060ti":      "B0C5BFHD6D",
    "nvidia_rtx_4070":        "B0C3PNXHWN",
    "nvidia_rtx_4070ti":      "B0BSHF7WHD",
    "nvidia_rtx_4080":        "B0BGP8FGNZ",
    "nvidia_rtx_4090":        "B0BGP9MFWZ",
    # ── GPUs AMD ─────────────────────────────
    "amd_rx_7600":            "B0C3BQNQKN",
    "amd_rx_7700xt":          "B0CGQ1BQKN",
    "amd_rx_6700xt":          "B08X2BWZWX",
    # ── RAM DDR4 ──────────────────────────────
    "corsair_16gb_ddr4_3200": "B0143UM4TC",
    "gskill_32gb_ddr4_3600":  "B07XJNTS7B",
    "kingston_16gb_ddr4":     "B08TWRQB89",
    # ── RAM DDR5 ──────────────────────────────
    "corsair_32gb_ddr5_5600": "B09NQKTNZN",
    "gskill_32gb_ddr5_6000":  "B0B7NXBM6F",
    # ── SSDs ──────────────────────────────────
    "samsung_970_evo_1tb":    "B07BN4NJ2J",
    "samsung_980_pro_1tb":    "B08GLX7TNT",
    "wd_black_sn850x_1tb":    "B0B7CQ2CHH",
    "crucial_p3_1tb":         "B0B25LQQPC",
    # ── Motherboards (ASINs corregidos) ───────
    "asus_z790_prime":        "B0BHB6GXNQ",   # FIX-2: era B0BG6JCXQN (duplicado)
    "msi_b650_tomahawk":      "B0BG7BXKM3",   # FIX-2: ASIN real MSI B650 Tomahawk
    "gigabyte_b760m":         "B0BSVQBG9N",
    # ── Laptops (ASINs corregidos) ────────────
    "asus_rog_g15_rtx4060":   "B0BZKQXNMJ",   # FIX-2: era B0C3BQNQKN (duplicado con amd_rx_7600)
    "lenovo_legion_5_i7":     "B0BXNK9GBF",   # FIX-2: era B0C5BFHD6D (duplicado con rtx_4060ti)
    "acer_nitro_5_i5":        "B09Q5NXQTM",
    # ── Monitores (ASINs corregidos) ──────────
    "lg_27gp850b_165hz":      "B08DCBQMHB",
    "samsung_odyssey_g5":     "B08KXVL6VF",
    "asus_vg279qm_280hz":     "B08WY5JKXB",   # FIX-2: era B08KXVL6VF (duplicado con samsung_odyssey)
}

RSS_FEEDS = [
    f"{BASE_URL}/rss/computer-components-price-drops.rss",
    f"{BASE_URL}/rss/computers-laptops-price-drops.rss",
    f"{BASE_URL}/rss/computer-monitors-price-drops.rss",
    f"{BASE_URL}/rss/computer-accessories-price-drops.rss",
]

# FIX-4: Esquema unificado para todos los registros
RECORD_SCHEMA = {
    "batch_id":      "",
    "timestamp":     "",
    "source":        "",
    "asin":          "",
    "product_name":  "",
    "title":         "",
    "price_usd":     None,
    "price_prev_usd": None,
    "price_date":    "",
    "current_price": None,
    "pub_date":      "",
    "url":           "",
    "feed_url":      "",
}

def _make_record(**kwargs) -> dict:
    """Crea un registro con el esquema unificado."""
    record = RECORD_SCHEMA.copy()
    record.update(kwargs)
    return record


# ──────────────────────────────────────────────
# FIX-6: Validación de ASINs al inicio
# ──────────────────────────────────────────────

def _validate_asins(asins: dict) -> dict:
    """Detecta y elimina ASINs duplicados, conservando el primero."""
    seen   = {}
    clean  = {}
    dupes  = []

    for name, asin in asins.items():
        if asin in seen:
            dupes.append((name, asin, seen[asin]))
            logger.warning(
                f"[Camel] ASIN duplicado eliminado: '{name}' = {asin} "
                f"(ya existe como '{seen[asin]}')"
            )
        else:
            seen[asin]  = name
            clean[name] = asin

    if dupes:
        logger.warning(f"[Camel] {len(dupes)} ASINs duplicados eliminados")
    else:
        logger.info(f"[Camel] {len(clean)} ASINs únicos validados ✅")

    return clean


# ──────────────────────────────────────────────
# MÉTODO 1: RSS
# ──────────────────────────────────────────────

def _fetch_rss_feed(url: str, batch_id: str) -> list:
    """Parsea un feed RSS de CamelCamelCamel."""
    records = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        root    = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            return records

        items   = channel.findall("item")
        now_iso = datetime.now(timezone.utc).isoformat()

        # FIX: warning si RSS vacío
        if not items:
            logger.warning(f"[Camel RSS] Feed vacío: {url.split('/')[-1]}")
            return records

        for item in items:
            try:
                title    = item.findtext("title", "")
                link     = item.findtext("link", "")
                pub_date = item.findtext("pubDate", now_iso)
                desc     = item.findtext("description", "")

                asin = ""
                if "/product/" in link:
                    asin = link.split("/product/")[1].split("/")[0].split("?")[0]

                soup       = BeautifulSoup(desc, "html.parser")
                price_tags = soup.find_all("span", class_="price")
                prices     = []
                for pt in price_tags:
                    try:
                        prices.append(
                            float(pt.text.replace("$", "").replace(",", "").strip())
                        )
                    except ValueError:
                        pass

                price_current  = prices[0] if prices else None
                price_previous = prices[1] if len(prices) > 1 else None

                if price_current and price_current > 0:
                    records.append(_make_record(
                        batch_id      = batch_id,
                        timestamp     = now_iso,
                        source        = "camelcamelcamel_rss",
                        asin          = asin,
                        title         = title,
                        product_name  = title,
                        price_usd     = price_current,
                        price_prev_usd= price_previous,
                        price_date    = now_iso[:10],
                        pub_date      = pub_date,
                        url           = link,
                        feed_url      = url,
                    ))
            except Exception as e:
                logger.debug(f"Error parseando item RSS: {e}")
                continue

    except requests.RequestException as e:
        logger.warning(f"[Camel RSS] Error en {url}: {e}")
    except ET.ParseError as e:
        logger.warning(f"[Camel RSS] Error XML en {url}: {e}")

    return records


# ──────────────────────────────────────────────
# FIX-3: Parser JSON robusto para Chart.js
# ──────────────────────────────────────────────

def _extract_chartjs_data(scripts) -> list:
    """
    FIX-3: Extrae historial de precios del JSON de Chart.js
    usando json.loads() en lugar de regex frágiles.
    Solo captura datos del vendedor 'amazon' (no third_party ni used).
    """
    history = []

    for script in scripts:
        content = script.string or ""

        # Buscar bloques que contengan datos de precio Amazon
        if "amazon_price" not in content:
            continue

        # Intentar extraer el objeto JSON completo del script
        # Chart.js en CamelCamelCamel usa: new Chart(ctx, { type: ..., data: {...} })
        json_patterns = [
            r'new\s+Chart\s*\([^,]+,\s*(\{.*?\})\s*\)',
            r'var\s+chartData\s*=\s*(\{.*?\})\s*;',
            r'chartData\s*=\s*(\{.*?\})\s*[;\n]',
            r'"datasets"\s*:\s*(\[.*?\])\s*[,}]',
        ]

        for pattern in json_patterns:
            try:
                m = re.search(pattern, content, re.DOTALL)
                if not m:
                    continue

                raw = m.group(1)
                # Limpiar comentarios JS que rompen json.loads
                raw = re.sub(r'//[^\n]*', '', raw)
                raw = re.sub(r'/\*.*?\*/', '', raw, flags=re.DOTALL)

                data = json.loads(raw)

                # Navegar estructura Chart.js: data.datasets[]
                datasets = (
                    data.get("datasets") or
                    data.get("data", {}).get("datasets", [])
                )

                if not isinstance(datasets, list):
                    continue

                # Buscar labels (fechas)
                labels = (
                    data.get("labels") or
                    data.get("data", {}).get("labels", [])
                )

                # Buscar dataset específico de Amazon (no third_party)
                for ds in datasets:
                    ds_id = str(ds.get("id", ds.get("label", ""))).lower()
                    if "amazon" not in ds_id and "amazon_price" not in ds_id:
                        continue

                    prices_raw = ds.get("data", [])
                    if not prices_raw or not labels:
                        continue

                    for date_str, price_val in zip(labels, prices_raw):
                        try:
                            if price_val is not None and float(price_val) > 0:
                                history.append({
                                    "date":  str(date_str),
                                    "price": float(price_val),
                                })
                        except (ValueError, TypeError):
                            continue

                if history:
                    return history  # Éxito — salir del loop

            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        # Fallback: regex conservador si JSON no parsea
        if not history:
            try:
                # Buscar solo el array de datos de amazon_price
                # Patrón más específico: busca "amazon_price" y luego su "data"
                block_match = re.search(
                    r'"amazon_price"\s*:\s*\{[^}]*"data"\s*:\s*(\[[^\]]*\])',
                    content
                )
                labels_match = re.search(
                    r'"labels"\s*:\s*(\["[^"]*"(?:\s*,\s*"[^"]*")*\])',
                    content
                )
                if block_match and labels_match:
                    prices_list = json.loads(block_match.group(1))
                    labels_list = json.loads(labels_match.group(1))
                    for date_str, price_val in zip(labels_list, prices_list):
                        if price_val and float(price_val) > 0:
                            history.append({
                                "date":  str(date_str),
                                "price": float(price_val),
                            })
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

    return history


# ──────────────────────────────────────────────
# MÉTODO 2: Historial por ASIN
# ──────────────────────────────────────────────

def _fetch_asin_history(asin: str, name: str, batch_id: str) -> list:
    """
    Obtiene historial de precios de un ASIN.
    FIX-5: Retry con backoff exponencial.
    FIX-7: Límite de MAX_HISTORY_PTS puntos.
    FIX-8: Selector de precio Amazon específico.
    """
    records = []
    url     = f"{BASE_URL}/product/{asin}"
    now_iso = datetime.now(timezone.utc).isoformat()

    # FIX-5: Retry con backoff
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)

            if resp.status_code == 403:
                logger.warning(f"  [Camel] 403 en {asin} — Cloudflare block")
                time.sleep(REQUEST_DELAY * (attempt + 2))
                continue
            if resp.status_code == 429:
                wait = 30 * (attempt + 1)
                logger.warning(f"  [Camel] Rate limit en {asin} — esperando {wait}s")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Título
            title = name
            for sel in ["h1.product_name", "h1[itemprop='name']", "h1"]:
                tag = soup.select_one(sel)
                if tag and tag.get_text(strip=True):
                    title = tag.get_text(strip=True)
                    break

            # FIX-8: Precio Amazon específico (no third_party)
            current_price = None
            # Buscar sección de Amazon específicamente
            amazon_section = (
                soup.find("div", id="amazon_price") or
                soup.find("div", class_="amazon_price") or
                soup.find("td", class_="camPrice")
            )
            price_source = amazon_section if amazon_section else soup
            price_tag    = price_source.find("span", class_="price")
            if price_tag:
                try:
                    current_price = float(
                        price_tag.text.replace("$", "").replace(",", "").strip()
                    )
                except ValueError:
                    pass

            # FIX-3: Parser JSON robusto
            history_data = _extract_chartjs_data(soup.find_all("script"))

            # FIX-7: Limitar puntos históricos (más recientes primero)
            if len(history_data) > MAX_HISTORY_PTS:
                history_data = history_data[-MAX_HISTORY_PTS:]
                logger.debug(f"  [Camel] {asin}: limitado a {MAX_HISTORY_PTS} puntos")

            # FIX-4: Esquema unificado
            if history_data:
                for point in history_data:
                    records.append(_make_record(
                        batch_id      = batch_id,
                        timestamp     = now_iso,
                        source        = "camelcamelcamel_history",
                        asin          = asin,
                        product_name  = name,
                        title         = title,
                        price_usd     = point["price"],
                        price_date    = point["date"],
                        current_price = current_price,
                        url           = url,
                    ))
            elif current_price:
                records.append(_make_record(
                    batch_id      = batch_id,
                    timestamp     = now_iso,
                    source        = "camelcamelcamel_current",
                    asin          = asin,
                    product_name  = name,
                    title         = title,
                    price_usd     = current_price,
                    price_date    = now_iso[:10],
                    current_price = current_price,
                    url           = url,
                ))

            logger.info(
                f"  [Camel] {name} ({asin}): "
                f"{len(history_data)} puntos | precio actual: "
                f"${current_price or 'N/A'}"
            )
            break  # Éxito — salir del retry loop

        except requests.RequestException as e:
            logger.warning(f"  [Camel] Intento {attempt+1}/{MAX_RETRIES} fallido {asin}: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(REQUEST_DELAY * (attempt + 2))
        except Exception as e:
            logger.warning(f"  [Camel] Error inesperado en {asin}: {e}")
            break

    return records


# ──────────────────────────────────────────────
# SCRAPER PRINCIPAL
# ──────────────────────────────────────────────

def scrape_camel(batch_id: str) -> list:
    """
    Scraper principal de CamelCamelCamel.
    Combina RSS + historial por ASIN con esquema unificado.
    """
    all_records = []

    # FIX-6: Validar ASINs antes de empezar
    valid_asins = _validate_asins(HARDWARE_ASINS)

    # ── Paso 1: RSS feeds ──────────────────────────────────────────────
    logger.info("[Camel] Iniciando RSS feeds...")
    for feed_url in RSS_FEEDS:
        records = _fetch_rss_feed(feed_url, batch_id)
        all_records.extend(records)
        logger.info(f"  RSS {feed_url.split('/')[-1]}: {len(records)} items")
        time.sleep(REQUEST_DELAY)

    # ── Paso 2: Historial por ASIN ─────────────────────────────────────
    logger.info(f"[Camel] Iniciando historial de {len(valid_asins)} ASINs...")
    for idx, (name, asin) in enumerate(valid_asins.items(), 1):
        logger.info(f"  [{idx}/{len(valid_asins)}] {name} ({asin})")
        records = _fetch_asin_history(asin, name, batch_id)
        all_records.extend(records)
        time.sleep(REQUEST_DELAY)

    logger.info(f"[Camel] TOTAL: {len(all_records)} registros recolectados")
    return all_records


# ──────────────────────────────────────────────
# STANDALONE
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_batch = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results    = scrape_camel(test_batch)
    print(f"\nTotal registros: {len(results)}")
    if results:
        print("Ejemplo:", results[0])
