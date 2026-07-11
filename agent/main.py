#!/usr/bin/env python3
"""
main.py — Orquestador v5.5
════════════════════════════════════════════════════════════════════
Fixes v5.5 (sobre v5.4):
  - [O1] importlib de scrapers/__init__.py: try/except + sys.exit(1)
         Crashea ANTES de que logging esté activo → error solo en stderr
  - [O2] Carga dinámica MeLi/Newegg: error real en warning (era 'pass')
  - [O3] merge_to_master: dedup con md5 fingerprint para sku vacío
         'if not sku → agrega siempre' → duplicados acumulativos por run
  - [O4] save_report: 'new_added' real desde merge_to_master (era suma bruta)
  - [O5] run(): escritura atómica del MASTER (tmp → rename) — evita
         corrupción si GitHub Actions cancela a mitad del merge
  - [O6] FIELD_ORDER: campos MeLi actualizados (v1.0 → v2.0)
         sold_qty/seller_type → is_official_store/is_best_seller/etc.
  - [O7] __main__: datetime.now(timezone.utc)
"""

import sys
import os
import csv
import json
import hashlib
import logging
import argparse
import time
import importlib.util
from pathlib import Path
from datetime import datetime, timezone

# ── Paths ──────────────────────────────────────────────────────────────
AGENT_DIR = Path(__file__).resolve().parent
ROOT_DIR  = AGENT_DIR.parent
DATA_DIR  = ROOT_DIR / "data" / "raw"
LOG_DIR   = ROOT_DIR / "data" / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── FIX-8 + [O1]: Forzar carga de agent/scrapers/ con error explícito ──
_scrapers_path = AGENT_DIR / "scrapers" / "__init__.py"
_spec = importlib.util.spec_from_file_location(
    "scrapers",
    str(_scrapers_path),
    submodule_search_locations=[str(AGENT_DIR / "scrapers")],
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["scrapers"] = _mod
try:
    _spec.loader.exec_module(_mod)
except Exception as _e:
    # [O1] Logging aún no está activo → print a stderr + exit
    print(f"FATAL: scrapers/__init__.py falló al cargar: {_e}", file=sys.stderr)
    sys.exit(1)

if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

# ── [O2] Carga dinámica de MercadoLibre PE — error real en warning ──────
_meli_path        = AGENT_DIR / "scrapers" / "scraper_mercadolibre.py"
_HAS_MELI         = False
_meli_load_error  = None
scrape_mercadolibre = None

if _meli_path.exists():
    try:
        _meli_spec = importlib.util.spec_from_file_location(
            "scrapers.scraper_mercadolibre", str(_meli_path),
        )
        _meli_mod = importlib.util.module_from_spec(_meli_spec)
        sys.modules["scrapers.scraper_mercadolibre"] = _meli_mod
        _meli_spec.loader.exec_module(_meli_mod)
        scrape_mercadolibre = _meli_mod.scrape_mercadolibre
        _HAS_MELI = True
    except Exception as _e:
        _meli_load_error = str(_e)   # [O2] guardar para el warning

# ── [O2] Carga dinámica de Newegg USA — error real en warning ───────────
_newegg_path        = AGENT_DIR / "scrapers" / "scraper_newegg.py"
_HAS_NEWEGG         = False
_newegg_load_error  = None
scrape_newegg       = None

if _newegg_path.exists():
    try:
        _newegg_spec = importlib.util.spec_from_file_location(
            "scrapers.scraper_newegg", str(_newegg_path),
        )
        _newegg_mod = importlib.util.module_from_spec(_newegg_spec)
        sys.modules["scrapers.scraper_newegg"] = _newegg_mod
        _newegg_spec.loader.exec_module(_newegg_mod)
        scrape_newegg = _newegg_mod.scrape_newegg
        _HAS_NEWEGG = True
    except Exception as _e:
        _newegg_load_error = str(_e)   # [O2] guardar para el warning

# ── Logging ────────────────────────────────────────────────────────────
LOG_FILE = LOG_DIR / "agent.log"
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

# ── Status de carga de scrapers opcionales ─────────────────────────────
if not _HAS_MELI:
    # [O2] Mostrar el error real, no solo "no encontrado o con error"
    _meli_reason = f"error: {_meli_load_error}" if _meli_load_error else "archivo no encontrado"
    log.warning(f"[FIX-9] scraper_mercadolibre.py no disponible ({_meli_reason}) — paso MeLi PE omitido")
else:
    log.info("[FIX-9] scraper_mercadolibre.py cargado ✅")

if not _HAS_NEWEGG:
    _newegg_reason = f"error: {_newegg_load_error}" if _newegg_load_error else "archivo no encontrado"
    log.warning(f"[FIX-10] scraper_newegg.py no disponible ({_newegg_reason}) — paso Newegg USA omitido")
else:
    log.info("[FIX-10] scraper_newegg.py cargado ✅")

# ── Imports desde scrapers ─────────────────────────────────────────────
from scrapers import (
    scrape_local,
    scrape_dolar,
    scrape_ebay,
    scrape_camel,
    scrape_pcpartpicker,
    scrape_kaggle,
    scrape_importacion,
    scrape_competencia,
    _HAS_IMPORTACION,
    _HAS_COMPETENCIA,
)

# ── [O6] FIELD_ORDER — campos MeLi actualizados a v2.0 ─────────────────
FIELD_ORDER = [
    "batch_id", "timestamp", "source", "category",
    "sku", "brand", "title",
    "price_pen", "price_orig_pen", "price_usd", "price_orig_usd", "price_date",
    "discount_pct", "price_currency",
    "rating", "reviews",
    # Campos MeLi v2.0 (vacíos en otras fuentes — no rompen nada)
    "condition", "available_qty", "free_shipping",
    "is_official_store", "is_best_seller", "is_good_seller", "seller_nickname",
    # Campos comunes
    "retailer", "part_id", "url",
]


# ══════════════════════════════════════════════════════════════════════
# GUARDAR REGISTROS EN CSV
# ══════════════════════════════════════════════════════════════════════

def save_batch(records: list, batch_id: str, source_tag: str) -> Path:
    if not records:
        log.warning(f"  [save] Sin registros para {source_tag}")
        return None

    out_path   = DATA_DIR / f"batch_{batch_id}_{source_tag}.csv"
    all_keys   = set(k for r in records for k in r.keys())
    ordered    = [f for f in FIELD_ORDER if f in all_keys]
    remainder  = sorted(all_keys - set(ordered))
    fieldnames = ordered + remainder

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    log.info(f"  💾 Guardado: {out_path.name} ({len(records):,} registros)")
    return out_path


# ══════════════════════════════════════════════════════════════════════
# MERGE AL MASTER
# ══════════════════════════════════════════════════════════════════════

def _make_dedup_key(row: dict) -> tuple:
    """
    [O3] Clave de deduplicación robusta para items con y sin SKU.
    Sin SKU → fingerprint md5(title[:80]|price) — determinístico entre runs.
    """
    source     = row.get("source", "")
    sku        = row.get("sku", "").strip()
    price_date = row.get("price_date", "")

    if not sku:
        title = row.get("title", row.get("name", ""))[:80]
        price = str(row.get("price_pen") or row.get("price_usd") or "")
        fp    = hashlib.md5(f"{title}|{price}".encode()).hexdigest()[:12]
        return (source, f"fp_{fp}", price_date)

    return (source, sku, price_date)


def merge_to_master(batch_files: list) -> tuple[int, int]:
    """
    Retorna (total_records, added_records).
    [O5] Escritura atómica: tmp → rename — evita corrupción por cancelación.
    """
    master_path = DATA_DIR / "MASTER_hardware_peru.csv"
    new_records = []
    all_fields  = set(FIELD_ORDER)

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
        return 0, 0

    existing_records = []
    existing_keys    = set()

    if master_path.exists():
        try:
            with open(master_path, encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    existing_records.append(row)
                    all_fields.update(row.keys())
                    existing_keys.add(_make_dedup_key(row))
        except Exception as e:
            log.warning(f"  Error leyendo MASTER: {e}")

    added   = 0
    skipped = 0
    for row in new_records:
        key = _make_dedup_key(row)
        if key not in existing_keys:
            existing_records.append(row)
            existing_keys.add(key)
            added += 1
        else:
            skipped += 1

    if skipped:
        log.info(f"  [master] Deduplicados: {skipped:,} registros omitidos")

    ordered    = [f for f in FIELD_ORDER if f in all_fields]
    remainder  = sorted(all_fields - set(ordered))
    fieldnames = ordered + remainder

    # [O5] Escritura atómica: escribir en .tmp → renombrar
    tmp_path = master_path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(existing_records)
        tmp_path.replace(master_path)   # atómico en mismo filesystem
    except Exception as e:
        log.error(f"  [master] Error escribiendo MASTER: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    total = len(existing_records)
    log.info(f"  📊 MASTER actualizado: {total:,} registros totales (+{added:,} nuevos)")
    return total, added


# ══════════════════════════════════════════════════════════════════════
# REPORTE JSON
# ══════════════════════════════════════════════════════════════════════

def save_report(batch_id: str, stats: dict, elapsed: float, new_added: int):
    """[O4] new_added = registros realmente añadidos al MASTER (no suma bruta)."""
    report = {
        "batch_id":     batch_id,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "elapsed_s":    round(elapsed, 1),
        "stats":        stats,
        "new_added":    new_added,          # [O4] real, no suma bruta
        "master_total": stats.get("master_total", 0),
    }
    report_path = DATA_DIR / f"report_{batch_id}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    log.info(f"  📋 Reporte: {report_path.name}")
    return report


# ══════════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ══════════════════════════════════════════════════════════════════════

def run(mode: str, batch_id: str):
    start   = time.time()
    stats   = {}
    batches = []

    log.info("═" * 60)
    log.info(f"  PIPELINE v5.5 — modo={mode} | batch={batch_id}")
    log.info("═" * 60)

    # ── 1. Tipo de cambio (siempre) ────────────────────────────────
    log.info("\n[1/10] 💱 Tipo de cambio USD/PEN")
    try:
        dolar_records = scrape_dolar(batch_id)
        p = save_batch(dolar_records, batch_id, "dolar")
        batches.append(p)
        stats["dolar"] = len(dolar_records)
        log.info(f"  ✅ Dolar: {len(dolar_records)} registros")
    except Exception as e:
        log.error(f"  ❌ Dolar: {e}")
        stats["dolar"] = 0

    # ── 2. Scrapers locales PE ─────────────────────────────────────
    if mode in ("normal", "local_only", "full"):
        log.info("\n[2/10] 🇵🇪 Tiendas locales PE (Falabella + Hiraoka)")
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

    # ── 3. MercadoLibre PE ─────────────────────────────────────────
    if _HAS_MELI and mode in ("normal", "local_only", "full"):
        log.info("\n[3/10] 🛍️ MercadoLibre PE")
        try:
            meli_records = scrape_mercadolibre(batch_id)
            p = save_batch(meli_records, batch_id, "mercadolibre")
            batches.append(p)
            stats["mercadolibre_pe"] = len(meli_records)
            log.info(f"  ✅ MeLi PE: {len(meli_records):,} registros")
        except Exception as e:
            log.error(f"  ❌ MeLi PE: {e}")
            stats["mercadolibre_pe"] = 0
    else:
        if not _HAS_MELI:
            log.warning("  ⚠️  [3/10] MeLi PE omitido — scraper no disponible")
        stats["mercadolibre_pe"] = 0

    # ── 4. Newegg USA ──────────────────────────────────────────────
    if _HAS_NEWEGG and mode in ("normal", "historical", "full"):
        log.info("\n[4/10] 🖥️ Newegg USA (precios USD)")
        try:
            newegg_records = scrape_newegg(batch_id)
            p = save_batch(newegg_records, batch_id, "newegg")
            batches.append(p)
            stats["newegg_usa"] = len(newegg_records)
            log.info(f"  ✅ Newegg USA: {len(newegg_records):,} registros")
        except Exception as e:
            log.error(f"  ❌ Newegg USA: {e}")
            stats["newegg_usa"] = 0
    else:
        if not _HAS_NEWEGG:
            log.warning("  ⚠️  [4/10] Newegg USA omitido — scraper no disponible")
        stats["newegg_usa"] = 0

    # ── 5. eBay ────────────────────────────────────────────────────
    if mode in ("normal", "historical", "full"):
        log.info("\n[5/10] 🛒 eBay USA")
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

    # ── 6. CamelCamelCamel ─────────────────────────────────────────
    if mode in ("historical", "full"):
        log.info("\n[6/10] 🐪 CamelCamelCamel")
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

    # ── 7. PCPartPicker ────────────────────────────────────────────
    if mode in ("historical", "full"):
        log.info("\n[7/10] 🖥️ PCPartPicker")
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

    # ── 8. Kaggle ──────────────────────────────────────────────────
    if mode in ("kaggle_only", "full"):
        log.info("\n[8/10] 📦 Kaggle datasets")
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

    # ── 9. Importación ─────────────────────────────────────────────
    if _HAS_IMPORTACION and mode in ("normal", "historical", "full"):
        log.info("\n[9/10] 📦 Precios de importación")
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

    # ── 10. Competencia ────────────────────────────────────────────
    if _HAS_COMPETENCIA and mode in ("normal", "local_only", "full"):
        log.info("\n[10/10] 🔍 Competencia local PE")
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

    # ── Merge al MASTER ────────────────────────────────────────────
    log.info("\n[MERGE] Actualizando MASTER_hardware_peru.csv...")
    # [O4] merge_to_master retorna (total, added)
    master_total, new_added = merge_to_master([b for b in batches if b])
    stats["master_total"] = master_total

    # ── Reporte ────────────────────────────────────────────────────
    elapsed = time.time() - start
    # [O4] Pasar new_added real al reporte
    report  = save_report(batch_id, stats, elapsed, new_added)

    # ── Resumen final ──────────────────────────────────────────────
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
    log.info(f"  {'NUEVOS REALES':<18} {new_added:>10,}")   # [O4]
    log.info(f"  {'MASTER TOTAL':<18} {master_total:>10,}")
    log.info("═" * 60)

    return report


# ══════════════════════════════════════════════════════════════════════
# ARGPARSE
# ══════════════════════════════════════════════════════════════════════

def _parse_args():
    parser = argparse.ArgumentParser(
        description="Pipeline de recolección — tesis-hardware-peru v5.5",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        default="normal",
        choices=["normal", "local_only", "historical", "kaggle_only", "full"],
        help=(
            "Modo de ejecución:\n"
            "  normal      → local PE + MeLi PE + Newegg + eBay + importacion (~45 min)\n"
            "  local_only  → Falabella/Hiraoka + MeLi PE (~22 min)\n"
            "  historical  → Newegg + eBay + CamelCamelCamel + PCPartPicker (~50 min)\n"
            "  kaggle_only → solo descarga Kaggle (~30 min)\n"
            "  full        → todo (~110 min) ⚠️ supera timeout de 55 min"
        ),
    )
    parser.add_argument(
        "--batch-id",
        default=None,
        help="Batch ID manual (default: timestamp automático)",
    )
    return parser.parse_args()


# ══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    args     = _parse_args()
    # [O7] datetime con timezone explícita
    batch_id = args.batch_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run(mode=args.mode, batch_id=batch_id)
