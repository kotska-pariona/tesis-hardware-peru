"""
scraper_camel.py  v3.1
CamelCamelCamel — Historial de precios Amazon (desde 2008)

Fixes v3.1 (sobre v3.0):
  [C10] ebaysdk eliminado de dependencias (no usado aquí — alineado con [W20]/[P10])
  [C11] _fetch_rss_feed: session requests reutilizada en lugar de requests.get()
        por llamada — reduce overhead de conexión TCP en RSS + ASIN loop
  [C12] _fetch_asin_history: backoff exponencial reemplaza delay lineal
        (attempt+2 → 2**attempt * REQUEST_DELAY) — más robusto ante 429/403
  [C13] scrape_camel: parámetro mode agregado para alinear firma con main.py
        (main.py pasa mode= a todos los scrapers opcionales)
  [C14] _extract_chartjs_data: log DEBUG cuando ninguna estrategia extrae datos
        (facilita diagnóstico del camel=0 sin spam en modo normal)
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

try:
    from fake_useragent import UserAgent as _UA
    _ua_gen = _UA()
except ImportError:
    _ua_gen = None

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────
BASE_URL        = "https://camelcamelcamel.com"
REQUEST_DELAY   = 2.5
TIMEOUT         = 20
MAX_RETRIES     = 3
MAX_HISTORY_PTS = 1000

# [C1] UA base de fallback si fake-useragent no está disponible
_UA_FALLBACK = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

def _get_headers() -> dict:
    """[C1] Genera headers con User-Agent rotativo."""
    ua = _ua_gen.random if _ua_gen else _UA_FALLBACK
    return {
        "User-Agent":      ua,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer":         "https://camelcamelcamel.com/",
    }

# ──────────────────────────────────────────────
# ASINs — 37 únicos, verificados Julio 2026
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
    # ── Motherboards ──────────────────────────
    "asus_z790_prime":        "B0BHB6GXNQ",
    "msi_b650_tomahawk":      "B0BG7BXKM3",
    "gigabyte_b760m":         "B0BSVQBG9N",
    # ── Laptops ───────────────────────────────
    "asus_rog_g15_rtx4060":   "B0BZKQXNMJ",
    "lenovo_legion_5_i7":     "B0BXNK9GBF",
    "acer_nitro_5_i5":        "B09Q5NXQTM",
    # ── Monitores ─────────────────────────────
    "lg_27gp850b_165hz":      "B08DCBQMHB",
    "samsung_odyssey_g5":     "B08KXVL6VF",
    "asus_vg279qm_280hz":     "B08WY5JKXB",
}

RSS_FEEDS = [
    f"{BASE_URL}/rss/computer-components-price-drops.rss",
    f"{BASE_URL}/rss/computers-laptops-price-drops.rss",
    f"{BASE_URL}/rss/computer-monitors-price-drops.rss",
    f"{BASE_URL}/rss/computer-accessories-price-drops.rss",
]

# [C2] Esquema unificado — 'title' es el título raw (RSS/HTML),
#      'product_name' es el nombre canónico del producto.
#      'price_prev_usd' solo se popula en fuente RSS.
RECORD_SCHEMA = {
    "batch_id":       "",
    "timestamp":      "",
    "source":         "",
    "asin":           "",
    "product_name":   "",
    "title":          "",      # título raw del RSS o h1 del HTML
    "price_usd":      None,
    "price_prev_usd": None,    # solo RSS: precio anterior al drop
    "price_date":     "",
    "current_price":  None,
    "pub_date":       "",
    "url":            "",
    "feed_url":       "",
}

def _make_record(**kwargs) -> dict:
    record = RECORD_SCHEMA.copy()
    record.update(kwargs)
    return record


# ──────────────────────────────────────────────
# Validación de ASINs
# ──────────────────────────────────────────────
def _validate_asins(asins: dict) -> dict:
    seen, clean, dupes = {}, {}, []
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
# [C5/C6/C7] Extractor de brackets balanceados
# Reemplaza todos los regex non-greedy r'{.*?}' y r'\[.*?\]'
# ──────────────────────────────────────────────
def _extract_balanced(text: str, start_idx: int, open_ch: str, close_ch: str) -> Optional[str]:
    """
    Extrae el bloque balanceado que empieza en start_idx.
    Maneja strings JSON (no cuenta brackets dentro de strings).
    Retorna el bloque completo o None si no está balanceado.
    """
    depth   = 0
    in_str  = False
    escaped = False
    i       = start_idx

    while i < len(text):
        ch = text[i]
        if escaped:
            escaped = False
        elif ch == '\\' and in_str:
            escaped = True
        elif ch == '"' and not escaped:
            in_str = not in_str
        elif not in_str:
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return text[start_idx: i + 1]
        i += 1
    return None  # No balanceado


def _find_balanced_block(content: str, marker: str, open_ch: str) -> Optional[str]:
    """
    Busca 'marker' en content, luego extrae el bloque balanceado
    que comienza en el primer open_ch después del marker.
    """
    close_ch = '}' if open_ch == '{' else ']'
    idx = content.find(marker)
    while idx != -1:
        start = content.find(open_ch, idx)
        if start == -1:
            break
        block = _extract_balanced(content, start, open_ch, close_ch)
        if block:
            return block
        idx = content.find(marker, idx + 1)
    return None


# ──────────────────────────────────────────────
# FIX-3 (v3.0): Parser Chart.js con brackets balanceados
# ──────────────────────────────────────────────
def _extract_chartjs_data(scripts) -> list:
    """
    Extrae historial de precios del JSON de Chart.js.
    [C5/C6] Usa extractor de brackets balanceados en lugar de regex non-greedy.
    Solo captura datos del vendedor 'amazon' (no third_party ni used).
    [C14] Log DEBUG cuando ninguna estrategia extrae datos.
    """
    history = []

    for script in scripts:
        content = script.string or ""
        if "amazon_price" not in content and "amazon" not in content.lower():
            continue

        # ── Estrategia 1: extraer objeto completo de new Chart(...) ──────
        chart_block = _find_balanced_block(content, "new Chart", '{')
        if chart_block:
            try:
                clean = re.sub(r'//[^\n]*', '', chart_block)
                clean = re.sub(r'/\*.*?\*/', '', clean, flags=re.DOTALL)
                data  = json.loads(clean)

                datasets = (
                    data.get("datasets") or
                    data.get("data", {}).get("datasets", [])
                )
                labels = (
                    data.get("labels") or
                    data.get("data", {}).get("labels", [])
                )

                if isinstance(datasets, list) and labels:
                    for ds in datasets:
                        ds_id = str(ds.get("id", ds.get("label", ""))).lower()
                        if "amazon" not in ds_id:
                            continue
                        for date_str, price_val in zip(labels, ds.get("data", [])):
                            try:
                                if price_val is not None and float(price_val) > 0:
                                    history.append({
                                        "date":  str(date_str),
                                        "price": float(price_val),
                                    })
                            except (ValueError, TypeError):
                                continue
                    if history:
                        return history
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        # ── Estrategia 2: extraer solo el array 'datasets' ───────────────
        datasets_block = _find_balanced_block(content, '"datasets"', '[')
        labels_block   = _find_balanced_block(content, '"labels"',   '[')
        if datasets_block and labels_block:
            try:
                clean_ds = re.sub(r'//[^\n]*', '', datasets_block)
                clean_lb = re.sub(r'//[^\n]*', '', labels_block)
                datasets = json.loads(clean_ds)
                labels   = json.loads(clean_lb)
                for ds in datasets:
                    ds_id = str(ds.get("id", ds.get("label", ""))).lower()
                    if "amazon" not in ds_id:
                        continue
                    for date_str, price_val in zip(labels, ds.get("data", [])):
                        try:
                            if price_val is not None and float(price_val) > 0:
                                history.append({
                                    "date":  str(date_str),
                                    "price": float(price_val),
                                })
                        except (ValueError, TypeError):
                            continue
                if history:
                    return history
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        # ── Estrategia 3 (fallback conservador): bloque amazon_price ─────
        # [C7] Usa _find_balanced_block en lugar de regex [^}]* / [^\]]*
        amazon_block = _find_balanced_block(content, '"amazon_price"', '{')
        labels_block = _find_balanced_block(content, '"labels"', '[')
        if amazon_block and labels_block:
            try:
                data_block = _find_balanced_block(amazon_block, '"data"', '[')
                if data_block:
                    prices_list = json.loads(data_block)
                    labels_list = json.loads(labels_block)
                    for date_str, price_val in zip(labels_list, prices_list):
                        try:
                            if price_val and float(price_val) > 0:
                                history.append({
                                    "date":  str(date_str),
                                    "price": float(price_val),
                                })
                        except (ValueError, TypeError):
                            continue
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        # [C14] Ninguna estrategia extrajo datos — loguear para diagnóstico
        if not history:
            logger.debug(
                "[Camel] _extract_chartjs_data: ninguna estrategia extrajo datos "
                f"(script len={len(content)})"
            )

    return history


# ──────────────────────────────────────────────
# MÉTODO 1: RSS
# ──────────────────────────────────────────────
def _fetch_rss_feed(url: str, batch_id: str, session: requests.Session) -> list:
    """
    [C11] Recibe session reutilizable en lugar de crear conexión TCP por llamada.
    """
    records = []
    try:
        resp = session.get(url, headers=_get_headers(), timeout=TIMEOUT)  # [C1][C11]
        resp.raise_for_status()
        root    = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            return records

        items   = channel.findall("item")
        now_iso = datetime.now(timezone.utc).isoformat()

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

                # [C4] Filtrar registros sin ASIN — inútiles para análisis ROI
                if not asin:
                    logger.debug(f"[Camel RSS] Item sin ASIN, omitido: {link}")
                    continue

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
                        batch_id       = batch_id,
                        timestamp      = now_iso,
                        source         = "camelcamelcamel_rss",
                        asin           = asin,
                        title          = title,
                        product_name   = title,
                        price_usd      = price_current,
                        price_prev_usd = price_previous,  # solo RSS
                        price_date     = now_iso[:10],
                        pub_date       = pub_date,
                        url            = link,
                        feed_url       = url,
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
# MÉTODO 2: Historial por ASIN
# ──────────────────────────────────────────────
def _fetch_asin_history(
    asin: str, name: str, batch_id: str, session: requests.Session
) -> list:
    """
    [C11] Recibe session reutilizable.
    [C12] Backoff exponencial: 2**attempt * REQUEST_DELAY.
    """
    records = []
    url     = f"{BASE_URL}/product/{asin}"
    now_iso = datetime.now(timezone.utc).isoformat()

    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, headers=_get_headers(), timeout=TIMEOUT)  # [C1][C11]

            if resp.status_code == 403:
                wait = (2 ** attempt) * REQUEST_DELAY   # [C12] backoff exponencial
                logger.warning(f"  [Camel] 403 en {asin} — esperando {wait:.1f}s")
                time.sleep(wait)
                continue
            if resp.status_code == 429:
                wait = (2 ** attempt) * 30              # [C12] backoff exponencial
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

            # Precio Amazon específico
            current_price  = None
            amazon_section = (
                soup.find("div", id="amazon_price") or
                soup.find("div", class_="amazon_price") or
                soup.find("td", class_="camPrice")
            )
            # [C8] Log cuando cae al selector genérico
            if amazon_section:
                price_source = amazon_section
            else:
                price_source = soup
                logger.debug(f"  [Camel] {asin}: selector específico no encontrado — usando genérico")

            price_tag = price_source.find("span", class_="price")
            if price_tag:
                try:
                    current_price = float(
                        price_tag.text.replace("$", "").replace(",", "").strip()
                    )
                except ValueError:
                    pass

            # [C5/C6/C7] Parser con brackets balanceados
            history_data = _extract_chartjs_data(soup.find_all("script"))

            if len(history_data) > MAX_HISTORY_PTS:
                history_data = history_data[-MAX_HISTORY_PTS:]
                logger.debug(f"  [Camel] {asin}: limitado a {MAX_HISTORY_PTS} puntos")

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
                f"{len(history_data)} puntos históricos | "
                f"precio actual: ${current_price or 'N/A'}"
            )
            break  # Éxito

        except requests.RequestException as e:
            wait = (2 ** attempt) * REQUEST_DELAY   # [C12] backoff exponencial
            logger.warning(
                f"  [Camel] Intento {attempt+1}/{MAX_RETRIES} fallido {asin}: {e} "
                f"— esperando {wait:.1f}s"
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(wait)
        except Exception as e:
            logger.warning(f"  [Camel] Error inesperado en {asin}: {e}")
            break

    return records


# ──────────────────────────────────────────────
# SCRAPER PRINCIPAL
# ──────────────────────────────────────────────
def scrape_camel(batch_id: str, mode: str = "normal") -> list:
    """
    Scraper principal de CamelCamelCamel.
    Combina RSS + historial por ASIN con esquema unificado.

    [C13] Parámetro mode agregado — main.py lo pasa a todos los scrapers opcionales.
    [C11] Session requests compartida entre RSS + ASIN loop.
    """
    all_records = []
    valid_asins = _validate_asins(HARDWARE_ASINS)

    # [C11] Session compartida — reutiliza conexiones TCP
    session = requests.Session()

    # ── Paso 1: RSS feeds ──────────────────────────────────────────────
    logger.info("[Camel] Iniciando RSS feeds...")
    for feed_url in RSS_FEEDS:
        records = _fetch_rss_feed(feed_url, batch_id, session)   # [C11]
        all_records.extend(records)
        logger.info(f"  RSS {feed_url.split('/')[-1]}: {len(records)} items")
        time.sleep(REQUEST_DELAY)

    # ── Paso 2: Historial por ASIN ─────────────────────────────────────
    logger.info(f"[Camel] Iniciando historial de {len(valid_asins)} ASINs...")
    for idx, (name, asin) in enumerate(valid_asins.items(), 1):
        logger.info(f"  [{idx}/{len(valid_asins)}] {name} ({asin})")
        records = _fetch_asin_history(asin, name, batch_id, session)   # [C11]
        all_records.extend(records)
        time.sleep(REQUEST_DELAY)

    session.close()
    logger.info(f"[Camel] TOTAL: {len(all_records)} registros recolectados")
    return all_records


# ──────────────────────────────────────────────
# STANDALONE
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # [C9] datetime con timezone explícita
    test_batch = f"test_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    results    = scrape_camel(test_batch)
    print(f"\nTotal registros: {len(results)}")
    if results:
        print("Ejemplo:", results[0])
