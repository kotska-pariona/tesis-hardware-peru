#!/usr/bin/env python3
"""
main.py — Orquestador v5.11
════════════════════════════════════════════════════════════════════
Fixes v5.11 (sobre v5.10):
  [O30] convert_currency(): rate_mid ahora se castea a float()
        garantizado en run() antes de propagarse. Si scrape_dolar
        retorna "mid" como string (comportamiento real de CSV-parsed
        data), la división float(pen)/rate_mid ya no falla
        silenciosamente en el except (ValueError, TypeError) de
        convert_currency(). Fix de bug real — en producción el tipo
        de cambio se leía pero la conversión cruzada nunca ocurría
        si el scraper retornaba el valor como str.
  [O31] merge_to_master(): log de inicio ahora indica cuántos
        batch files entran al merge. Antes el mensaje era fijo
        "Actualizando MASTER_hardware_peru.csv..." sin contexto.
        Ahora: "Actualizando MASTER con N batch(es) válidos..."
        — mejora trazabilidad en runs parciales por timeout.
  [O32] _ALIAS_GROUPS: part_id removido de la lista de aliases
        de "sku". En v5.10, part_id estaba en
        _ALIAS_GROUPS["sku"] = ["sku","asin_sku","item_id","part_id"]
        lo que causaba que normalize_schema() copiara part_id→sku
        para cualquier scraper que emitiera part_id sin sku
        (PCPartPicker, Competencia, Ripley en desarrollo).
        part_id y sku son semánticamente distintos en varios
        scrapers — part_id es un descriptor de componente
        (ej: "B550M-DS3H"), no un identificador de listing.
        part_id sigue disponible como columna propia en FIELD_ORDER.
        Si un scraper específico necesita part_id→sku, debe
        hacerlo en su propio parser, no en normalize_schema().
  [O33] save_batch(): columnas nuevas de scrapers futuros ya no
        se pierden silenciosamente. Antes, extrasaction="ignore"
        en DictWriter descartaba cualquier campo no presente en
        fieldnames. Ahora fieldnames se construye como unión de
        FIELD_ORDER + remainder (todos los keys del batch actual),
        lo que ya cubría el caso — se agrega log.debug() explícito
        cuando remainder contiene campos no estándar, para
        auditar columnas nuevas de scrapers en integración
        (ej: Ripley PE en Prioridad 2.1).

Fixes v5.10 (sobre v5.9):
  [O28] merge_to_master(): mensaje de log "Deduplicados" corregido.
  [O29] normalize_schema(): source_tag usado en logging DEBUG.

Fixes v5.9 (sobre v5.8):
  [O23] normalize_schema(): consolida columnas alias.
  [O24] normalize_schema(): deriva price_date desde timestamp.
  [O25] convert_currency(): rellena price_usd/price_pen cruzado.
  [O26] scrape_dolar separado en MASTER_exchange_rate.csv.
  [O27] _make_dedup_key(): fallback sin sku usa url > title (sin price).

Fixes v5.8 (sobre v5.7):
  [O21] from __future__ import annotations.
  [O22] _make_dedup_key(): price_date restaurado en clave de dedup.

Fixes v5.7 (sobre v5.6):
  [O16] scrape_pcpartpicker cargado dinámicamente.
  [O17] Todos los scrapers llamados con mode= explícito.
  [O18] scrape_kaggle/scrape_camel/scrape_pcpartpicker con guards.
  [O19] _near_timeout(): log solo una vez por invocación.
  [O20] mode='local_only' incluye MeLi PE.
"""

from __future__ import annotations  # [O21] Compatibilidad Python <3.10

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
# [O16] PCPartPicker carga dinámica — igual que MeLi/Newegg
_HAS_PCP,    scrape_pcpartpicker, _pcp_err    = _load_optional_scraper(
    "scrape_pcpartpicker", "scraper_pcpartpicker.py"
)
# [O18] Camel y Kaggle con guards
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
    # Campos eBay v4.0 [O12]
    "seller_feedback_score", "seller_feedback_pct",
    # Campos comunes
    "retailer", "part_id", "url",
]

