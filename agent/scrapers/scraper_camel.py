"""
scraper_camel.py
CamelCamelCamel — Historial de precios Amazon (desde 2008)

Estrategia dual:
  1. RSS feed público  → últimas bajadas de precio (sin API key)
  2. JSON endpoint     → historial completo por ASIN (sin API key)

No requiere credenciales. Rate limit: ~1 req/seg recomendado.
"""

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
BASE_URL      = "https://camelcamelcamel.com"
REQUEST_DELAY = 1.2   # segundos — respetar rate limit
TIMEOUT       = 20

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

# ASINs de productos de hardware populares en Amazon USA
# Formato: { "nombre_descriptivo": "ASIN" }
HARDWARE_ASINS = {
    # Procesadores Intel
    "intel_i5_13600k":       "B0BCF54SR1",
    "intel_i7_13700k":       "B0BCF57B5K",
    "intel_i9_13900k":       "B0BCF4L3QT",
    "intel_i5_14600k":       "B0CGJ41N4K",
    "intel_i7_14700k":       "B0CGJ3V5ZY",
    # Procesadores AMD
    "amd_ryzen5_7600x":      "B0BBJDS62N",
    "amd_ryzen7_7700x":      "B0BBJDL5S4",
    "amd_ryzen9_7900x":      "B0BBJF4JGP",
    "amd_ryzen5_5600x":      "B08166SLDF",
    "amd_ryzen7_5800x":      "B0815XFSGK",
    # GPUs NVIDIA
    "nvidia_rtx_4060":       "B0C7DKJPVZ",
    "nvidia_rtx_4060ti":     "B0C5BFHD6D",
    "nvidia_rtx_4070":       "B0C3PNXHWN",
    "nvidia_rtx_4070ti":     "B0BSHF7WHD",
    "nvidia_rtx_4080":       "B0BGP8FGNZ",
    "nvidia_rtx_4090":       "B0BGP9MFWZ",
    # GPUs AMD
    "amd_rx_7600":           "B0C3BQNQKN",
    "amd_rx_7700xt":         "B0CGQ1BQKN",
    "amd_rx_6700xt":         "B08X2BWZWX",
    # RAM DDR4
    "corsair_16gb_ddr4_3200": "B0143UM4TC",
    "gskill_32gb_ddr4_3600":  "B07XJNTS7B",
    "kingston_16gb_ddr4":     "B08TWRQB89",
    # RAM DDR5
    "corsair_32gb_ddr5_5600": "B09NQKTNZN",
    "gskill_32gb_ddr5_6000":  "B0B7NXBM6F",
    # SSDs
    "samsung_970_evo_1tb":    "B07BN4NJ2J",
    "samsung_980_pro_1tb":    "B08GLX7TNT",
    "wd_black_sn850x_1tb":    "B0B7CQ2CHH",
    "crucial_p3_1tb":         "B0B25LQQPC",
    # Motherboards
    "asus_z790_prime":        "B0BG6JCXQN",
    "msi_b650_tomahawk":      "B0BG6JCXQN",
    "gigabyte_b760m":         "B0BSVQBG9N",
    # Laptops
    "asus_rog_g15_rtx4060":   "B0C3BQNQKN",
    "lenovo_legion_5_i7":     "B0C5BFHD6D",
    "acer_nitro_5_i5":        "B09Q5NXQTM",
    # Monitores
    "lg_27gp850b_165hz":      "B08DCBQMHB",
    "samsung_odyssey_g5":     "B08KXVL6VF",
    "asus_vg279qm_280hz":     "B08KXVL6VF",
}

# Categorías RSS de CamelCamelCamel (price drops)
RSS_FEEDS = [
    f"{BASE_URL}/rss/computer-components-price-drops.rss",
    f"{BASE_URL}/rss/computers-laptops-price-drops.rss",
    f"{BASE_URL}/rss/computer-monitors-price-drops.rss",
    f"{BASE_URL}/rss/computer-accessories-price-drops.rss",
]


# ──────────────────────────────────────────────
# MÉTODO 1: RSS (bajadas de precio recientes)
# ──────────────────────────────────────────────

def _fetch_rss_feed(url: str, batch_id: str) -> list:
    """Parsea un feed RSS de CamelCamelCamel."""
    records = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            return records

        items = channel.findall("item")
        now_iso = datetime.now(timezone.utc).isoformat()

        for item in items:
            try:
                title    = item.findtext("title", "")
                link     = item.findtext("link", "")
                pub_date = item.findtext("pubDate", now_iso)
                desc     = item.findtext("description", "")

                # Extraer ASIN de la URL
                asin = ""
                if "/product/" in link:
                    asin = link.split("/product/")[1].split("/")[0].split("?")[0]

                # Extraer precios del description (HTML embebido)
                soup = BeautifulSoup(desc, "html.parser")
                price_tags = soup.find_all("span", class_="price")
                prices = []
                for pt in price_tags:
                    try:
                        prices.append(float(pt.text.replace("$", "").replace(",", "").strip()))
                    except ValueError:
                        pass

                price_current  = prices[0] if len(prices) > 0 else None
                price_previous = prices[1] if len(prices) > 1 else None

                if price_current and price_current > 0:
                    records.append({
                        "batch_id":        batch_id,
                        "timestamp":       now_iso,
                        "source":          "camelcamelcamel_rss",
                        "asin":            asin,
                        "title":           title,
                        "price_usd":       price_current,
                        "price_prev_usd":  price_previous,
                        "pub_date":        pub_date,
                        "url":             link,
                        "feed_url":        url,
                    })
            except Exception as e:
                logger.debug(f"Error parseando item RSS: {e}")
                continue

    except requests.RequestException as e:
        logger.warning(f"[Camel RSS] Error en {url}: {e}")
    except ET.ParseError as e:
        logger.warning(f"[Camel RSS] Error XML en {url}: {e}")

    return records


