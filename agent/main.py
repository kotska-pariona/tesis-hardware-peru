#!/usr/bin/env python3
"""
main.py — Orquestador v5.8
════════════════════════════════════════════════════════════════════
Fixes v5.8 (sobre v5.7):
  [O21] BUG CRÍTICO: en TODOS los pasos que usan _near_timeout(),
        si mode-condición=True PERO near_timeout=True, stats[key]
        NUNCA se asignaba (ni 0 ni conteo real) — la clave quedaba
        ausente del dict `stats` y por ende del report JSON.
        Esto rompe cualquier consumidor downstream (roi_calculator,
        dashboards) que acceda a report["stats"][fuente] esperando
        que la clave siempre exista. Fix: se invirtió la condición
        (if _near_timeout(): stats[key]=0 else: try/except) para
        que la clave SIEMPRE se asigne, y se agregó un log explícito
        "⏭️ omitido por timeout" por fuente (antes solo había un
        warning global genérico, sin indicar qué fuente se saltó).

Fixes v5.7 (sobre v5.6):
  [O16] scrape_pcpartpicker cargado dinámicamente igual que MeLi/Newegg
        — era import directo desde scrapers/__init__.py; si falla, el
        pipeline entero muere. Ahora es opcional con _HAS_PCP flag.
  [O17] Todos los scrapers llamados con mode= explícito — en v5.6 solo
        scrape_local/scrape_dolar lo recibían; el resto ignoraba el parámetro
  [O18] scrape_kaggle / scrape_camel / scrape_pcpartpicker agregados a
        _HAS_* guards — si el módulo no carga, el paso se omite con warning
        en lugar de KeyError en import
  [O19] _near_timeout(): log solo una vez por invocación — en v5.6 podía
        loguear el warning en cada paso si el pipeline ya estaba cerca del límite
  [O20] mode='local_only' incluye MeLi PE — en v5.6 estaba incluido pero
        faltaba en el help string; ahora ambos son consistentes
"""

import sys
import os
import csv
import json
import hashlib
import logging
import logging.handlers
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

# ── [O13] Guardia de timeout ───────────────────────────────────────────
MAX_ELAPSED_S = int(os.getenv("MAX_ELAPSED_S", "3000"))  # 50 min default

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
    print(
        f"FATAL: scrapers/__init__.py falló al cargar: {_e}",
        file=sys.stderr,
    )
    sys.exit(1)

if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ── Helper de carga dinámica de scrapers opcionales ────────────────────
def _load_optional_scraper(
    name: str, filename: str
) -> tuple[bool, object, str | None]:
    """
    Carga dinámica de un scraper opcional desde agent/scrapers/.
    Retorna (has_scraper, fn_or_None, error_or_None).
    """
    path = AGENT_DIR / "scrapers" / filename
    if not path.exists():
        return False, None, "archivo no encontrado"
    try:
        mod_name = f"scrapers.{filename[:-3]}"
        spec     = importlib.util.spec_from_file_location(
            mod_name, str(path)
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        fn = getattr(mod, name)
        return True, fn, None
    except Exception as e:
        return False, None, str(e)


# ── Carga de scrapers opcionales ───────────────────────────────────────
_HAS_MELI,   scrape_mercadolibre, _meli_err   = _load_optional_scraper(
    "scrape_mercadolibre", "scraper_mercadolibre.py"
)
_HAS_NEWEGG, scrape_newegg,       _newegg_err = _load_optional_scraper(
    "scrape_newegg",       "scraper_newegg.py"
)
# [O16] PCPartPicker ahora también es opcional — igual que MeLi/Newegg
_HAS_PCP,    scrape_pcpartpicker, _pcp_err    = _load_optional_scraper(
    "scrape_pcpartpicker", "scraper_pcpartpicker.py"
)
# [O18] Camel y Kaggle con guards — si __init__.py no los expone, no muere
_HAS_CAMEL,  scrape_camel,        _camel_err  = _load_optional_scraper(
    "scrape_camel",        "scraper_camel.py"
)
_HAS_KAGGLE, scrape_kaggle,       _kaggle_err = _load_optional_scraper(
    "scrape_kaggle",       "scraper_kaggle.py"
)

# ── Logging con rotación [M6] ──────────────────────────────────────────
LOG_FILE = LOG_DIR / "agent.log"
_file_handler = logging.handlers.RotatingFileHandler(
    str(LOG_FILE),
    maxBytes=5 * 1024 * 1024,   # 5 MB por archivo
    backupCount=7,               # 7 archivos → máx 35 MB histórico
    encoding="utf-8",
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        _file_handler,
    ],
)
log = logging.getLogger("main")

