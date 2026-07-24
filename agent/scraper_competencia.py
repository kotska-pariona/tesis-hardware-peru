import requests, time, logging
from datetime import datetime

logger = logging.getLogger(__name__)

BASE     = "https://www.coolbox.pe"
GQL_URL  = f"{BASE}/_v/segment/graphql/v1"
HEADERS  = {
    "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept":       "application/json",
}

GQL_QUERY = """
query($selectedFacets:[SelectedFacetInput], $from:Int, $to:Int) {
  productSearch(
    selectedFacets: $selectedFacets
    from: $from
    to: $to
    hideUnavailableItems: true
    orderBy: "OrderByScoreDESC"
  ) @context(provider: "vtex.search-graphql@0.x") {
    products {
      productId
      productName
      brand
      link
      items {
        itemId
        sellers {
          commertialOffer {
            Price
            ListPrice
            AvailableQuantity
          }
        }
      }
    }
    recordsFiltered
  }
}
"""

CURRENCY = "PEN"

CAT_FACETS = {
    "CPU":         [{"key": "category-3", "value": "procesadores"}],
    "GPU":         [{"key": "category-3", "value": "tarjetas-de-v%C3%ADdeo"}],
    "RAM":         [{"key": "category-3", "value": "memorias-ram"}],
    "SSD":         [{"key": "category-3", "value": "discos-internos-y-ssd"}],
    "MOTHERBOARD": [{"key": "category-3", "value": "placas-madres"}],
    "PSU":         [{"key": "category-3", "value": "fuentes-de-poder"}],
    "COOLER":      [{"key": "category-3", "value": "sistemas-de-enfriamiento-y-ventiladores"}],
    "CASE":        [{"key": "category-3", "value": "cases-de-pc"}],
}

PAGE_SIZE = 48


def _fetch_page(facets, page_from):
    resp = requests.post(
        GQL_URL, headers=HEADERS,
        json={"query": GQL_QUERY, "variables": {
            "selectedFacets": facets,
            "from": page_from,
            "to":   page_from + PAGE_SIZE - 1,
        }},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def scrape_coolbox(batch_id=None):
    if batch_id is None:
        batch_id = datetime.utcnow().strftime("%Y%m%d_%H%M")

    all_records = []
    seen_ids    = set()

    for cat, facets in CAT_FACETS.items():
        cat_records = []
        page_from   = 0
        retries     = 0

        while True:
            try:
                data = _fetch_page(facets, page_from)
            except Exception as e:
                logger.warning(f"[Coolbox] {cat} from={page_from} ERR: {e}")
                retries += 1
                if retries >= 3:
                    break
                time.sleep(2 ** retries)
                continue

            retries = 0

            if "errors" in data:
                logger.error(f"[Coolbox] GQL error {cat}: {data['errors'][0]['message'][:120]}")
                break

            ps       = data.get("data", {}).get("productSearch", {})
            products = ps.get("products", [])
            total    = ps.get("recordsFiltered", 0)

            for p in products:
                pid = p.get("productId", "")
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)

                items = p.get("items", [])
                if not items:
                    continue
                sku     = items[0]
                sku_id  = sku.get("itemId", "")
                sellers = sku.get("sellers", [])
                if not sellers:
                    continue

                offer      = sellers[0].get("commertialOffer", {})
                price      = offer.get("Price")
                list_price = offer.get("ListPrice")
                avail_qty  = offer.get("AvailableQuantity", 0)

                if not price or price == 0:
                    continue

                discount_pct = (
                    round((1 - price / list_price) * 100, 1)
                    if list_price and list_price > price else 0.0
                )

                link = p.get("link", "")
                cat_records.append({
                    "batch_id":       batch_id,
                    "source":         "coolbox_pe",
                    "currency":       CURRENCY,
                    "category":       cat,
                    "sku":            sku_id,
                    "product_id":     pid,
                    "name":           p.get("productName", ""),
                    "brand":          p.get("brand", ""),
                    "price_pen":      price,
                    "price_orig_pen": list_price,
                    "discount_pct":   discount_pct,
                    "available_qty":  avail_qty,
                    "url": f"{BASE}{link}" if link.startswith("/") else link,
                })

            page_from += PAGE_SIZE
            if page_from >= total:
                break
            time.sleep(0.5)

        all_records.extend(cat_records)
        logger.info(f"[Coolbox] {cat:<12} -> {len(cat_records):>3} productos (currency={CURRENCY})")
        time.sleep(0.4)

    logger.info(f"[Coolbox] TOTAL {len(all_records)} productos | batch={batch_id}")
    return all_records