# ── [O23][O32] Grupos de columnas alias → canónica ─────────────────────
# [O32] part_id REMOVIDO de aliases de "sku" — son semánticamente
# distintos en PCPartPicker, Competencia y Ripley PE (en desarrollo).
# part_id sigue disponible como columna propia en FIELD_ORDER.
# Si un scraper específico necesita part_id→sku, debe hacerlo en
# su propio parser, no aquí.
_ALIAS_GROUPS = {
    "sku":            ["sku", "asin_sku", "item_id"],   # [O32] part_id removido
    "available_qty":  ["available_qty", "available"],
    "price_orig_pen": ["price_orig_pen", "original_price"],
    "free_shipping":  ["free_shipping", "shipping_free"],
    "price_currency": ["price_currency", "currency"],
}


# ══════════════════════════════════════════════════════════════════════
# [O23][O24][O29] NORMALIZACIÓN DE ESQUEMA
# ══════════════════════════════════════════════════════════════════════

def normalize_schema(records: list, source_tag: str) -> list:
    """
    [O23] Consolida columnas alias en su columna canónica del contrato.
    [O24] Deriva price_date desde timestamp cuando price_date está vacío.
    [O29] source_tag usado en logging DEBUG por fuente.
    [O32] part_id ya NO es alias de sku — ver _ALIAS_GROUPS.
    """
    for row in records:
        # [O23] Alias genéricos: primer valor no vacío gana
        for canon, aliases in _ALIAS_GROUPS.items():
            current = row.get(canon)
            if current is None or current == "":
                for alt in aliases:
                    val = row.get(alt)
                    if val is not None and val != "":
                        row[canon] = val
                        log.debug(
                            f"  [normalize:{source_tag}] "
                            f"{alt} -> {canon} = {val!r} "
                            f"(sku={row.get('sku', '?')})"
                        )
                        break

        # [O24] price_date derivado de timestamp
        pd_val = row.get("price_date")
        ts_val = row.get("timestamp")
        if (pd_val is None or pd_val == "") and ts_val:
            row["price_date"] = str(ts_val)[:10]

    return records


# ══════════════════════════════════════════════════════════════════════
# [O25][O30] CONVERSIÓN DE MONEDA CRUZADA
# ══════════════════════════════════════════════════════════════════════

def convert_currency(records: list, rate_mid: float | None) -> list:
    """
    [O25] Rellena price_usd/price_pen cruzado usando el 'mid' del tipo
    de cambio del batch actual. Nunca sobreescribe un valor ya presente.
    [O30] rate_mid ya llega garantizado como float desde run() —
    el cast se hace en el punto de lectura, no aquí, para que esta
    función sea agnóstica al tipo de origen del dato.
    """
    if not rate_mid:
        return records
    for row in records:
        usd = row.get("price_usd")
        pen = row.get("price_pen")
        try:
            if (usd is None or usd == "") and pen not in (None, ""):
                row["price_usd"] = round(float(pen) / rate_mid, 2)
            elif (pen is None or pen == "") and usd not in (None, ""):
                row["price_pen"] = round(float(usd) * rate_mid, 2)
        except (ValueError, TypeError):
            continue
    return records


# ══════════════════════════════════════════════════════════════════════
# GUARDAR REGISTROS EN CSV
# ══════════════════════════════════════════════════════════════════════