# ── Status de carga de scrapers opcionales ─────────────────────────────
_OPTIONAL_SCRAPERS = {
    "MeLi PE     [FIX-9] ": (_HAS_MELI,   _meli_err),
    "Newegg USA  [FIX-10]": (_HAS_NEWEGG, _newegg_err),
    "PCPartPicker [O16]  ": (_HAS_PCP,    _pcp_err),
    "Camel        [O18]  ": (_HAS_CAMEL,  _camel_err),
    "Kaggle       [O18]  ": (_HAS_KAGGLE, _kaggle_err),
}
for label, (ok, err) in _OPTIONAL_SCRAPERS.items():
    if ok:
        log.info(f"  ✅ {label} cargado")
    else:
        reason = f"error: {err}" if err else "archivo no encontrado"
        log.warning(f"  ⚠️  {label} no disponible ({reason}) — paso omitido")

# ── Imports CORE desde scrapers/__init__.py ────────────────────────────
from scrapers import (
    scrape_local,
    scrape_dolar,
    scrape_ebay,
    scrape_importacion,
    scrape_competencia,
    _HAS_IMPORTACION,
    _HAS_COMPETENCIA,
)

# ── [O12] FIELD_ORDER — eBay v4.0 + MeLi v2.0 ─────────────────────────
FIELD_ORDER = [
    "batch_id", "timestamp", "source", "category",
    "sku", "brand", "title",
    "price_pen", "price_orig_pen", "price_usd", "price_orig_usd",
    "price_date", "discount_pct", "price_currency",
    "rating", "reviews",
    # Campos MeLi v2.0
    "condition", "available_qty", "free_shipping",
    "is_official_store", "is_best_seller", "is_good_seller",
    "seller_nickname",
    # Campos eBay v4.0 [O12] — seller_feedback renombrado
    "seller_feedback_score", "seller_feedback_pct",
    # Campos comunes
    "retailer", "part_id", "url",
]


# ══════════════════════════════════════════════════════════════════════
# GUARDAR REGISTROS EN CSV
# ══════════════════════════════════════════════════════════════════════

def save_batch(
    records: list, batch_id: str, source_tag: str
) -> Path | None:
    """
    [O10] IOError se propaga — no retorna None silencioso en caso de error.
    Retorna None SOLO cuando records está vacío (sin datos, no error).
    """
    if not records:
        log.warning(f"  [save] Sin registros para {source_tag}")
        return None

    out_path   = DATA_DIR / f"batch_{batch_id}_{source_tag}.csv"
    all_keys   = set(k for r in records for k in r.keys())
    ordered    = [f for f in FIELD_ORDER if f in all_keys]
    remainder  = sorted(all_keys - set(ordered))
    fieldnames = ordered + remainder

    # [O10] No capturar IOError — que se propague al caller
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=fieldnames, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(records)

    log.info(
        f"  💾 Guardado: {out_path.name} ({len(records):,} registros)"
    )
    return out_path


# ══════════════════════════════════════════════════════════════════════
# MERGE AL MASTER
# ══════════════════════════════════════════════════════════════════════

