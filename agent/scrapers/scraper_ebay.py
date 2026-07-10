"""
scraper_ebay.py  v2.0
eBay Browse API (REST) — Precios de mercado USA en tiempo real

MIGRACIÓN v2.0:
  - findCompletedItems (Finding API v1) fue DEPRECADA en Oct 2023
  - Migrado a Browse API REST con OAuth2 Client Credentials
  - Endpoint: GET /buy/browse/v1/item_summary/search

Requiere en GitHub Secrets:
  - EBAY_APP_ID      (Client ID)
  - EBAY_CLIENT_SECRET

Registro gratuito: https://developer.ebay.com/my/keys

Fixes v2.0:
  - [FIX-1] Migración a Browse API REST (findCompletedItems deprecada)
  - [FIX-2] OAuth2 Client Credentials flow (_get_oauth_token)
  - [FIX-3] Incluir condición Used (3000) para rango completo de precios
  - [FIX-4] EBAY_CATEGORY_IDS conectado a las queries
  - [FIX-5] Filtro de precios absurdos ($5 - $10,000)
  - [FIX-6] shipping_usd: distingue gratis (0.0) vs desconocido (None)
  - [FIX-7] Deduplicación por item_id al final
  - [FIX-8] condition parsing robusto
  - [FIX-9] seller_feedback convertido a int
  - [FIX-10] MAX_PAGES reducido a 5 en modo normal (rate limit)
"""

import os
import time
import base64
import logging
import requests
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────
EBAY_APP_ID       = os.getenv("EBAY_APP_ID", "")        # Client ID
EBAY_CLIENT_SECRET= os.getenv("EBAY_CLIENT_SECRET", "") # Client Secret

# FIX-1: Browse API REST (reemplaza Finding API v1 deprecada)
BROWSE_API_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
OAUTH_URL      = "https://api.ebay.com/identity/v1/oauth2/token"
OAUTH_SCOPE    = "https://api.ebay.com/oauth/api_scope"

ITEMS_PER_PAGE = 200    # Browse API permite hasta 200
MAX_PAGES      = 5      # FIX-10: 5 × 200 = 1,000 items/query (era 10)
REQUEST_DELAY  = 0.8    # Aumentado ligeramente para Browse API

PRICE_MIN_USD  = 5.0    # FIX-5: filtro mínimo
PRICE_MAX_USD  = 10_000.0  # FIX-5: filtro máximo

# FIX-4: Queries con su categoría asociada
EBAY_QUERIES = [
    # (query, category_id, label)
    ("intel core i5 processor",       "164",   "cpu"),
    ("intel core i7 processor",       "164",   "cpu"),
    ("intel core i9 processor",       "164",   "cpu"),
    ("amd ryzen 5 processor",         "164",   "cpu"),
    ("amd ryzen 7 processor",         "164",   "cpu"),
    ("amd ryzen 9 processor",         "164",   "cpu"),
    ("nvidia rtx 4060 graphics card", "27386", "gpu"),
    ("nvidia rtx 4070 graphics card", "27386", "gpu"),
    ("nvidia rtx 4080 graphics card", "27386", "gpu"),
    ("amd rx 7600 graphics card",     "27386", "gpu"),
    ("amd rx 7700 graphics card",     "27386", "gpu"),
    ("ddr4 16gb ram",                 "170083","ram"),
    ("ddr4 32gb ram",                 "170083","ram"),
    ("ddr5 16gb ram",                 "170083","ram"),
    ("ddr5 32gb ram",                 "170083","ram"),
    ("nvme ssd 1tb",                  "56083", "storage"),
    ("nvme ssd 500gb",                "56083", "storage"),
    ("samsung 870 evo ssd",           "56083", "storage"),
    ("intel z790 motherboard",        "1244",  "motherboard"),
    ("amd b650 motherboard",          "1244",  "motherboard"),
    ("gaming laptop rtx 4060",        "177",   "laptop"),
    ("laptop intel i7 16gb",          "177",   "laptop"),
    ("gaming monitor 144hz 27 inch",  "80053", "monitor"),
    ("4k monitor 27 inch",            "80053", "monitor"),
    ("mechanical keyboard gaming",    "33963", "peripheral"),
    ("gaming mouse wireless",         "26252", "peripheral"),
]


# ──────────────────────────────────────────────
# FIX-2: OAuth2 Client Credentials
# ──────────────────────────────────────────────

_token_cache: dict = {}   # { "token": str, "expires_at": float }