# ──────────────────────────────────────────────
# MÉTODO 2: Historial por ASIN (scraping directo)
# ──────────────────────────────────────────────

def _fetch_asin_history(asin: str, name: str, batch_id: str) -> list:
    """
    Obtiene el historial de precios de un ASIN específico.
    CamelCamelCamel expone los datos en un gráfico Chart.js embebido.
    """
    records = []
    url = f"{BASE_URL}/product/{asin}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Extraer título del producto
        title_tag = soup.find("h1", class_="product_name")
        title = title_tag.text.strip() if title_tag else name

        # Extraer precio actual
        price_tag = soup.find("span", class_="price")
        current_price = None
        if price_tag:
            try:
                current_price = float(
                    price_tag.text.replace("$", "").replace(",", "").strip()
                )
            except ValueError:
                pass

        # Extraer datos históricos del script Chart.js
        scripts = soup.find_all("script")
        history_data = []

        for script in scripts:
            content = script.string or ""
            if "amazon_price" in content and "labels" in content:
                import re, json

                # Buscar array de labels (fechas)
                labels_match = re.search(r'"labels"\s*:\s*(\[.*?\])', content, re.DOTALL)
                # Buscar array de datos de precio Amazon
                data_match   = re.search(
                    r'"amazon_price".*?"data"\s*:\s*(\[.*?\])',
                    content, re.DOTALL
                )

                if labels_match and data_match:
                    try:
                        labels = json.loads(labels_match.group(1))
                        prices = json.loads(data_match.group(1))

                        for date_str, price_val in zip(labels, prices):
                            if price_val and float(price_val) > 0:
                                history_data.append({
                                    "date":  date_str,
                                    "price": float(price_val),
                                })
                    except (json.JSONDecodeError, ValueError):
                        pass
                break

        now_iso = datetime.now(timezone.utc).isoformat()

        # Si hay historial, crear un registro por punto temporal
        if history_data:
            for point in history_data:
                records.append({
                    "batch_id":      batch_id,
                    "timestamp":     now_iso,
                    "source":        "camelcamelcamel_history",
                    "asin":          asin,
                    "product_name":  name,
                    "title":         title,
                    "price_usd":     point["price"],
                    "price_date":    point["date"],
                    "current_price": current_price,
                    "url":           url,
                })
        elif current_price:
            # Fallback: solo precio actual
            records.append({
                "batch_id":      batch_id,
                "timestamp":     now_iso,
                "source":        "camelcamelcamel_current",
                "asin":          asin,
                "product_name":  name,
                "title":         title,
                "price_usd":     current_price,
                "price_date":    now_iso[:10],
                "current_price": current_price,
                "url":           url,
            })

        logger.info(
            f"  [Camel] {name} ({asin}): "
            f"{len(history_data)} puntos históricos"
        )

    except requests.RequestException as e:
        logger.warning(f"  [Camel] Error en ASIN {asin}: {e}")
    except Exception as e:
        logger.warning(f"  [Camel] Error inesperado en {asin}: {e}")

    return records


# ──────────────────────────────────────────────
# SCRAPER PRINCIPAL
# ──────────────────────────────────────────────

def scrape_camel(batch_id: str) -> list:
    """
    Scraper principal de CamelCamelCamel.
    Combina RSS (precio drops recientes) + historial por ASIN.
    """
    all_records = []

    # — Paso 1: RSS feeds (rápido, muchos productos)
    logger.info("[Camel] Iniciando RSS feeds...")
    for feed_url in RSS_FEEDS:
        records = _fetch_rss_feed(feed_url, batch_id)
        all_records.extend(records)
        logger.info(f"  RSS {feed_url.split('/')[-1]}: {len(records)} items")
        time.sleep(REQUEST_DELAY)

    # — Paso 2: Historial por ASIN (más lento, más profundo)
    logger.info(f"[Camel] Iniciando historial de {len(HARDWARE_ASINS)} ASINs...")
    for name, asin in HARDWARE_ASINS.items():
        records = _fetch_asin_history(asin, name, batch_id)
        all_records.extend(records)
        time.sleep(REQUEST_DELAY)

    logger.info(f"[Camel] TOTAL: {len(all_records)} registros recolectados")
    return all_records


# ──────────────────────────────────────────────
# EJECUCIÓN STANDALONE
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_batch = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results = scrape_camel(test_batch)
    print(f"\nTotal registros: {len(results)}")
    if results:
        print("Ejemplo:", results[0])
