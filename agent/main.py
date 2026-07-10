"""
main.py — Orquestador v5.1 (Objetivo 1: Máxima recolección de datos)
════════════════════════════════════════════════════════════════════
Modos:
  python main.py                        → normal (local PE + eBay)
  python main.py --mode local_only      → solo Falabella/Ripley/Hiraoka
  python main.py --mode historical      → eBay + CamelCamelCamel + PCPartPicker
  python main.py --mode kaggle_only     → solo Kaggle datasets
  python main.py --mode full            → todo (~86 min — supera timeout de 55 min)
  python main.py --batch-id XXXX        → batch ID manual

Fixes v5.1:
  - [FIX-1] merge_to_master: deduplicación por (source, sku, price_date)
  - [FIX-2] scraper_importacion y scraper_competencia integrados (opcionales)
  - [FIX-3] save_report: excluye master_total del total de scrapers
  - [FIX-4] imports unificados via __init__.py
  - [FIX-5] save_batch: orden de columnas lógico (no alfabético)
  - [FIX-6] LOG_FILE movido a data/logs/
  - [FIX-7] Nota de timeout en modo 'full'
"""

import sys
import os
import csv
import json
import logging
import argparse
import time
from pathlib import Path
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────────
AGENT_DIR = Path(__file__).resolve().parent
ROOT_DIR  = AGENT_DIR.parent
DATA_DIR  = ROOT_DIR / "data" / "raw"
LOG_DIR   = ROOT_DIR / "data" / "logs"   # FIX-6: separado de los datos
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(AGENT_DIR))

# ── Logging ───────────────────────────────────────────────────────────────
LOG_FILE = LOG_DIR / "agent.log"   # FIX-6
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
    ],
)
log = logging.getLogger("main")

# ── FIX-4: Imports unificados via __init__.py ─────────────────────────────
from scrapers import (
    scrape_local,
    scrape_dolar,
    scrape_ebay,
    scrape_camel,
    scrape_pcpartpicker,
    scrape_kaggle,
    scrape_importacion,   # None si el módulo no está listo
    scrape_competencia,   # None si el módulo no está listo
    _HAS_IMPORTACION,
    _HAS_COMPETENCIA,
)

# ── FIX-5: Orden lógico de columnas en CSV ────────────────────────────────
FIELD_ORDER = [
    "batch_id", "timestamp", "source", "category",
    "sku", "brand", "title",
    "price_pen", "price_orig_pen", "price_usd", "price_date",
    "discount_pct", "price_currency",
    "rating", "reviews",
    "retailer", "part_id", "url",
]


# ══════════════════════════════════════════════════════════════════════════
# GUARDAR REGISTROS EN CSV
# ══════════════════════════════════════════════════════════════════════════

def save_batch(records: list, batch_id: str, source_tag: str) -> Path:
    """Guarda una lista de registros en data/raw/batch_{batch_id}_{tag}.csv"""
    if not records:
        log.warning(f"  [save] Sin registros para {source_tag}")
        return None

    out_path = DATA_DIR / f"batch_{batch_id}_{source_tag}.csv"

    # FIX-5: Orden lógico — columnas conocidas primero, resto alfabético al final
    all_keys  = set(k for r in records for k in r.keys())
    ordered   = [f for f in FIELD_ORDER if f in all_keys]
    remainder = sorted(all_keys - set(ordered))
    fieldnames = ordered + remainder

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    log.info(f"  💾 Guardado: {out_path.name} ({len(records):,} registros)")
    return out_path


# ══════════════════════════════════════════════════════════════════════════
# MERGE AL MASTER
# ══════════════════════════════════════════════════════════════════════════

