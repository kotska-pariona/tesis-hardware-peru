"""
scraper_ebay.py
eBay Finding API — Historial de ventas completadas (últimos 90 días)
Documentación: https://developer.ebay.com/devzone/finding/concepts/findingapiguide.html

Requiere: EBAY_APP_ID en secrets (gratuito en developer.ebay.com)
"""

import os
import time
import logging
import requests
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────
EBAY_APP_ID   = os.getenv("EBAY_APP_ID", "")
FINDING_API   = "https://svcs.ebay.com/services/search/FindingService/v1"
ITEMS_PER_PAGE = 100   # máximo permitido por eBay
MAX_PAGES      = 10    # 10 × 100 = 1,000 items por query
REQUEST_DELAY  = 0.5   # segundos entre requests

# Queries de hardware — ampliar según necesidad
EBAY_QUERIES = [
    # Procesadores
    "intel core i5 processor",
    "intel core i7 processor",
    "intel core i9 processor",
    "amd ryzen 5 processor",
    "amd ryzen 7 processor",
    "amd ryzen 9 processor",
    # Tarjetas de video
    "nvidia rtx 4060 graphics card",
    "nvidia rtx 4070 graphics card",
    "nvidia rtx 4080 graphics card",
    "amd rx 7600 graphics card",
    "amd rx 7700 graphics card",
    # RAM
    "ddr4 16gb ram",
    "ddr4 32gb ram",
    "ddr5 16gb ram",
    "ddr5 32gb ram",
    # Almacenamiento
    "nvme ssd 1tb",
    "nvme ssd 500gb",
    "samsung 870 evo ssd",
    # Motherboards
    "intel z790 motherboard",
    "amd b650 motherboard",
    # Laptops
    "gaming laptop rtx 4060",
    "laptop intel i7 16gb",
    # Monitores
    "gaming monitor 144hz 27 inch",
    "4k monitor 27 inch",
    # Periféricos
    "mechanical keyboard gaming",
    "gaming mouse wireless",
]

# Categorías eBay para filtrar (opcional, mejora precisión)
EBAY_CATEGORY_IDS = {
    "procesadores": "164",
    "tarjetas_video": "27386",
    "ram": "170083",
    "almacenamiento": "56083",
    "motherboards": "1244",
    "laptops": "177",
    "monitores": "80053",
}


# ──────────────────────────────────────────────
# FUNCIONES CORE
# ──────────────────────────────────────────────

def _build_params(query: str, page: int, completed: bool = True) -> dict:
    """Construye los parámetros para la Finding API."""
    operation = "findCompletedItems" if completed else "findItemsByKeywords"
    return {
        "OPERATION-NAME":          operation,
        "SERVICE-VERSION":         "1.13.0",
        "SECURITY-APPNAME":        EBAY_APP_ID,
        "RESPONSE-DATA-FORMAT":    "JSON",
        "REST-PAYLOAD":            "",
        "keywords":                query,
        "paginationInput.entriesPerPage": ITEMS_PER_PAGE,
        "paginationInput.pageNumber":     page,
        "itemFilter(0).name":      "ListingType",
        "itemFilter(0).value":     "FixedPrice",
        "itemFilter(1).name":      "Condition",
        "itemFilter(1).value(0)":  "1000",   # New
        "itemFilter(1).value(1)":  "1500",   # New other
        "sortOrder":               "EndTimeSoonest",
        "outputSelector(0)":       "SellerInfo",
        "outputSelector(1)":       "StoreInfo",
    }