def _make_dedup_key(row: dict) -> tuple:
    """
    [O11] price_date removido de la clave — evita duplicados acumulativos.
    Clave: (source, sku) para items con SKU.
    Clave: (source, fp_<md5>) para items sin SKU — determinístico.
    """
    source = row.get("source", "")
    sku    = (row.get("sku") or "").strip()

    if not sku:
        title = (row.get("title") or row.get("name") or "")[:80]
        price = str(row.get("price_pen") or row.get("price_usd") or "")
        fp    = hashlib.md5(f"{title}|{price}".encode()).hexdigest()[:12]
        return (source, f"fp_{fp}")

    return (source, sku)


def merge_to_master(batch_files: list) -> tuple[int, int]:
    """
    Retorna (total_records, added_records).
    [O5] Escritura atómica: tmp → rename.
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
        log.info(
            f"  [master] Deduplicados: {skipped:,} registros omitidos"
        )

    ordered    = [f for f in FIELD_ORDER if f in all_fields]
    remainder  = sorted(all_fields - set(ordered))
    fieldnames = ordered + remainder

    # [O5] Escritura atómica
    tmp_path = master_path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=fieldnames, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(existing_records)
        tmp_path.replace(master_path)
    except Exception as e:
        log.error(f"  [master] Error escribiendo MASTER: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    total = len(existing_records)
    log.info(
        f"  📊 MASTER actualizado: {total:,} registros totales "
        f"(+{added:,} nuevos)"
    )
    return total, added


# ══════════════════════════════════════════════════════════════════════
# REPORTE JSON
# ══════════════════════════════════════════════════════════════════════

def save_report(
    batch_id: str, stats: dict, elapsed: float, new_added: int
):
    report = {
        "batch_id":     batch_id,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "elapsed_s":    round(elapsed, 1),
        "stats":        stats,
        "new_added":    new_added,
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

    # [O14] Contador de pasos dinámico
    _step_n = [0]
    def _step(label: str) -> str:
        _step_n[0] += 1
        return f"\n[{_step_n[0]}] {label}"

    # [O19] _near_timeout(): log solo UNA vez — flag para evitar spam
    _timeout_warned = [False]
    def _near_timeout() -> bool:
        elapsed = time.time() - start
        if elapsed > MAX_ELAPSED_S - 120:
            if not _timeout_warned[0]:
                log.warning(
                    f"  ⏱ Timeout próximo ({elapsed:.0f}s / "
                    f"{MAX_ELAPSED_S}s) — saltando pasos restantes "
                    f"para merge seguro"
                )
                _timeout_warned[0] = True
            return True
        return False

    log.info("═" * 60)
    log.info(f"  PIPELINE v5.8 — modo={mode} | batch={batch_id}")
    log.info(
        f"  MAX_ELAPSED_S={MAX_ELAPSED_S}s ({MAX_ELAPSED_S//60} min)"
    )
    log.info("═" * 60)

    # ── 1. Tipo de cambio (siempre) ──────────────────────────────
    log.info(_step("💱 Tipo de cambio USD/PEN"))
    try:
        dolar_records = scrape_dolar(batch_id, mode=mode)   # [O17]
        p = save_batch(dolar_records, batch_id, "dolar")
        if p: batches.append(p)                              # [O15]
        stats["dolar"] = len(dolar_records)
        log.info(f"  ✅ Dolar: {len(dolar_records)} registros")
    except Exception as e:
        log.error(f"  ❌ Dolar: {e}")
        stats["dolar"] = 0

    # ── 2. Scrapers locales PE ───────────────────────────────────
    if mode in ("normal", "local_only", "full"):
        log.info(_step("🇵🇪 Tiendas locales PE (Falabella + Hiraoka)"))
        if _near_timeout():                                   # [O21]
            log.warning("  ⏭️  Local PE omitido — cerca del timeout")
            stats["local"] = 0
        else:
            try:
                local_records = scrape_local(batch_id, mode=mode)   # [O17]
                p = save_batch(local_records, batch_id, "local")
                if p: batches.append(p)
                stats["local"] = len(local_records)
                log.info(
                    f"