def _get_oauth_token() -> Optional[str]:
    """
    Obtiene Bearer token via OAuth2 Client Credentials flow.
    Cachea el token hasta su expiración.
    """
    now = time.time()

    # Usar token cacheado si no expiró (con 60s de margen)
    if _token_cache.get("token") and now < _token_cache.get("expires_at", 0) - 60:
        return _token_cache["token"]

    if not EBAY_APP_ID or not EBAY_CLIENT_SECRET:
        logger.error(
            "❌ EBAY_APP_ID o EBAY_CLIENT_SECRET no configurados.\n"
            "   Regístralo en: https://developer.ebay.com/my/keys"
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

        logger.info(f"[eBay] OAuth2 token obtenido (expira en {expires_in//60} min)")
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
    """
    Parsea items de la Browse API REST.
    Estructura diferente a la Finding API v1.
    """
    records = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for item in items:
        try:
            # Precio
            price_info = item.get("price", {})
            price_usd  = float(price_info.get("value", 0))
            currency   = price_info.get("currency", "USD")

            if price_usd <= 0:
                continue

            # FIX-5: Filtrar precios absurdos
            if not (PRICE_MIN_USD <= price_usd <= PRICE_MAX_USD):
                logger.debug(f"  Precio fuera de rango: ${price_usd} — descartado")
                continue

            # FIX-6: Envío — distinguir gratis vs desconocido
            shipping_options = item.get("shippingOptions", [])
            if shipping_options:
                ship_raw = shipping_options[0].get("shippingCost", {}).get("value")
                if ship_raw is not None:
                    ship_cost = float(ship_raw)
                    ship_free = ship_cost == 0.0
                else:
                    ship_cost = None
                    ship_free = False
            else:
                ship_cost = None
                ship_free = item.get("shippingOptions") == []  # lista vacía = gratis en Browse API

            # FIX-8: Condición robusta
            condition_raw = item.get("condition", "")
            if isinstance(condition_raw, list):
                condition = condition_raw[0] if condition_raw else "Unknown"
            else:
                condition = str(condition_raw) if condition_raw else "Unknown"

            # FIX-9: seller_feedback como int
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
                "shipping_usd":    ship_cost,    # None = desconocido
                "shipping_free":   ship_free,    # FIX-6: bool explícito
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
        logger.error("❌ EBAY_APP_ID no configurado.")
        return []

    # FIX-2: Obtener token OAuth2
    token = _get_oauth_token()
    if not token:
        logger.error("❌ No se pudo obtener token OAuth2 de eBay.")
        return []

    headers = {
        "Authorization":              f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID":    "EBAY_US",
        "Content-Type":               "application/json",
    }

    all_records    = []
    seen_item_ids  = set()   # FIX-7: deduplicación
    total_queries  = len(EBAY_QUERIES)

    for q_idx, (query, category_id, label) in enumerate(EBAY_QUERIES, 1):
        logger.info(f"[eBay] Query {q_idx}/{total_queries}: '{query}' (cat={category_id})")
        query_records = []
        offset        = 0

        for page in range(1, MAX_PAGES + 1):
            try:
                # FIX-1: Browse API params
                # FIX-3: Incluir New (1000) + Used (3000) para rango completo
                params = {
                    "q":           query,
                    "category_ids": category_id,
                    "filter":      (
                        "buyingOptions:{FIXED_PRICE},"
                        "conditions:{NEW|USED}"          # FIX-3: New + Used
                    ),
                    "sort":        "price",              # Precio ascendente
                    "limit":       ITEMS_PER_PAGE,
                    "offset":      offset,
                    "fieldgroups": "MATCHING_ITEMS",
                }

                resp = requests.get(
                    BROWSE_API_URL,
                    headers=headers,
                    params=params,
                    timeout=15,
                )

                # Manejar token expirado
                if resp.status_code == 401:
                    logger.warning("[eBay] Token expirado — renovando...")
                    _token_cache.clear()
                    token  = _get_oauth_token()
                    if not token:
                        break
                    headers["Authorization"] = f"Bearer {token}"
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
                    f"  Página {page}: +{len(parsed)} items "
                    f"(offset={offset}, total={total_found})"
                )

                offset += ITEMS_PER_PAGE
                if offset >= total_found or offset >= ITEMS_PER_PAGE * MAX_PAGES:
                    break

                time.sleep(REQUEST_DELAY)

            except requests.RequestException as e:
                logger.warning(f"  [eBay] Error en página {page}: {e}")
                time.sleep(3)
                break
            except (KeyError, ValueError) as e:
                logger.warning(f"  [eBay] Error parseando respuesta: {e}")
                break

        all_records.extend(query_records)
        logger.info(f"  ✅ '{query}': {len(query_records)} registros")
        time.sleep(REQUEST_DELAY)

    # FIX-7: Deduplicar por item_id
    unique_records = []
    for r in all_records:
        iid = r.get("item_id", "")
        if iid and iid not in seen_item_ids:
            seen_item_ids.add(iid)
            unique_records.append(r)
        elif not iid:
            unique_records.append(r)  # Sin item_id → conservar

    dupes = len(all_records) - len(unique_records)
    if dupes:
        logger.info(f"[eBay] Deduplicados: {dupes} registros eliminados")

    logger.info(f"[eBay] TOTAL: {len(unique_records)} registros únicos")
    return unique_records


# ──────────────────────────────────────────────
# STANDALONE
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_batch = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results    = scrape_ebay(test_batch)
    print(f"\nTotal registros: {len(results)}")
    if results:
        print("Ejemplo:", results[0])