def save_batch(
    records: list,
    batch_id: str,
    source_tag: str,
    rate_mid: float | None = None,
) -> Path | None:
    """
    [O10] IOError se propaga — no retorna None silencioso en error.
    Retorna None SOLO cuando records está vacío.
    [O23][O25] normalize_schema() y convert_currency() aplicados aquí.
    [O33] log.debug() cuando remainder contiene campos no estándar —
    audita columnas nuevas de scrapers en integración (ej: Ripley PE).
    """
    if not records:
        log.warning(f"  [save] Sin registros para {source_tag}")
        return None

    records = normalize_schema(records, source_tag)
    if rate_mid:
        records = convert_currency(records, rate_mid)

    out_path   = DATA_DIR / f"batch_{batch_id}_{source_tag}.csv"
    all_keys   = set(k for r in records for k in r.keys())
    ordered    = [f for f in FIELD_ORDER if f in all_keys]
    remainder  = sorted(all_keys - set(ordered))

    # ── [O33] AÑADIDO v5.11 ───────────────────────────────────────────
    if remainder:
        log.debug(
            f"  [save:{source_tag}] Columnas no estándar detectadas "
            f"(se incluirán al final): {remainder}"
        )
    # ── FIN [O33] ─────────────────────────────────────────────────────

    fieldnames = ordered + remainder

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
# [O26] TIPO DE CAMBIO — ARCHIVO SEPARADO DEL MASTER DE PRODUCTOS
# ══════════════════════════════════════════════════════════════════════

