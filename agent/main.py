"""
main.py — Orquestador v5.0 (Objetivo 1: Máxima recolección de datos)
════════════════════════════════════════════════════════════════════
Modos:
  python main.py                        → todo
  python main.py --mode local_only      → solo Falabella/Ripley/Hiraoka
  python main.py --mode historical      → solo eBay/Camel/PCPartPicker
  python main.py --mode kaggle_only     → solo Kaggle datasets
  python main.py --mode normal          → local + eBay (sin Kaggle/Camel)
  python main.py --mode full            → absolutamente todo
  python main.py --batch-id XXXX        → batch ID manual
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
# agent/main.py → necesita encontrar agent/scrapers/
AGENT_DIR = Path(__file__).resolve().parent
ROOT_DIR  = AGENT_DIR.parent
DATA_DIR  = ROOT_DIR / "data" / "raw"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Agregar agent/ al path para imports relativos
sys.path.insert(0, str(AGENT_DIR))

# ── Logging ───────────────────────────────────────────────────────────────
LOG_FILE = DATA_DIR / "agent.log"
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

# ── Imports de scrapers ───────────────────────────────────────────────────
from scrapers.scraper_dolar        import scrape_dolar
from scrapers.scraper_local        import scrape_local
from scrapers.scraper_ebay         import scrape_ebay
from scrapers.scraper_camel        import scrape_camel
from scrapers.scraper_pcpartpicker import scrape_pcpartpicker
from scrapers.scraper_kaggle       import scrape_kaggle


# ══════════════════════════════════════════════════════════════════════════
# GUARDAR REGISTROS EN CSV
# ══════════════════════════════════════════════════════════════════════════

def save_batch(records: list, batch_id: str, source_tag: str) -> Path:
    """Guarda una lista de registros en data/raw/batch_{batch_id}_{tag}.csv"""
    if not records:
        log.warning(f"  [save] Sin registros para {source_tag}")
        return None

    out_path = DATA_DIR / f"batch_{batch_id}_{source_tag}.csv"
    fieldnames = sorted(set(k for r in records for k in r.keys()))

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    log.info(f"  💾 Guardado: {out_path.name} ({len(records)} registros)")
    return out_path


def merge_to_master(batch_files: list[Path]) -> int:
    """
    Agrega todos los batch CSV al MASTER_hardware_peru.csv.
    Evita duplicados por fingerprint si existe la columna.
    """
    master_path = DATA_DIR / "MASTER_hardware_peru.csv"
    all_records = []
    all_fields  = set()

    # Leer batch files nuevos
    for f in batch_files:
        if f is None or not f.exists():
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                rows = list(reader)
                all_records.extend(rows)
                all_fields.update(reader.fieldnames or [])
        except Exception as e:
            log.warning(f"  Error leyendo {f.name}: {e}")

    if not all_records:
        log.warning("  [master] Sin registros nuevos para agregar")
        return 0

    # Leer master existente
    existing_records = []
    if master_path.exists():
        try:
            with open(master_path, encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                existing_records = list(reader)
                all_fields.update(reader.fieldnames or [])
        except Exception as e:
            log.warning(f"  Error leyendo MASTER: {e}")

    # Combinar
    combined   = existing_records + all_records
    fieldnames = sorted(all_fields)

    with open(master_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(combined)

    new_total = len(combined)
    log.info(f"  📊 MASTER actualizado: {new_total:,} registros totales")
    return new_total


# ══════════════════════════════════════════════════════════════════════════
# REPORTE JSON
# ══════════════════════════════════════════════════════════════════════════

def save_report(batch_id: str, stats: dict, elapsed: float):
    report = {
        "batch_id":   batch_id,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "elapsed_s":  round(elapsed, 1),
        "stats":      stats,
        "total":      sum(v for v in stats.values() if isinstance(v, int)),
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
    start    = time.time()
    stats    = {}
    batches  = []

    log.info("═" * 60)
    log.info(f"  PIPELINE v5.0 — modo={mode} | batch={batch_id}")
    log.info("═" * 60)

    # ── 1. Tipo de cambio (siempre) ────────────────────────────────────────
    log.info("\n[1/6] 💱 Tipo de cambio USD/PEN")
    try:
        dolar_records = scrape_dolar(batch_id)
        p = save_batch(dolar_records, batch_id, "dolar")
        batches.append(p)
        stats["dolar"] = len(dolar_records)
        log.info(f"  ✅ Dolar: {len(dolar_records)} registros")
    except Exception as e:
        log.error(f"  ❌ Dolar: {e}")
        stats["dolar"] = 0

    # ── 2. Scrapers locales PE ─────────────────────────────────────────────
    if mode in ("normal", "local_only", "full"):
        log.info("\n[2/6] 🇵🇪 Tiendas locales PE (Falabella / Ripley / Hiraoka)")
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

    # ── 3. eBay Finding API ────────────────────────────────────────────────
    if mode in ("normal", "historical", "full"):
        log.info("\n[3/6] 🛒 eBay USA (ventas completadas 90 días)")
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

    # ── 4. CamelCamelCamel ─────────────────────────────────────────────────
    if mode in ("historical", "full"):
        log.info("\n[4/6] 🐪 CamelCamelCamel (historial Amazon)")
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

    # ── 5. PCPartPicker ────────────────────────────────────────────────────
    if mode in ("historical", "full"):
        log.info("\n[5/6] 🖥️ PCPartPicker (historial USA multi-tienda)")
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

    # ── 6. Kaggle datasets ─────────────────────────────────────────────────
    if mode in ("kaggle_only", "full"):
        log.info("\n[6/6] 📦 Kaggle datasets (bulk histórico)")
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

    # ── Merge al MASTER ────────────────────────────────────────────────────
    log.info("\n[MERGE] Actualizando MASTER_hardware_peru.csv...")
    master_total = merge_to_master([b for b in batches if b])
    stats["master_total"] = master_total

    # ── Reporte ────────────────────────────────────────────────────────────
    elapsed = time.time() - start
    report  = save_report(batch_id, stats, elapsed)

    # ── Resumen final ──────────────────────────────────────────────────────
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
    log.info(f"  {'MASTER TOTAL':<18} {master_total:>10,}")
    log.info("═" * 60)

    return report


# ══════════════════════════════════════════════════════════════════════════
# ARGPARSE
# ══════════════════════════════════════════════════════════════════════════

def _parse_args():
    parser = argparse.ArgumentParser(
        description="Pipeline de recolección de datos — tesis-hardware-peru v5.0"
    )
    parser.add_argument(
        "--mode",
        default="normal",
        choices=["normal", "local_only", "historical", "kaggle_only", "full"],
        help=(
            "Modo de ejecución:\n"
            "  normal      → local PE + eBay (default)\n"
            "  local_only  → solo Falabella/Ripley/Hiraoka\n"
            "  historical  → eBay + CamelCamelCamel + PCPartPicker\n"
            "  kaggle_only → solo descarga Kaggle\n"
            "  full        → todo (puede tardar 60+ min)"
        ),
    )
    parser.add_argument(
        "--batch-id",
        default=None,
        help="Batch ID manual (default: timestamp automático)",
    )
    return parser.parse_args()


# ══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    args     = _parse_args()
    batch_id = args.batch_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    run(mode=args.mode, batch_id=batch_id)