def merge_to_master(batch_files: list) -> int:
    """
    Agrega todos los batch CSV al MASTER_hardware_peru.csv.
    FIX-1: Deduplicación por (source, sku, price_date) para evitar inflado.
    """
    master_path = DATA_DIR / "MASTER_hardware_peru.csv"
    new_records = []
    all_fields  = set(FIELD_ORDER)

    # Leer batch files nuevos
    for f in batch_files:
        if f is None or not f.exists():
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                rows   = list(reader)
                new_records.extend(rows)
                all_fields.update(reader.fieldnames or [])
        except Exception as e:
            log.warning(f"  Error leyendo {f.name}: {e}")

    if not new_records:
        log.warning("  [master] Sin registros nuevos para agregar")
        return 0

    # Leer master existente
    existing_records = []
    existing_keys    = set()

    if master_path.exists():
        try:
            with open(master_path, encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    existing_records.append(row)
                    all_fields.update(row.keys())
                    # FIX-1: Construir set de claves existentes
                    dedup_key = (
                        row.get("source", ""),
                        row.get("sku", ""),
                        row.get("price_date", ""),
                    )
                    existing_keys.add(dedup_key)
        except Exception as e:
            log.warning(f"  Error leyendo MASTER: {e}")

    # FIX-1: Solo agregar registros que no existen ya
    added   = 0
    skipped = 0
    for row in new_records:
        dedup_key = (
            row.get("source", ""),
            row.get("sku", ""),
            row.get("price_date", ""),
        )
        # Registros sin SKU (ej: tipo de cambio) siempre se agregan
        if not row.get("sku") or dedup_key not in existing_keys:
            existing_records.append(row)
            existing_keys.add(dedup_key)
            added += 1
        else:
            skipped += 1

    if skipped:
        log.info(f"  [master] Deduplicados: {skipped:,} registros omitidos (ya existen)")

    # FIX-5: Orden lógico de columnas
    ordered    = [f for f in FIELD_ORDER if f in all_fields]
    remainder  = sorted(all_fields - set(ordered))
    fieldnames = ordered + remainder

    with open(master_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(existing_records)

    total = len(existing_records)
    log.info(f"  📊 MASTER actualizado: {total:,} registros totales (+{added:,} nuevos)")
    return total


# ══════════════════════════════════════════════════════════════════════════
# REPORTE JSON
# ══════════════════════════════════════════════════════════════════════════

def save_report(batch_id: str, stats: dict, elapsed: float):
    # FIX-3: excluir master_total del total de scrapers
    scraper_keys = [k for k in stats if k != "master_total"]
    report = {
        "batch_id":     batch_id,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "elapsed_s":    round(elapsed, 1),
        "stats":        stats,
        "total_new":    sum(stats[k] for k in scraper_keys if isinstance(stats[k], int)),
        "master_total": stats.get("master_total", 0),
    }
    report_path = DATA_DIR / f"report_{batch_id}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    log.info(f"  📋 Reporte: {report_path.name}")
    return report


# ══════════════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════

def run(mode: str, batch_id: str):
    start   = time.time()
    stats   = {}
    batches = []

    log.info("═" * 60)
    log.info(f"  PIPELINE v5.1 — modo={mode} | batch={batch_id}")
    log.info("═" * 60)

    # ── 1. Tipo de cambio (siempre) ────────────────────────────────────
    log.info("\n[1/8] 💱 Tipo de cambio USD/PEN")
    try:
        dolar_records = scrape_dolar(batch_id)
        p = save_batch(dolar_records, batch_id, "dolar")
        batches.append(p)
        stats["dolar"] = len(dolar_records)
        log.info(f"  ✅ Dolar: {len(dolar_records)} registros")
    except Exception as e:
        log.error(f"  ❌ Dolar: {e}")
        stats["dolar"] = 0

    # ── 2. Scrapers locales PE ─────────────────────────────────────────
    if mode in ("normal", "local_only", "full"):
        log.info("\n[2/8] 🇵🇪 Tiendas locales PE (Falabella / Ripley / Hiraoka)")
        try:
            local_records = scrape_local(batch_id)
            p = save_batch(local_records, batch_id, "local")
            batches.append(p)
            stats["local"] = len(local_records)
            log.info(f"  ✅ Local PE: {len(local_records):,} registros")
        except Exception as e:
            log.error(f"  ❌ Local PE: {e}")
            stats["local"] = 0
    else:
        stats["local"] = 0

    # ── 3. eBay ────────────────────────────────────────────────────────
    if mode in ("normal", "historical", "full"):
        log.info("\n[3/8] 🛒 eBay USA (ventas completadas 90 días)")
        try:
            ebay_records = scrape_ebay(batch_id)
            p = save_batch(ebay_records, batch_id, "ebay")
            batches.append(p)
            stats["ebay"] = len(ebay_records)
            log.info(f"  ✅ eBay: {len(ebay_records):,} registros")
        except Exception as e:
            log.error(f"  ❌ eBay: {e}")
            stats["ebay"] = 0
    else:
        stats["ebay"] = 0

    # ── 4. CamelCamelCamel ─────────────────────────────────────────────
    if mode in ("historical", "full"):
        log.info("\n[4/8] 🐪 CamelCamelCamel (historial Amazon)")
        try:
            camel_records = scrape_camel(batch_id)
            p = save_batch(camel_records, batch_id, "camel")
            batches.append(p)
            stats["camel"] = len(camel_records)
            log.info(f"  ✅ Camel: {len(camel_records):,} registros")
        except Exception as e:
            log.error(f"  ❌ Camel: {e}")
            stats["camel"] = 0
    else:
        stats["camel"] = 0

    # ── 5. PCPartPicker ────────────────────────────────────────────────
    if mode in ("historical", "full"):
        log.info("\n[5/8] 🖥️ PCPartPicker (historial USA multi-tienda)")
        try:
            pcp_records = scrape_pcpartpicker(batch_id)
            p = save_batch(pcp_records, batch_id, "pcpartpicker")
            batches.append(p)
            stats["pcpartpicker"] = len(pcp_records)
            log.info(f"  ✅ PCPartPicker: {len(pcp_records):,} registros")
        except Exception as e:
            log.error(f"  ❌ PCPartPicker: {e}")
            stats["pcpartpicker"] = 0
    else:
        stats["pcpartpicker"] = 0

    # ── 6. Kaggle ──────────────────────────────────────────────────────
    if mode in ("kaggle_only", "full"):
        log.info("\n[6/8] 📦 Kaggle datasets (bulk histórico)")
        try:
            kaggle_records = scrape_kaggle(batch_id)
            p = save_batch(kaggle_records, batch_id, "kaggle")
            batches.append(p)
            stats["kaggle"] = len(kaggle_records)
            log.info(f"  ✅ Kaggle: {len(kaggle_records):,} registros")
        except Exception as e:
            log.error(f"  ❌ Kaggle: {e}")
            stats["kaggle"] = 0
    else:
        stats["kaggle"] = 0

    # ── 7. FIX-2: Importación (si está disponible) ────────────────────
    if _HAS_IMPORTACION and mode in ("normal", "historical", "full"):
        log.info("\n[7/8] 📦 Precios de importación")
        try:
            imp_records = scrape_importacion(batch_id)
            p = save_batch(imp_records, batch_id, "importacion")
            batches.append(p)
            stats["importacion"] = len(imp_records)
            log.info(f"  ✅ Importación: {len(imp_records):,} registros")
        except Exception as e:
            log.error(f"  ❌ Importación: {e}")
            stats["importacion"] = 0
    else:
        stats["importacion"] = 0

    # ── 8. FIX-2: Competencia (si está disponible) ────────────────────
    if _HAS_COMPETENCIA and mode in ("normal", "local_only", "full"):
        log.info("\n[8/8] 🔍 Análisis de competencia local PE")
        try:
            comp_records = scrape_competencia(batch_id)
            p = save_batch(comp_records, batch_id, "competencia")
            batches.append(p)
            stats["competencia"] = len(comp_records)
            log.info(f"  ✅ Competencia: {len(comp_records):,} registros")
        except Exception as e:
            log.error(f"  ❌ Competencia: {e}")
            stats["competencia"] = 0
    else:
        stats["competencia"] = 0

    # ── Merge al MASTER ────────────────────────────────────────────────
    log.info("\n[MERGE] Actualizando MASTER_hardware_peru.csv...")
    master_total = merge_to_master([b for b in batches if b])
    stats["master_total"] = master_total

    # ── Reporte ────────────────────────────────────────────────────────
    elapsed = time.time() - start
    report  = save_report(batch_id, stats, elapsed)

    # ── Resumen final ──────────────────────────────────────────────────
    log.info("\n" + "═" * 60)
    log.info("  RESUMEN FINAL")
    log.info("═" * 60)
    log.info(f"  Batch ID     : {batch_id}")
    log.info(f"  Modo         : {mode}")
    log.info(f"  Duración     : {int(elapsed//60)}m {int(elapsed%60)}s")
    log.info(f"  {'Fuente':<18} {'Registros':>10}")
    log.info(f"  {'-'*30}")
    for src, count in stats.items():
        if src != "master_total":
            log.info(f"  {src:<18} {count:>10,}")
    log.info(f"  {'-'*30}")
    log.info(f"  {'TOTAL NUEVOS':<18} {report['total_new']:>10,}")   # FIX-3
    log.info(f"  {'MASTER TOTAL':<18} {master_total:>10,}")
    log.info("═" * 60)

    return report


# ══════════════════════════════════════════════════════════════════════════
# ARGPARSE
# ══════════════════════════════════════════════════════════════════════════

def _parse_args():
    parser = argparse.ArgumentParser(
        description="Pipeline de recolección de datos — tesis-hardware-peru v5.1",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        default="normal",
        choices=["normal", "local_only", "historical", "kaggle_only", "full"],
        help=(
            "Modo de ejecución:\n"
            "  normal      → local PE + eBay + importacion (default, ~25 min)\n"
            "  local_only  → solo Falabella/Ripley/Hiraoka (~17 min)\n"
            "  historical  → eBay + CamelCamelCamel + PCPartPicker (~39 min)\n"
            "  kaggle_only → solo descarga Kaggle (~30 min)\n"
            "  full        → todo (~86 min) ⚠️ supera timeout de 55 min del workflow"
        ),
    )
    parser.add_argument(
        "--batch-id",
        default=None,
        help="Batch ID manual (default: timestamp automático YYYYMMDD_HHMMSS)",
    )
    return parser.parse_args()


# ══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    args     = _parse_args()
    batch_id = args.batch_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    run(mode=args.mode, batch_id=batch_id)