def save_dolar_batch(records: list, batch_id: str) -> Path | None:
    """
    [O26] Guarda el tipo de cambio en MASTER_exchange_rate.csv,
    separado de MASTER_hardware_peru.csv. Dedup por (source, date).
    """
    if not records:
        log.warning("  [save] Sin registros de tipo de cambio")
        return None

    for r in records:
        if not r.get("date") and r.get("timestamp"):
            r["date"] = str(r["timestamp"])[:10]

    exch_path = DATA_DIR / "MASTER_exchange_rate.csv"
    existing: list = []
    seen: set = set()

    if exch_path.exists():
        try:
            with open(exch_path, encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    existing.append(row)
                    seen.add((row.get("source", ""), row.get("date", "")))
        except Exception as e:
            log.warning(f"  Error leyendo MASTER_exchange_rate: {e}")

    added = 0
    for r in records:
        key = (r.get("source", ""), r.get("date", ""))
        if key not in seen:
            existing.append(r)
            seen.add(key)
            added += 1

    if not existing:
        return None

    all_fields = set()
    for r in existing:
        all_fields.update(r.keys())
    fieldnames = sorted(all_fields)

    tmp_path = exch_path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=fieldnames, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(existing)
        tmp_path.replace(exch_path)
    except Exception as e:
        log.error(f"  [exchange] Error escribiendo MASTER_exchange_rate: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    log.info(
        f"  💾 MASTER_exchange_rate.csv: +{added:,} nuevos "
        f"({len(existing):,} total)"
    )
    return exch_path


# ══════════════════════════════════════════════════════════════════════
# MERGE AL MASTER
# ══════════════════════════════════════════════════════════════════════

def _make_dedup_key(row: dict) -> tuple:
    """
    [O22] price_date en la clave de dedup — 1 registro por SKU por día.
    [O27] Fallback sin sku: sku > url > title (SIN price).
    """
    source     = row.get("source", "") or ""
    sku        = (row.get("sku") or "").strip()
    price_date = (row.get("price_date") or "").strip()

    if sku:
        return (source, sku, price_date)

    url   = (row.get("url") or "").strip()
    title = (row.get("title") or row.get("name") or "")[:120].strip().lower()
    identity_source = url if url else title
    fp = hashlib.md5(identity_source.encode()).hexdigest()[:12]
    return (source, f"fp_{fp}", price_date)


def merge_to_master(batch_files: list) -> tuple[int, int]:
    """
    Retorna (total_records, added_records).
    [O5]  Escritura atómica: tmp → rename.
    [O26] batch_files ya NO incluye el batch de dólar.
    [O31] Log de inicio indica cuántos batch files entran al merge.
    """
    master_path = DATA_DIR / "MASTER_hardware_peru.csv"
    new_records = []
    all_fields  = set(FIELD_ORDER)

    # ── [O31] AÑADIDO v5.11 ───────────────────────────────────────────
    valid_files = [f for f in batch_files if f is not None and f.exists()]
    log.info(
        f"\n[MERGE] Actualizando MASTER con "
        f"{len(valid_files)} batch(es) válidos "
        f"(de {len(batch_files)} generados)..."
    )
    # ── FIN [O31] ─────────────────────────────────────────────────────

    for f in valid_files:
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
        # [O28] Mensaje genérico — no asume sku
        log.info(
            f"  [master] Deduplicados: {skipped:,} registros omitidos "
            f"(mismo source+identidad+price_date; identidad = sku, "
            f"o fingerprint url/title si no hay sku — ver [O27])"
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

    # [O19] _near_timeout(): log solo UNA vez
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
    log.info(f"  PIPELINE v5.11 — modo={mode} | batch={batch_id}")
    log.info(
        f"  MAX_ELAPSED_S={MAX_ELAPSED_S}s ({MAX_ELAPSED_S//60} min)"
    )
    log.info("═" * 60)

    # ── 1. Tipo de cambio (siempre) ──────────────────────────────────
    log.info(_step("💱 Tipo de cambio USD/PEN"))
    rate_mid = None
    try:
        dolar_records = scrape_dolar(batch_id, mode=mode)
        # ── [O30] AÑADIDO v5.11 — cast a float garantizado ──────────
        _raw_mid = dolar_records[0].get("mid") if dolar_records else None
        try:
            rate_mid = float(_raw_mid) if _raw_mid not in (None, "") else None
        except (ValueError, TypeError):
            log.warning(
                f"  ⚠️  rate_mid inválido ({_raw_mid!r}) — "
                f"conversión cruzada deshabilitada para este batch"
            )
            rate_mid = None
        # ── FIN [O30] ────────────────────────────────────────────────
        save_dolar_batch(dolar_records, batch_id)
        stats["dolar"] = len(dolar_records)
        log.info(
            f"  ✅ Dolar: {len(dolar_records)} registros "
            f"(rate_mid={rate_mid})"
        )
    except Exception as e:
        log.error(f"  ❌ Dolar: {e}")
        stats["dolar"] = 0

    # ── 2. Scrapers locales PE ───────────────────────────────────────
    if mode in ("normal", "local_only", "full"):
        log.info(_step("🇵🇪 Tiendas locales PE (Falabella + Hiraoka)"))
        if not _near_timeout():
            try:
                local_records = scrape_local(batch_id, mode=mode)
                p = save_batch(
                    local_records, batch_id, "local", rate_mid=rate_mid
                )
                if p: batches.append(p)
                stats["local"] = len(local_records)
                log.info(
                    f"  ✅ Local PE: {len(local_records):,} registros"
                )
            except Exception as e:
                log.error(f"  ❌ Local PE: {e}")
                stats["local"] = 0
    else:
        stats["local"] = 0

    # ── 3. MercadoLibre PE ───────────────────────────────────────────
    if _HAS_MELI and mode in ("normal", "local_only", "full"):
        log.info(_step("🛍️ MercadoLibre PE"))
        if not _near_timeout():
            try:
                meli_records = scrape_mercadolibre(batch_id, mode=mode)
                p = save_batch(
                    meli_records, batch_id, "mercadolibre",
                    rate_mid=rate_mid
                )
                if p: batches.append(p)
                stats["mercadolibre_pe"] = len(meli_records)
                log.info(
                    f"  ✅ MeLi PE: {len(meli_records):,} registros"
                )
            except Exception as e:
                log.error(f"  ❌ MeLi PE: {e}")
                stats["mercadolibre_pe"] = 0
    else:
        if not _HAS_MELI:
            log.warning("  ⚠️  MeLi PE omitido — scraper no disponible")
        stats["mercadolibre_pe"] = 0

    # ── 4. Newegg USA ────────────────────────────────────────────────
    if _HAS_NEWEGG and mode in ("normal", "historical", "full"):
        log.info(_step("🖥️ Newegg USA (precios USD)"))
        if not _near_timeout():
            try:
                newegg_records = scrape_newegg(batch_id, mode=mode)
                p = save_batch(
                    newegg_records, batch_id, "newegg", rate_mid=rate_mid
                )
                if p: batches.append(p)
                stats["newegg_usa"] = len(newegg_records)
                log.info(
                    f"  ✅ Newegg USA: {len(newegg_records):,} registros"
                )
            except Exception as e:
                log.error(f"  ❌ Newegg USA: {e}")
                stats["newegg_usa"] = 0
    else:
        if not _HAS_NEWEGG:
            log.warning(
                "  ⚠️  Newegg USA omitido — scraper no disponible"
            )
        stats["newegg_usa"] = 0

    # ── 5. eBay ──────────────────────────────────────────────────────
    if mode in ("normal", "historical", "full"):
        log.info(_step("🛒 eBay USA"))
        if not _near_timeout():
            try:
                ebay_records = scrape_ebay(batch_id, mode=mode)
                p = save_batch(
                    ebay_records, batch_id, "ebay", rate_mid=rate_mid
                )
                if p: batches.append(p)
                stats["ebay"] = len(ebay_records)
                log.info(
                    f"  ✅ eBay: {len(ebay_records):,} registros"
                )
            except Exception as e:
                log.error(f"  ❌ eBay: {e}")
                stats["ebay"] = 0
    else:
        stats["ebay"] = 0

    # ── 6. CamelCamelCamel ───────────────────────────────────────────
    if _HAS_CAMEL and mode in ("historical", "full"):
        log.info(_step("🐪 CamelCamelCamel"))
        if not _near_timeout():
            try:
                camel_records = scrape_camel(batch_id, mode=mode)
                p = save_batch(
                    camel_records, batch_id, "camel", rate_mid=rate_mid
                )
                if p: batches.append(p)
                stats["camel"] = len(camel_records)
                log.info(
                    f"  ✅ Camel: {len(camel_records):,} registros"
                )
            except Exception as e:
                log.error(f"  ❌ Camel: {e}")
                stats["camel"] = 0
    else:
        if not _HAS_CAMEL and mode in ("historical", "full"):
            log.warning(
                "  ⚠️  CamelCamelCamel omitido — scraper no disponible"
            )
        stats["camel"] = 0

    # ── 7. PCPartPicker ──────────────────────────────────────────────
    if _HAS_PCP and mode in ("historical", "full"):
        log.info(_step("🖥️ PCPartPicker"))
        if not _near_timeout():
            try:
                pcp_records = scrape_pcpartpicker(batch_id, mode=mode)
                p = save_batch(
                    pcp_records, batch_id, "pcpartpicker",
                    rate_mid=rate_mid
                )
                if p: batches.append(p)
                stats["pcpartpicker"] = len(pcp_records)
                log.info(
                    f"  ✅ PCPartPicker: {len(pcp_records):,} registros"
                )
            except Exception as e:
                log.error(f"  ❌ PCPartPicker: {e}")
                stats["pcpartpicker"] = 0
    else:
        if not _HAS_PCP and mode in ("historical", "full"):
            log.warning(
                "  ⚠️  PCPartPicker omitido — scraper no disponible"
            )
        stats["pcpartpicker"] = 0

    # ── 8. Kaggle ────────────────────────────────────────────────────
    if _HAS_KAGGLE and mode in ("kaggle_only", "full"):
        log.info(_step("📦 Kaggle datasets"))
        if not _near_timeout():
            try:
                kaggle_records = scrape_kaggle(batch_id, mode=mode)
                p = save_batch(
                    kaggle_records, batch_id, "kaggle", rate_mid=rate_mid
                )
                if p: batches.append(p)
                stats["kaggle"] = len(kaggle_records)
                log.info(
                    f"  ✅ Kaggle: {len(kaggle_records):,} registros"
                )
            except Exception as e:
                log.error(f"  ❌ Kaggle: {e}")
                stats["kaggle"] = 0
    else:
        if not _HAS_KAGGLE and mode in ("kaggle_only", "full"):
            log.warning(
                "  ⚠️  Kaggle omitido — scraper no disponible"
            )
        stats["kaggle"] = 0

    # ── 9. Importación ───────────────────────────────────────────────
    if _HAS_IMPORTACION and mode in (
        "normal", "local_only", "historical", "full"
    ):
        log.info(_step("📦 Precios de importación"))
        if not _near_timeout():
            try:
                imp_records = scrape_importacion(batch_id, mode=mode)
                p = save_batch(
                    imp_records, batch_id, "importacion",
                    rate_mid=rate_mid
                )
                if p: batches.append(p)
                stats["importacion"] = len(imp_records)
                log.info(
                    f"  ✅ Importación: {len(imp_records):,} registros"
                )
            except Exception as e:
                log.error(f"  ❌ Importación: {e}")
                stats["importacion"] = 0
    else:
        stats["importacion"] = 0

    # ── 10. Competencia ──────────────────────────────────────────────
    if _HAS_COMPETENCIA and mode in ("normal", "local_only", "full"):
        log.info(_step("🔍 Competencia local PE"))
        if not _near_timeout():
            try:
                comp_records = scrape_competencia(batch_id, mode=mode)
                p = save_batch(
                    comp_records, batch_id, "competencia",
                    rate_mid=rate_mid
                )
                if p: batches.append(p)
                stats["competencia"] = len(comp_records)
                log.info(
                    f"  ✅ Competencia: {len(comp_records):,} registros"
                )
            except Exception as e:
                log.error(f"  ❌ Competencia: {e}")
                stats["competencia"] = 0
    else:
        stats["competencia"] = 0

    # ── Merge al MASTER ──────────────────────────────────────────────
    master_total, new_added = merge_to_master(batches)
    stats["master_total"] = master_total

    # ── Reporte ──────────────────────────────────────────────────────
    elapsed = time.time() - start
    report  = save_report(batch_id, stats, elapsed, new_added)

    # ── Resumen final ─────────────────────────────────────────────────
    log.info("\n" + "═" * 60)
    log.info("  RESUMEN FINAL")
    log.info("═" * 60)
    log.info(f"  Batch ID     : {batch_id}")
    log.info(f"  Modo         : {mode}")
    log.info(f"  Duración     : {int(elapsed//60)}m {int(elapsed%60)}s")
    log.info(f"  {'Fuente':<22} {'Registros':>10}")
    log.info(f"  {'-'*34}")
    for src, count in stats.items():
        if src != "master_total":
            log.info(f"  {src:<22} {count:>10,}")
    log.info(f"  {'-'*34}")
    log.info(f"  {'NUEVOS REALES':<22} {new_added:>10,}")
    log.info(f"  {'MASTER TOTAL':<22} {master_total:>10,}")
    log.info("═" * 60)

    return report


# ══════════════════════════════════════════════════════════════════════
# ARGPARSE
# ══════════════════════════════════════════════════════════════════════

def _parse_args():
    parser = argparse.ArgumentParser(
        description="Pipeline de recolección — tesis-hardware-peru v5.11",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        default="normal",
        choices=[
            "normal", "local_only", "historical", "kaggle_only", "full"
        ],
        help=(
            "Modo de ejecución:\n"
            "  normal      → local PE + MeLi PE + Newegg + eBay + "
            "importacion + competencia (~55 min)\n"
            "  local_only  → Falabella/Hiraoka + MeLi PE + importacion + "
            "competencia (~30 min)\n"
            "  historical  → Newegg + eBay + CamelCamelCamel + "
            "PCPartPicker + importacion (~50 min)\n"
            "  kaggle_only → solo descarga Kaggle (~30 min)\n"
            "  full        → todo (~110 min) "
            "⚠️ usa MAX_ELAPSED_S para merge seguro"
        ),
    )
    parser.add_argument(
        "--batch-id",
        default=None,
        help="Batch ID manual (default: timestamp automático)",
    )
    parser.add_argument(
        "--max-elapsed",
        type=int,
        default=None,
        help=(
            f"Timeout en segundos "
            f"(default: {MAX_ELAPSED_S}s = {MAX_ELAPSED_S//60} min)"
        ),
    )
    return parser.parse_args()


# ══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    args = _parse_args()
    if args.max_elapsed:
        MAX_ELAPSED_S = args.max_elapsed
    batch_id = (
        args.batch_id or
        datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    )
    run(mode=args.mode, batch_id=batch_id)
