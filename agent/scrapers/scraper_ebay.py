"""
scraper_ebay.py  v3.0
eBay Browse API (REST) — Precios de mercado USA en tiempo real

Fixes v3.0 (sobre v2.0):
  - [E1] EBAY_CLIENT_SECRET documentado explícitamente en workflows
         (requiere agregarlo a GitHub Secrets — ver instrucciones abajo)
  - [E2] ship_free: solo True cuando shippingCost.value == '0.0' explícito
  - [E3] Validación currency == 'USD' antes de guardar el registro
  - [E4] Paginación migrada a while loop — 401 no consume páginas del contador
  - [E5] Deduplicación sin item_id usa fingerprint title[:60]|price
  - [E6] EBAY_QUERIES ampliado: PSU, Cooler, Case (cat IDs verificados)
  - [E7] __main__: datetime.now(timezone.utc) — naive datetime corregido
  - [E8] conditions ampliado: NEW|USED|VERY_GOOD|GOOD

CONFIGURACIÓN REQUERIDA (GitHub Secrets):
  EBAY_APP_ID        → Client ID  (https://developer.ebay.com/my/keys)
  EBAY_CLIENT_SECRET → Client Secret (NUEVO — agregar al workflow)

Workflows que deben incluir EBAY_CLIENT_SECRET en env:
  .github/workflows/daily_agent.yml
  .github/workflows/pipeline_roi.yml
"""

import os
import time
import base64
import hashlib
import logging
import requests
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────
EBAY_APP_ID        = os.getenv("EBAY_APP_ID", "")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET", "")   # [E1] Requerido

BROWSE_API_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
OAUTH_URL      = "https://api.ebay.com/identity/v1/oauth2/token"
OAUTH_SCOPE    = "https://api.ebay.com/oauth/api_scope"

ITEMS_PER_PAGE = 200
MAX_PAGES      = 5
REQUEST_DELAY  = 0.8

PRICE_MIN_USD = 5.0
PRICE_MAX_USD = 10_000.0

# ──────────────────────────────────────────────
# [E6] EBAY_QUERIES — ampliado con PSU, Cooler, Case
# ──────────────────────────────────────────────
EBAY_QUERIES = [
    # (query, category_id, label)
    # ── CPU ──────────────────────────────────
    ("intel core i5 processor",        "164",    "cpu"),
    ("intel core i7 processor",        "164",    "cpu"),
    ("intel core i9 processor",        "164",    "cpu"),
    ("amd ryzen 5 processor",          "164",    "cpu"),
    ("amd ryzen 7 processor",          "164",    "cpu"),
    ("amd ryzen 9 processor",          "164",    "cpu"),
    # ── GPU ──────────────────────────────────
    ("nvidia rtx 4060 graphics card",  "27386",  "gpu"),
    ("nvidia rtx 4070 graphics card",  "27386",  "gpu"),
    ("nvidia rtx 4080 graphics card",  "27386",  "gpu"),
    ("amd rx 7600 graphics card",      "27386",  "gpu"),
    ("amd rx 7700 graphics card",      "27386",  "gpu"),
    # ── RAM ──────────────────────────────────
    ("ddr4 16gb ram",                  "170083", "ram"),
    ("ddr4 32gb ram",                  "170083", "ram"),
    ("ddr5 16gb ram",                  "170083", "ram"),
    ("ddr5 32gb ram",                  "170083", "ram"),
    # ── SSD ──────────────────────────────────
    ("nvme ssd 1tb",                   "56083",  "storage"),
    ("nvme ssd 500gb",                 "56083",  "storage"),
    ("samsung 870 evo ssd",            "56083",  "storage"),
    # ── Motherboard ──────────────────────────
    ("intel z790 motherboard",         "1244",   "motherboard"),
    ("amd b650 motherboard",           "1244",   "motherboard"),
    # ── PSU [E6] ─────────────────────────────
    ("modular power supply 850w gold", "42017",  "psu"),
    ("corsair rm850x power supply",    "42017",  "psu"),
    # ── Cooler [E6] ──────────────────────────
    ("240mm aio liquid cpu cooler",    "131486", "cooler"),
    ("noctua cpu air cooler",          "131486", "cooler"),
    # ── Case [E6] ────────────────────────────
    ("atx mid tower pc case gaming",   "42014",  "case"),
    ("lian li pc case tempered glass", "42014",  "case"),
    # ── Laptop ───────────────────────────────
    ("gaming laptop rtx 4060",         "177",    "laptop"),
    ("laptop intel i7 16gb",           "177",    "laptop"),
    # ── Monitor ──────────────────────────────
    ("gaming monitor 144hz 27 inch",   "80053",  "monitor"),
    ("4k monitor 27 inch",             "80053",  "monitor"),
    # ── Periféricos ──────────────────────────
    ("mechanical keyboard gaming",     "33963",  "peripheral"),
    ("gaming mouse wireless",          "26252",  "peripheral"),
]


