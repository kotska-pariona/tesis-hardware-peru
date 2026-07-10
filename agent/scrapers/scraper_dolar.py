"""
scraper_dolar.py
Tipo de cambio USD/PEN en tiempo real — múltiples fuentes con fallback

Fuentes (en orden de prioridad):
  1. SUNAT (oficial Perú)           → tipo de cambio contable
  2. SBS Perú (Superintendencia)    → tipo de cambio bancario
  3. ExchangeRate-API (gratuita)    → fallback internacional
  4. Open Exchange Rates (gratuita) → fallback secundario
  5. Valor hardcodeado              → último recurso

No requiere credenciales para las fuentes 1-4.
"""

import re
import time
import logging
from datetime import datetime, timezone, date
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────
TIMEOUT        = 15
REQUEST_DELAY  = 0.5
FALLBACK_RATE  = 3.72   # Valor de respaldo (actualizar periódicamente)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-PE,es;q=0.9",
}


# ──────────────────────────────────────────────
# FUENTE 1: SUNAT (oficial)
# ──────────────────────────────────────────────

def _fetch_sunat() -> Optional[dict]:
    """
    Obtiene el tipo de cambio oficial de SUNAT.
    Endpoint: https://e-consulta.sunat.gob.pe/cl-at-ittipcam/tcS01Alias
    """
    url = "https://e-consulta.sunat.gob.pe/cl-at-ittipcam/tcS01Alias"
    today = date.today()

    params = {
        "accion":   "buscar",
        "moneda":   "02",   # USD
        "fecha":    today.strftime("%d/%m/%Y"),
    }

    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Buscar tabla con tipo de cambio
        rows = soup.select("table tr")
        for row in rows:
            cells = row.select("td")
            if len(cells) >= 3:
                try:
                    compra = float(cells[1].get_text(strip=True).replace(",", "."))
                    venta  = float(cells[2].get_text(strip=True).replace(",", "."))
                    if 3.0 < compra < 5.0 and 3.0 < venta < 5.0:
                        return {
                            "source":    "sunat",
                            "buy":       compra,
                            "sell":      venta,
                            "mid":       round((compra + venta) / 2, 4),
                            "date":      today.isoformat(),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                except (ValueError, IndexError):
                    continue

    except requests.RequestException as e:
        logger.debug(f"[Dolar/SUNAT] Error: {e}")

    return None


# ──────────────────────────────────────────────
# FUENTE 2: SBS Perú
# ──────────────────────────────────────────────

def _fetch_sbs() -> Optional[dict]:
    """
    Obtiene el tipo de cambio de la SBS (Superintendencia de Banca y Seguros).
    """
    url = "https://www.sbs.gob.pe/app/pp/sistip_portal/paginas/publicacion/tipocambio.aspx"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Buscar la fila del dólar americano
        rows = soup.select("table#ctl00_cphContent_rgTipoCambio_ctl00 tr")
        for row in rows:
            cells = row.select("td")
            text  = row.get_text().lower()
            if "dólar" in text or "dollar" in text or "usd" in text:
                if len(cells) >= 3:
                    try:
                        compra = float(cells[1].get_text(strip=True).replace(",", "."))
                        venta  = float(cells[2].get_text(strip=True).replace(",", "."))
                        if 3.0 < compra < 5.0:
                            return {
                                "source":    "sbs_peru",
                                "buy":       compra,
                                "sell":      venta,
                                "mid":       round((compra + venta) / 2, 4),
                                "date":      date.today().isoformat(),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                    except (ValueError, IndexError):
                        continue

    except requests.RequestException as e:
        logger.debug(f"[Dolar/SBS] Error: {e}")

    return None


# ──────────────────────────────────────────────
# FUENTE 3: ExchangeRate-API (gratuita, sin key)
# ──────────────────────────────────────────────

def _fetch_exchangerate_api() -> Optional[dict]:
    """
    Usa la API gratuita de exchangerate-api.com (sin API key).
    Límite: 1,500 requests/mes en plan gratuito.
    """
    url = "https://open.er-api.com/v6/latest/USD"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if data.get("result") == "success":
            pen_rate = data.get("rates", {}).get("PEN")
            if pen_rate and 3.0 < pen_rate < 5.0:
                return {
                    "source":    "exchangerate_api",
                    "buy":       round(pen_rate * 0.995, 4),   # Aproximar compra
                    "sell":      round(pen_rate * 1.005, 4),   # Aproximar venta
                    "mid":       round(pen_rate, 4),
                    "date":      data.get("time_last_update_utc", "")[:10],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

    except requests.RequestException as e:
        logger.debug(f"[Dolar/ExchangeRate-API] Error: {e}")
    except (ValueError, KeyError) as e:
        logger.debug(f"[Dolar/ExchangeRate-API] Error JSON: {e}")

    return None


# ──────────────────────────────────────────────
# FUENTE 4: Frankfurter (BCE, gratuita, sin key)
# ──────────────────────────────────────────────

def _fetch_frankfurter() -> Optional[dict]:
    """
    Usa la API de Frankfurter (datos del Banco Central Europeo).
    Completamente gratuita, sin límites.
    """
    url = "https://api.frankfurter.app/latest?from=USD&to=PEN"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        pen_rate = data.get("rates", {}).get("PEN")
        if pen_rate and 3.0 < pen_rate < 5.0:
            return {
                "source":    "frankfurter_bce",
                "buy":       round(pen_rate * 0.995, 4),
                "sell":      round(pen_rate * 1.005, 4),
                "mid":       round(pen_rate, 4),
                "date":      data.get("date", date.today().isoformat()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    except requests.RequestException as e:
        logger.debug(f"[Dolar/Frankfurter] Error: {e}")
    except (ValueError, KeyError) as e:
        logger.debug(f"[Dolar/Frankfurter] Error JSON: {e}")

    return None


# ──────────────────────────────────────────────
# FUENTE 5: dolarpe.com (scraping)
# ──────────────────────────────────────────────

def _fetch_dolarpe() -> Optional[dict]:
    """Scraping de dolarpe.com — tipo de cambio paralelo Perú."""
    url = "https://dolarpe.com/"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Buscar precios de compra/venta
        compra_tag = soup.select_one(".compra .precio, #compra, .buy-price")
        venta_tag  = soup.select_one(".venta .precio, #venta, .sell-price")

        def extract_price(tag) -> Optional[float]:
            if not tag:
                return None
            text = re.sub(r"[^\d.,]", "", tag.get_text()).replace(",", ".")
            try:
                val = float(text)
                return val if 3.0 < val < 5.0 else None
            except ValueError:
                return None

        compra = extract_price(compra_tag)
        venta  = extract_price(venta_tag)

        if compra and venta:
            return {
                "source":    "dolarpe_com",
                "buy":       compra,
                "sell":      venta,
                "mid":       round((compra + venta) / 2, 4),
                "date":      date.today().isoformat(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    except requests.RequestException as e:
        logger.debug(f"[Dolar/dolarpe.com] Error: {e}")

    return None


# ──────────────────────────────────────────────
# SCRAPER PRINCIPAL — con fallback en cadena
# ──────────────────────────────────────────────

SOURCES = [
    ("SUNAT",            _fetch_sunat),
    ("SBS Perú",         _fetch_sbs),
    ("ExchangeRate-API", _fetch_exchangerate_api),
    ("Frankfurter/BCE",  _fetch_frankfurter),
    ("dolarpe.com",      _fetch_dolarpe),
]


def get_exchange_rate(batch_id: str) -> dict:
    """
    Obtiene el tipo de cambio USD/PEN con fallback automático entre fuentes.
    Siempre retorna un dict válido (nunca falla).
    """
    for source_name, fetch_fn in SOURCES:
        logger.info(f"[Dolar] Intentando fuente: {source_name}")
        try:
            result = fetch_fn()
            if result:
                result["batch_id"] = batch_id
                logger.info(
                    f"  ✅ {source_name}: "
                    f"Compra={result['buy']} | "
                    f"Venta={result['sell']} | "
                    f"Mid={result['mid']}"
                )
                return result
            else:
                logger.debug(f"  ⚠️ {source_name}: sin datos válidos")
        except Exception as e:
            logger.warning(f"  ❌ {source_name}: error inesperado — {e}")

        time.sleep(REQUEST_DELAY)

    # Fallback absoluto
    logger.warning(f"[Dolar] Todas las fuentes fallaron. Usando valor hardcodeado: {FALLBACK_RATE}")
    return {
        "batch_id":  batch_id,
        "source":    "hardcoded_fallback",
        "buy":       FALLBACK_RATE - 0.02,
        "sell":      FALLBACK_RATE + 0.02,
        "mid":       FALLBACK_RATE,
        "date":      date.today().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def scrape_dolar(batch_id: str) -> list:
    """
    Wrapper que retorna lista de 1 registro (compatible con el pipeline).
    También obtiene historial de los últimos 30 días si está disponible.
    """
    records = []

    # Tipo de cambio actual
    current = get_exchange_rate(batch_id)
    records.append(current)

    # Historial 30 días desde Frankfurter (gratuito, sin límites)
    try:
        from datetime import timedelta
        end_date   = date.today()
        start_date = end_date - timedelta(days=30)
        hist_url   = (
            f"https://api.frankfurter.app/"
            f"{start_date.isoformat()}..{end_date.isoformat()}"
            f"?from=USD&to=PEN"
        )
        resp = requests.get(hist_url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        hist_data = resp.json()

        for date_str, rates in hist_data.get("rates", {}).items():
            pen = rates.get("PEN")
            if pen and 3.0 < pen < 5.0:
                records.append({
                    "batch_id":  batch_id,
                    "source":    "frankfurter_history",
                    "buy":       round(pen * 0.995, 4),
                    "sell":      round(pen * 1.005, 4),
                    "mid":       round(pen, 4),
                    "date":      date_str,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        logger.info(f"[Dolar] Historial 30d: {len(records) - 1} puntos adicionales")

    except Exception as e:
        logger.debug(f"[Dolar] Error obteniendo historial: {e}")

    logger.info(f"[Dolar] TOTAL: {len(records)} registros")
    return records


# ──────────────────────────────────────────────
# EJECUCIÓN STANDALONE
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_batch = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results = scrape_dolar(test_batch)
    print(f"\nTotal registros: {len(results)}")
    for r in results[:3]:
        print(r)
