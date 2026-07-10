"""
scraper_dolar.py  v2.0
Tipo de cambio USD/PEN en tiempo real — múltiples fuentes con fallback

Fuentes (en orden de prioridad):
  1. SUNAT (oficial Perú)     → tipo de cambio contable (L-V)
  2. SBS Perú                 → tipo de cambio bancario
  3. ExchangeRate-API         → fallback internacional (1500 req/mes gratis)
  4. Frankfurter/BCE          → fallback secundario (sin límites)
  5. dolarpe.com              → tipo de cambio paralelo Perú
  6. Valor hardcodeado        → último recurso

Fixes v2.0:
  - [FIX-1] timedelta movido al import del top
  - [FIX-2] FALLBACK_RATE actualizado a 3.78 (Julio 2026)
  - [FIX-3] extract_price: manejo correcto de punto de miles
  - [FIX-4] SBS: selector CSS con fallback genérico
  - [FIX-5] Caché opcional con TTL de 4h para reducir requests
  - [FIX-6] Log específico para SUNAT en fines de semana
  - [FIX-7] dolarpe.com: log de debug cuando tags son None
"""

import re
import json
import time
import logging
from datetime import datetime, timezone, date, timedelta   # FIX-1: timedelta al top
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────
TIMEOUT       = 15
REQUEST_DELAY = 0.5

# FIX-2: Actualizado Julio 2026 — revisar cada 3 meses
FALLBACK_RATE            = 3.78
FALLBACK_RATE_UPDATED    = "2026-07-10"   # Fecha de última actualización manual

# FIX-5: Caché TTL (horas) — evita requests redundantes en runs de 2h
CACHE_TTL_HOURS = 4
CACHE_FILE      = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / ".dolar_cache.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-PE,es;q=0.9",
}


# ──────────────────────────────────────────────
# FIX-5: Caché con TTL
# ──────────────────────────────────────────────

def _load_cache() -> Optional[dict]:
    """Carga el tipo de cambio cacheado si tiene menos de CACHE_TTL_HOURS."""
    try:
        if not CACHE_FILE.exists():
            return None
        with open(CACHE_FILE, encoding="utf-8") as f:
            cached = json.load(f)
        cached_at = datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
        age_hours = (datetime.now(timezone.utc) - cached_at).total_seconds() / 3600
        if age_hours < CACHE_TTL_HOURS:
            logger.info(f"[Dolar] Cache hit — {age_hours:.1f}h de antigüedad (TTL={CACHE_TTL_HOURS}h)")
            return cached
    except Exception:
        pass
    return None


def _save_cache(result: dict) -> None:
    """Guarda el tipo de cambio en caché."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {**result, "cached_at": datetime.now(timezone.utc).isoformat()}
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        logger.debug(f"[Dolar] No se pudo guardar caché: {e}")


# ──────────────────────────────────────────────
# FIX-3: Función robusta para limpiar precios
# ──────────────────────────────────────────────

def _parse_price(text: str) -> Optional[float]:
    """
    Convierte texto de precio a float manejando formatos:
      '3,72'      → 3.72   (formato SUNAT/SBS)
      '3.72'      → 3.72   (formato internacional)
      '3.720,50'  → 3720.5 → descartado por validación (>5.0) ✅
      '3,720.50'  → 3720.5 → descartado por validación ✅
      'S/ 3.72'   → 3.72
    """
    if not text:
        return None
    # Eliminar todo excepto dígitos, coma y punto
    clean = re.sub(r"[^\d,.]", "", text.strip())
    if not clean:
        return None
    try:
        # Detectar formato: si tiene coma Y punto, el último es decimal
        if "," in clean and "." in clean:
            last_comma = clean.rfind(",")
            last_dot   = clean.rfind(".")
            if last_comma > last_dot:
                # Formato europeo: 3.720,50 → eliminar punto, reemplazar coma
                clean = clean.replace(".", "").replace(",", ".")
            else:
                # Formato anglosajón: 3,720.50 → eliminar coma
                clean = clean.replace(",", "")
        elif "," in clean:
            # Solo coma: puede ser decimal (3,72) o miles (3,720)
            parts = clean.split(",")
            if len(parts) == 2 and len(parts[1]) <= 2:
                clean = clean.replace(",", ".")   # Decimal: 3,72 → 3.72
            else:
                clean = clean.replace(",", "")    # Miles: 3,720 → 3720
        return float(clean)
    except ValueError:
        return None


# ──────────────────────────────────────────────
# FUENTE 1: SUNAT (oficial)
# ──────────────────────────────────────────────

def _fetch_sunat() -> Optional[dict]:
    """
    Tipo de cambio oficial SUNAT.
    NOTA: No disponible sábado/domingo — retorna None correctamente.
    """
    # FIX-6: Log informativo en fines de semana
    weekday = date.today().weekday()
    if weekday >= 5:
        logger.info("[Dolar/SUNAT] Fin de semana — SUNAT no publica tipo de cambio")
        return None

    url   = "https://e-consulta.sunat.gob.pe/cl-at-ittipcam/tcS01Alias"
    today = date.today()
    params = {
        "accion": "buscar",
        "moneda": "02",
        "fecha":  today.strftime("%d/%m/%Y"),
    }

    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for row in soup.select("table tr"):
            cells = row.select("td")
            if len(cells) >= 3:
                compra = _parse_price(cells[1].get_text(strip=True))  # FIX-3
                venta  = _parse_price(cells[2].get_text(strip=True))  # FIX-3
                if compra and venta and 3.0 < compra < 5.0 and 3.0 < venta < 5.0:
                    return {
                        "source":    "sunat",
                        "buy":       compra,
                        "sell":      venta,
                        "mid":       round((compra + venta) / 2, 4),
                        "date":      today.isoformat(),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

    except requests.RequestException as e:
        logger.debug(f"[Dolar/SUNAT] Error: {e}")

    return None


# ──────────────────────────────────────────────
# FUENTE 2: SBS Perú
# ──────────────────────────────────────────────

def _fetch_sbs() -> Optional[dict]:
    """Tipo de cambio SBS. FIX-4: selector con fallback genérico."""
    url = "https://www.sbs.gob.pe/app/pp/sistip_portal/paginas/publicacion/tipocambio.aspx"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # FIX-4: Selectores en orden de especificidad
        selectors = [
            "table#ctl00_cphContent_rgTipoCambio_ctl00 tr",  # ID específico ASP.NET
            "table.rgMasterTable tr",                         # Clase genérica RadGrid
            "table tr",                                       # Fallback: cualquier tabla
        ]

        for selector in selectors:
            rows = soup.select(selector)
            for row in rows:
                cells = row.select("td")
                text  = row.get_text().lower()
                if any(k in text for k in ["dólar", "dollar", "usd", "estados unidos"]):
                    if len(cells) >= 3:
                        compra = _parse_price(cells[1].get_text(strip=True))  # FIX-3
                        venta  = _parse_price(cells[2].get_text(strip=True))  # FIX-3
                        if compra and venta and 3.0 < compra < 5.0:
                            return {
                                "source":    "sbs_peru",
                                "buy":       compra,
                                "sell":      venta,
                                "mid":       round((compra + venta) / 2, 4),
                                "date":      date.today().isoformat(),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
            if rows:
                break  # Si el selector encontró filas pero no USD, no probar el siguiente

    except requests.RequestException as e:
        logger.debug(f"[Dolar/SBS] Error: {e}")

    return None


# ──────────────────────────────────────────────
# FUENTE 3: ExchangeRate-API (gratuita)
# ──────────────────────────────────────────────

def _fetch_exchangerate_api() -> Optional[dict]:
    """
    API gratuita open.er-api.com.
    Límite: 1,500 req/mes. Con 12 runs/día = ~360/mes — dentro del límite.
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
                    "buy":       round(pen_rate * 0.995, 4),
                    "sell":      round(pen_rate * 1.005, 4),
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
# FUENTE 4: Frankfurter (BCE, sin límites)
# ──────────────────────────────────────────────