# ──────────────────────────────────────────────
# OAuth2 Client Credentials
# ──────────────────────────────────────────────
_token_cache: dict = {}


def _get_oauth_token() -> Optional[str]:
    """
    Obtiene Bearer token via OAuth2 Client Credentials flow.
    Cachea el token hasta su expiración (con 60s de margen).
    """
    now = time.time()
    if _token_cache.get("token") and now < _token_cache.get("expires_at", 0) - 60:
        return _token_cache["token"]

    if not EBAY_APP_ID or not EBAY_CLIENT_SECRET:
        logger.error(
            "❌ EBAY_APP_ID o EBAY_CLIENT_SECRET no configurados.\n"
            "   Agregar ambos a GitHub Secrets y al env del workflow.\n"
            "   Registro: https://developer.ebay.com/my/keys"
        )
        return None

    try:
        credentials = base64.b64encode(
            f"{EBAY_APP_ID}:{EBAY_CLIENT_SECRET}".encode()
        ).decode()

        resp = requests.post(
            OAUTH_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type":  "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "client_credentials",
                "scope":      OAUTH_SCOPE,
            },
            timeout=15,
        )
        resp.raise_for_status()
        token_data = resp.json()

        token      = token_data.get("access_token")
        expires_in = int(token_data.get("expires_in", 7200))

        _token_cache["token"]      = token
        _token_cache["expires_at"] = now + expires_in

        logger.info(f"[eBay] OAuth2 token obtenido (expira en {expires_in // 60} min)")
        return token

    except requests.RequestException as e:
        logger.error(f"[eBay] Error obteniendo OAuth2 token: {e}")
        return None
    except Exception as e:
        logger.error(f"[eBay] Error inesperado en OAuth2: {e}")
        return None


# ──────────────────────────────────────────────
# PARSEO DE ITEMS — Browse API
# ──────────────────────────────────────────────
def _parse_items_browse(items: list, query: str, label: str, batch_id: str) -> list:
    records = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for item in items:
        try:
            price_info = item.get("price", {})
            price_usd  = float(price_info.get("value", 0))
            currency   = price_info.get("currency", "USD")

            if price_usd <= 0:
                continue

            # [E3] Validar moneda — solo USD para EBAY_US marketplace
            if currency != "USD":
                logger.debug(f"  Item en {currency} (no USD), omitido: {item.get('title','')[:40]}")
                continue

            # Filtrar precios absurdos
            if not (PRICE_MIN_USD <= price_usd <= PRICE_MAX_USD):
                logger.debug(f"  Precio fuera de rango: ${price_usd} — descartado")
                continue

            # [E2] Envío — ship_free solo True cuando shippingCost.value == '0.0' explícito
            shipping_options = item.get("shippingOptions", [])
            ship_cost = None
            ship_free = False
            if shipping_options:
                ship_raw = shipping_options[0].get("shippingCost", {}).get("value")
                if ship_raw is not None:
                    ship_cost = float(ship_raw)
                    ship_free = (ship_cost == 0.0)   # Solo True si explícitamente 0.0
            # Si shippingOptions=[] → ship_cost=None, ship_free=False (desconocido)

            # Condición robusta
            condition_raw = item.get("condition", "")
            if isinstance(condition_raw, list):
                condition = condition_raw[0] if condition_raw else "Unknown"
            else:
                condition = str(condition_raw) if condition_raw else "Unknown"

            # seller_feedback como int
            seller_info     = item.get("seller", {})
            feedback_raw    = seller_info.get("feedbackScore", None)
            seller_feedback = None
            if feedback_raw is not None:
                try:
                    seller_feedback = int(feedback_raw)
                except (ValueError, TypeError):
                    seller_feedback = None

            records.append({
                "batch_id":        batch_id,
                "timestamp":       now_iso,
                "source":          "ebay_usa",
                "query":           query,
                "category_label":  label,
                "item_id":         item.get("itemId", ""),
                "title":           item.get("title", ""),
                "price_usd":       price_usd,
                "currency":        currency,
                "shipping_usd":    ship_cost,
                "shipping_free":   ship_free,
                "condition":       condition,
                "location":        item.get("itemLocation", {}).get("city", ""),
                "country":         item.get("itemLocation", {}).get("country", ""),
                "seller_feedback": seller_feedback,
                "url":             item.get("itemWebUrl", ""),
                "image_url":       item.get("image", {}).get("imageUrl", ""),
            })

        except (KeyError, ValueError, TypeError) as e:
            logger.debug(f"Error parseando item eBay: {e}")
            continue

    return records