def _parse_items(raw_items: list, query: str, batch_id: str) -> list:
    """Parsea los items crudos de la API a registros normalizados."""
    records = []
    now_iso  = datetime.now(timezone.utc).isoformat()

    for item in raw_items:
        try:
            # Precio
            selling = item.get("sellingStatus", [{}])[0]
            price_info = selling.get("currentPrice", [{}])[0]
            price_usd  = float(price_info.get("__value__", 0))
            currency   = price_info.get("@currencyId", "USD")

            if price_usd <= 0:
                continue

            # Envío
            shipping_info = item.get("shippingInfo", [{}])[0]
            ship_cost_raw = (
                shipping_info
                .get("shippingServiceCost", [{}])[0]
                .get("__value__", None)
            )
            ship_cost = float(ship_cost_raw) if ship_cost_raw is not None else None

            # Condición
            condition_list = item.get("condition", [{}])
            condition = condition_list[0].get("conditionDisplayName", ["New"])[0] if condition_list else "New"

            # Fechas
            end_time = item.get("listingInfo", [{}])[0].get("endTime", [now_iso])[0]

            record = {
                "batch_id":        batch_id,
                "timestamp":       now_iso,
                "source":          "ebay_usa",
                "query":           query,
                "item_id":         item.get("itemId", [""])[0],
                "title":           item.get("title", [""])[0],
                "price_usd":       price_usd,
                "currency":        currency,
                "shipping_usd":    ship_cost,
                "condition":       condition,
                "location":        item.get("location", [""])[0],
                "country":         item.get("country", [""])[0],
                "end_time":        end_time,
                "seller_feedback": (
                    item.get("sellerInfo", [{}])[0]
                    .get("feedbackScore", [None])[0]
                ),
                "url": (
                    item.get("viewItemURL", [""])[0]
                ),
            }
            records.append(record)

        except (KeyError, IndexError, ValueError, TypeError) as e:
            logger.debug(f"Error parseando item eBay: {e}")
            continue

    return records


def scrape_ebay(batch_id: str) -> list:
    """
    Scraper principal de eBay.
    Retorna lista de dicts con precios históricos (ventas completadas).
    """
    if not EBAY_APP_ID:
        logger.error("❌ EBAY_APP_ID no configurado. Agrega el secret en GitHub.")
        return []

    all_records = []
    total_queries = len(EBAY_QUERIES)

    for q_idx, query in enumerate(EBAY_QUERIES, 1):
        logger.info(f"[eBay] Query {q_idx}/{total_queries}: '{query}'")
        query_records = []

        for page in range(1, MAX_PAGES + 1):
            try:
                params = _build_params(query, page, completed=True)
                resp = requests.get(
                    FINDING_API,
                    params=params,
                    timeout=15,
                    headers={"User-Agent": "tesis-hardware-peru/1.0"}
                )
                resp.raise_for_status()
                data = resp.json()

                # Navegar la respuesta anidada de eBay
                search_result = (
                    data
                    .get("findCompletedItemsResponse", [{}])[0]
                    .get("searchResult", [{}])[0]
                )
                total_entries = int(
                    data
                    .get("findCompletedItemsResponse", [{}])[0]
                    .get("paginationOutput", [{}])[0]
                    .get("totalEntries", ["0"])[0]
                )
                raw_items = search_result.get("item", [])

                if not raw_items:
                    logger.debug(f"  Página {page}: sin items. Fin de paginación.")
                    break

                parsed = _parse_items(raw_items, query, batch_id)
                query_records.extend(parsed)

                logger.debug(
                    f"  Página {page}: +{len(parsed)} items "
                    f"(total disponible: {total_entries})"
                )

                # Si ya obtuvimos todos los disponibles, parar
                if len(query_records) >= total_entries:
                    break

                time.sleep(REQUEST_DELAY)

            except requests.RequestException as e:
                logger.warning(f"  [eBay] Error en página {page}: {e}")
                time.sleep(2)
                break
            except (KeyError, IndexError, ValueError) as e:
                logger.warning(f"  [eBay] Error parseando respuesta página {page}: {e}")
                break

        all_records.extend(query_records)
        logger.info(f"  ✅ Query '{query}': {len(query_records)} registros")
        time.sleep(REQUEST_DELAY)

    logger.info(f"[eBay] TOTAL: {len(all_records)} registros recolectados")
    return all_records


# ──────────────────────────────────────────────
# EJECUCIÓN STANDALONE (debug)
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_batch = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results = scrape_ebay(test_batch)
    print(f"\nTotal registros: {len(results)}")
    if results:
        print("Ejemplo:", results[0])