def _fetch_frankfurter() -> Optional[dict]:
    """
    API Frankfurter — datos del Banco Central Europeo.
    NOTA: USD→PEN es conversión triangular (USD→EUR→PEN).
    Diferencia vs tipo real: ~0.1-0.3% — aceptable para modelo ROI.
    """
    url = "https://api.frankfurter.app/latest?from=USD&to=PEN"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data     = resp.json()
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
# FUENTE 5: dolarpe.com
# ──────────────────────────────────────────────

def _fetch_dolarpe() -> Optional[dict]:
    """Scraping dolarpe.com — tipo de cambio paralelo Perú."""
    url = "https://dolarpe.com/"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        compra_tag = soup.select_one(".compra .precio, #compra, .buy-price, [data-type='buy']")
        venta_tag  = soup.select_one(".venta .precio, #venta, .sell-price, [data-type='sell']")

        # FIX-7: Log cuando los tags no se encuentran
        if not compra_tag or not venta_tag:
            logger.debug(
                f"[Dolar/dolarpe.com] Tags no encontrados — "
                f"compra={compra_tag is not None}, venta={venta_tag is not None}\n"
                f"  HTML snippet: {str(soup.body)[:200] if soup.body else 'N/A'}"
            )
            return None

        compra = _parse_price(compra_tag.get_text())   # FIX-3
        venta  = _parse_price(venta_tag.get_text())    # FIX-3

        if compra and venta and 3.0 < compra < 5.0:
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
# SCRAPER PRINCIPAL
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
    Obtiene el tipo de cambio USD/PEN con fallback automático.
    FIX-5: Usa caché si el dato tiene menos de CACHE_TTL_HOURS horas.
    Siempre retorna un dict válido — nunca falla.
    """
    # FIX-5: Intentar caché primero
    cached = _load_cache()
    if cached:
        cached["batch_id"] = batch_id
        cached["source"]  += "_cached"
        return cached

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
                _save_cache(result)   # FIX-5: Guardar en caché
                return result
            else:
                logger.debug(f"  ⚠️ {source_name}: sin datos válidos")
        except Exception as e:
            logger.warning(f"  ❌ {source_name}: error inesperado — {e}")
        time.sleep(REQUEST_DELAY)

    # Fallback absoluto — FIX-2: valor actualizado
    logger.warning(
        f"[Dolar] Todas las fuentes fallaron. "
        f"Usando hardcoded: {FALLBACK_RATE} (actualizado: {FALLBACK_RATE_UPDATED})"
    )
    return {
        "batch_id":  batch_id,
        "source":    "hardcoded_fallback",
        "buy":       round(FALLBACK_RATE - 0.02, 4),
        "sell":      round(FALLBACK_RATE + 0.02, 4),
        "mid":       FALLBACK_RATE,
        "date":      date.today().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def scrape_dolar(batch_id: str) -> list:
    """
    Retorna lista de registros USD/PEN:
      - [0]   : tipo de cambio actual
      - [1..N]: historial 30 días (Frankfurter)
    """
    records = []

    # Tipo de cambio actual
    current = get_exchange_rate(batch_id)
    records.append(current)

    # Historial 30 días desde Frankfurter
    try:
        end_date   = date.today()
        start_date = end_date - timedelta(days=30)   # FIX-1: timedelta ya importado
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
# STANDALONE
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_batch = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results    = scrape_dolar(test_batch)
    print(f"\nTotal registros: {len(results)}")
    for r in results[:3]:
        print(r)
