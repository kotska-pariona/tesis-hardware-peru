"""
pipeline.py — Orquestador principal
Fuentes: Falabella PE + Hiraoka PE + Coolbox PE
"""
import logging, csv, json, os, sys
from datetime import datetime, timezone
from collections import Counter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Importar scrapers ────────────────────────────────────────────────
from scraper_competencia import scrape_coolbox

# Ajusta estos imports según tus nombres de archivo reales
try:
    from scraper_falabella import scrape_falabella
except ImportError:
    logger.warning("scraper_falabella no encontrado — se omitirá")
    scrape_falabella = None

try:
    from scraper_hiraoka import scrape_hiraoka
except ImportError:
    logger.warning("scraper_hiraoka no encontrado — se omitirá")
    scrape_hiraoka = None

# ── Schema maestro (columnas en orden) ───────────────────────────────
SCHEMA = [
    "batch_id", "source", "currency", "category",
    "sku", "product_id", "name", "brand",
    "price_pen", "price_orig_pen", "discount_pct",
    "available_qty", "url",
]

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")


def normalize(record: dict) -> dict:
    """Garantiza que todos los campos del schema existan."""
    return {col: record.get(col, "") for col in SCHEMA}


def dedup(records: list) -> tuple[list, int]:
    """Deduplicación por (source, sku). Retorna (únicos, n_eliminados)."""
    seen, unique = set(), []
    for r in records:
        key = (r.get("source",""), r.get("sku",""))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique, len(records) - len(unique)


def run_pipeline(batch_id: str = None) -> list[dict]:
    if batch_id is None:
        batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")

    logger.info(f"{'='*55}")
    logger.info(f"  PIPELINE START  batch_id={batch_id}")
    logger.info(f"{'='*55}")

    all_records = []

    # ── Falabella ────────────────────────────────────────────────────
    if scrape_falabella:
        logger.info("▶ Scraping Falabella...")
        try:
            recs = scrape_falabella(batch_id=batch_id)
            all_records.extend(recs)
            logger.info(f"  Falabella   → {len(recs)} productos")
        except Exception as e:
            logger.error(f"  Falabella FAILED: {e}")
    else:
        logger.info("  Falabella   → OMITIDA (módulo no disponible)")

    # ── Hiraoka ──────────────────────────────────────────────────────
    if scrape_hiraoka:
        logger.info("▶ Scraping Hiraoka...")
        try:
            recs = scrape_hiraoka(batch_id=batch_id)
            all_records.extend(recs)
            logger.info(f"  Hiraoka     → {len(recs)} productos")
        except Exception as e:
            logger.error(f"  Hiraoka FAILED: {e}")
    else:
        logger.info("  Hiraoka     → OMITIDA (módulo no disponible)")

    # ── Coolbox ──────────────────────────────────────────────────────
    logger.info("▶ Scraping Coolbox...")
    try:
        recs = scrape_coolbox(batch_id=batch_id)
        all_records.extend(recs)
        logger.info(f"  Coolbox     → {len(recs)} productos")
    except Exception as e:
        logger.error(f"  Coolbox FAILED: {e}")

    # ── Dedup + normalización ─────────────────────────────────────────
    unique, n_dup = dedup(all_records)
    normalized    = [normalize(r) for r in unique]

    # ── Resumen ───────────────────────────────────────────────────────
    logger.info(f"\n{'─'*55}")
    logger.info(f"  RAW total   : {len(all_records)}")
    logger.info(f"  Duplicados  : {n_dup}")
    logger.info(f"  ÚNICOS      : {len(normalized)}")
    logger.info(f"\n  Por fuente:")
    for src, cnt in Counter(r["source"] for r in normalized).items():
        logger.info(f"    {src:<20} {cnt:>4}")
    logger.info(f"\n  Por categoría:")
    for cat, cnt in sorted(Counter(r["category"] for r in normalized).items()):
        logger.info(f"    {cat:<14} {cnt:>4}")

    # ── Guardar CSV ───────────────────────────────────────────────────
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    csv_path  = os.path.join(OUTPUT_DIR, f"precios_{batch_id}.csv")
    json_path = os.path.join(OUTPUT_DIR, f"precios_{batch_id}.json")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA)
        writer.writeheader()
        writer.writerows(normalized)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)

    logger.info(f"\n  CSV  → {csv_path}")
    logger.info(f"  JSON → {json_path}")
    logger.info(f"{'='*55}")

    return normalized


if __name__ == "__main__":
    bid = sys.argv[1] if len(sys.argv) > 1 else None
    run_pipeline(batch_id=bid)