# ──────────────────────────────────────────────
# SCRAPER PRINCIPAL
# ──────────────────────────────────────────────
def scrape_ebay(batch_id: str) -> list:
    """
    Scraper principal eBay — Browse API REST v1.
    Retorna lista de dicts con precios de mercado USA.
    """
    if not EBAY_APP_ID:
        logger.error(
            "❌ EBAY_APP_ID no configurado. "
            "Agregar a GitHub Secrets y al env del workflow."
        )
        return []

    token = _get_oauth_token()
    if not token:
        logger.error("❌ No se pudo obtener token OAuth2 de eBay.")
        return []

    headers = {
        "Authorization":           f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Content-Type":            "application/json",
    }

    all_records   = []
    seen_item_ids = set()
    seen_fps      = set()    # [E5] fingerprints para items sin item_id
    total_queries = len(EBAY_QUERIES)

    for q_idx, (query, category_id, label) in enumerate(EBAY_QUERIES, 1):
        logger.info(f"[eBay] Query {q_idx}/{total_queries}: '{query}' (cat={category_id})")
        query_records = []

        # [E4] While loop — 401 no consume páginas del contador
        page   = 0
        offset = 0

        while page < MAX_PAGES:
            try:
                # [E8] conditions ampliado: NEW|USED|VERY_GOOD|GOOD
                params = {
                    "q":            query,
                    "category_ids": category_id,
                    "filter":       (
                        "buyingOptions:{FIXED_PRICE},"
                        "conditions:{NEW|USED|VERY_GOOD|GOOD}"
                    ),
                    "sort":         "price",
                    "limit":        ITEMS_PER_PAGE,
                    "offset":       offset,
                    "fieldgroups":  "MATCHING_ITEMS",
                }

                resp = requests.get(
                    BROWSE_API_URL,
                    headers=headers,
                    params=params,
                    timeout=15,
                )

                # [E4] 401 — renovar token SIN avanzar el contador de páginas
                if resp.status_code == 401:
                    logger.warning("[eBay] Token expirado — renovando...")
                    _token_cache.clear()
                    token = _get_oauth_token()
                    if not token:
                        break
                    headers["Authorization"] = f"Bearer {token}"
                    # NO incrementar page ni offset → reintentar la misma página
                    time.sleep(REQUEST_DELAY)
                    continue

                resp.raise_for_status()
                data = resp.json()

                items       = data.get("itemSummaries", [])
                total_found = int(data.get("total", 0))

                if not items:
                    if total_found == 0:
                        logger.debug(f"  Query '{query}': sin resultados")
                    break

                parsed = _parse_items_browse(items, query, label, batch_id)
                query_records.extend(parsed)

                logger.debug(
                    f"  Página {page + 1}: +{len(parsed)} items "
                    f"(offset={offset}, total={total_found})"
                )

                page   += 1
                offset += ITEMS_PER_PAGE

                if offset >= total_found:
                    break

                time.sleep(REQUEST_DELAY)

            except requests.RequestException as e:
                logger.warning(f"  [eBay] Error en página {page + 1}: {e}")
                time.sleep(3)
                break
            except (KeyError, ValueError) as e:
                logger.warning(f"  [eBay] Error parseando respuesta: {e}")
                break

        all_records.extend(query_records)
        logger.info(f"  ✅ '{query}': {len(query_records)} registros")
        time.sleep(REQUEST_DELAY)

    # Deduplicación
    unique_records = []
    for r in all_records:
        iid = r.get("item_id", "")
        if iid:
            if iid not in seen_item_ids:
                seen_item_ids.add(iid)
                unique_records.append(r)
        else:
            # [E5] Sin item_id → fingerprint title[:60]|price
            fp = hashlib.md5(
                f"{r.get('title','')[:60]}|{r.get('price_usd',0)}".encode()
            ).hexdigest()[:12]
            if fp not in seen_fps:
                seen_fps.add(fp)
                unique_records.append(r)

    dupes = len(all_records) - len(unique_records)
    if dupes:
        logger.info(f"[eBay] Deduplicados: {dupes} registros eliminados")

    logger.info(f"[eBay] TOTAL: {len(unique_records)} registros únicos")
    return unique_records


# ──────────────────────────────────────────────
# STANDALONE
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO)
    # [E7] datetime con timezone explícita
    test_batch = f"test_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    results    = scrape_ebay(test_batch)
    print(f"\nTotal registros: {len(results)}")
    if results:
        print("Ejemplo:", results[0])
