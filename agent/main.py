#!/usr/bin/env python3
"""
main.py — Orquestador v5.10
════════════════════════════════════════════════════════════════════
Fixes v5.10 (sobre v5.9):
  [O28] merge_to_master(): mensaje de log "Deduplicados" corregido.
        Decía de forma fija "(mismo source+sku+price_date)", pero
        desde [O27] el fallback sin sku identifica por url/title
        (sin price) — el mensaje no reflejaba ese caso. Ahora es
        genérico y describe ambas ramas de identidad.
  [O29] normalize_schema(): el parámetro source_tag se recibía en
        cada llamada desde save_batch() pero nunca se usaba dentro
        de la función. Ahora se usa en logging DEBUG por fuente,
        permitiendo auditar qué alias se rellenó y en qué SKU, sin
        cambiar el comportamiento ni la firma de la función.

Fixes v5.9 (sobre v5.8):
  [O23] normalize_schema(): consolida columnas alias detectadas por
        análisis del MASTER real (sku/asin_sku/item_id/part_id,
        available_qty/available, free_shipping/shipping_free,
        price_currency/currency, price_orig_pen/original_price).
        Se ejecuta dentro de save_batch() para las 10 fuentes, en
        UN solo punto de entrada — no se tocó ningún scraper
        individual.
  [O24] normalize_schema() también deriva price_date desde timestamp
        cuando price_date llega vacío. Esto corrige el bug confirmado
        por diagnóstico: ebay_usa, falabella_pe, hiraoka_pe (25,421
        de 40,040 filas del MASTER) tenían la fecha en timestamp
        pero nunca la copiaban a price_date — inflando
        artificialmente el % de "datos faltantes" en esa columna
        crítica.
  [O25] convert_currency(): rellena price_usd/price_pen cruzado
        usando el 'mid' del tipo de cambio del batch actual. Corrige
        el bug confirmado: fuentes USD (ebay_usa, amazon_usa,
        aliexpress) solo llenaban price_usd; fuentes PEN
        (falabella*, hiraoka*) solo llenaban price_pen. Ninguna
        hacía la conversión cruzada, dejando 43.93% de price_usd
        (columna objetivo) vacío sin necesidad — el dato es 100%
        derivable matemáticamente con el rate del batch.
  [O26] El tipo de cambio (scrape_dolar) YA NO se mezcla en
        MASTER_hardware_peru.csv vía merge_to_master(). Antes, sus
        registros (sin sku, con date en vez de price_date)
        colisionaban con la dedup key (source, sku, price_date) y
        se perdían silenciosamente (por eso exchangerate_api solo
        tenía 2 filas en 40,040). Ahora tiene su propio archivo
        MASTER_exchange_rate.csv vía save_dolar_batch(), con dedup
        propia por (source, date).
  [O27] _make_dedup_key(): FIX CRÍTICO — el fallback SIN sku ya NO
        usa price en el fingerprint. Antes (fix [O11], versión
        anterior a v5.7), cuando un registro no tenía sku, el
        fingerprint MD5 se calculaba sobre (title + price),
        generando una clave DISTINTA cada vez que el precio cambiaba
        de un día a otro para el MISMO producto sin sku — esto
        derrotaba la deduplicación y generaba filas acumulativas
        duplicadas para toda fuente sin sku (competencia,
        importación). Ahora la prioridad de identidad es:
        sku > url > title (SIN price); el precio se sigue
        diferenciando correctamente por price_date en la tupla
        final (source, identidad, price_date).

Fixes v5.8 (sobre v5.7):
  [O21] from __future__ import annotations — protege contra crash en
        Python <3.10 por el uso de sintaxis 'X | None' (PEP 604) en
        los type hints. Sin esto, el script muere al importarse en
        cualquier runner con Python 3.9 o inferior.
  [O22] _make_dedup_key(): price_date RESTAURADO en la clave de
        dedup. El fix [O11] (v5.x anterior a v5.7) removió
        price_date por completo para "evitar duplicados
        acumulativos", pero esto congelaba cada SKU en su PRIMER
        precio visto para siempre — el pipeline nunca volvía a
        registrar cambios de precio del mismo SKU en días distintos.
        Esto destruía la dimensión temporal completa que necesita
        el análisis de series de tiempo (TFT/TCN/XGBoost). Ahora la
        clave es (source, sku, price_date): sigue evitando
        duplicados si el pipeline corre 2x el mismo día, pero
        permite 1 registro por SKU por día — la serie temporal real.

Fixes v5.7 (sobre v5.6):
  [O16] scrape_pcpartpicker cargado dinámicamente igual que
        MeLi/Newegg — era import directo desde scrapers/__init__.py;
        si falla, el pipeline entero muere. Ahora es opcional con
        _HAS_PCP flag.
  [O17] Todos los scrapers llamados con mode= explícito — en v5.6
        solo scrape_local/scrape_dolar lo recibían; el resto
        ignoraba el parámetro
  [O18] scrape_kaggle / scrape_camel / scrape_pcpartpicker agregados
        a _HAS_* guards — si el módulo no carga, el paso se omite
        con warning en lugar de KeyError en import
  [O19] _near_timeout(): log solo una vez por invocación — en v5.6
        podía loguear el warning en cada paso si el pipeline ya
        estaba cerca del límite
  [O20] mode='local_only' incluye MeLi PE — en v5.6 estaba incluido
        pero faltaba en el help string; ahora ambos son consistentes
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

# ── [O23] Grupos de columnas alias → canónica (contrato data_contract.yaml) ──
# Basado en diagnóstico real del MASTER (12-jul-2026): primer valor no
# vacío de la lista gana y se copia a la columna canónica (primer elemento).
# NO se borra la columna alias original — solo se rellena la canónica.
_ALIAS_GROUPS = {
    "sku":            ["sku", "asin_sku", "item_id", "part_id"],
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
    [O29] source_tag ahora se usa en logging DEBUG por fuente — antes
          se recibía como parámetro pero nunca se usaba dentro de la
          función, perdiendo trazabilidad de qué fuente disparó cada
          relleno de alias.

    Ejecutado dentro de save_batch() — un solo punto de entrada para
    las 10 fuentes, sin modificar ningún scraper individual.
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
                        # ── [O29] AÑADIDO v5.10 ──────────────────────
                        log.debug(
                            f"  [normalize:{source_tag}] "
                            f"{alt} -> {canon} = {val!r} "
                            f"(sku={row.get('sku', '?')})"
                        )
                        # ── FIN [O29] ─────────────────────────────────
                        break

        # [O24] price_date derivado de timestamp — corrige el bug
        # confirmado en ebay_usa/falabella_pe/hiraoka_pe (25,421 filas)
        pd_val = row.get("price_date")
        ts_val = row.get("timestamp")
        if (pd_val is None or pd_val == "") and ts_val:
            row["price_date"] = str(ts_val)[:10]  # ISO8601 → YYYY-MM-DD

    return records


# ══════════════════════════════════════════════════════════════════════
# [O25] CONVERSIÓN DE MONEDA CRUZADA
# ══════════════════════════════════════════════════════════════════════

def convert_currency(records: list, rate_mid: float | None) -> list:
    """
    [O25] Rellena price_usd/price_pen cruzado usando el 'mid' del tipo
    de cambio del batch actual. Nunca sobreescribe un valor ya presente.

    Corrige el bug confirmado: fuentes USD (ebay_usa, amazon_usa,
    aliexpress) solo llenaban price_usd; fuentes PEN (falabella*,
    hiraoka*) solo llenaban price_pen — 43.93% de price_usd (columna
    objetivo, ec. 3.31) estaba vacío sin necesidad, siendo 100%
    derivable matemáticamente.
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
    rate_mid: float | None = None,   # [O25] propagado desde run()
) -> Path | None:
    """
    [O10] IOError se propaga — no retorna None silencioso en caso de error.
    Retorna None SOLO cuando records está vacío (sin datos, no error).
    [O23][O25] normalize_schema() y convert_currency() aplicados aquí —
    un solo punto de entrada para las 10 fuentes de producto.
    """
    if not records:
        log.warning(f"  [save] Sin registros para {source_tag}")
        return None

    records = normalize_schema(records, source_tag)          # [O23][O24][O29]
    if rate_mid:
        records = convert_currency(records, rate_mid)        # [O25]

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
# [O26] TIPO DE CAMBIO — ARCHIVO SEPARADO DEL MASTER DE PRODUCTOS
# ══════════════════════════════════════════════════════════════════════

def save_dolar_batch(records: list, batch_id: str) -> Path | None:
    """
    [O26] Guarda el tipo de cambio en MASTER_exchange_rate.csv, separado
    de MASTER_hardware_peru.csv. Dedup por (source, date) — NO por sku,
    ya que estos registros nunca tienen sku.

    Antes, estos registros pasaban por merge_to_master() con la dedup
    key (source, sku, price_date). Como no tienen sku ni price_date,
    caían en la rama de fingerprint (title+price) que colisionaba entre
    corridas del mismo día → se perdían silenciosamente. Por eso
    exchangerate_api solo tenía 2 filas en 40,040 registros del MASTER.
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
    [O22] price_date RESTAURADO en la clave de dedup.
    [O27] FIX CRÍTICO: el fallback SIN sku ya NO usa price en el
    fingerprint. Prioridad de identidad: sku > url > title.

    Antes ([O11], versión anterior a v5.7), el fallback sin sku
    usaba (title + price) para el fingerprint — esto generaba una
    clave DISTINTA cada vez que el precio cambiaba de un día a otro
    para el MISMO producto sin sku, derrotando la deduplicación.
    Ahora la identidad NUNCA depende del precio: sku > url > title.
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
    [O5] Escritura atómica: tmp → rename.
    [O26] batch_files ya NO incluye el batch de dólar — ver save_dolar_batch().
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
        # ── [O28] CORREGIDO v5.10 — mensaje genérico, ya no asume sku ──
        log.info(
            f"  [master] Deduplicados: {skipped:,} registros omitidos "
            f"(mismo source+identidad+price_date; identidad = sku, "
            f"o fingerprint url/title si no hay sku — ver [O27])"
        )
        # ── FIN [O28] ─────────────────────────────────────────────────

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
    log.info(f"  PIPELINE v5.10 — modo={mode} | batch={batch_id}")
    log.info(
        f"  MAX_ELAPSED_S={MAX_ELAPSED_S}s ({MAX_ELAPSED_S//60} min)"
    )
    log.info("═" * 60)

    # ── 1. Tipo de cambio (siempre) ──────────────────────────────
    # [O26] Ya NO se agrega a `batches` — tiene su propio MASTER.
    log.info(_step("💱 Tipo de cambio USD/PEN"))
    rate_mid = None
    try:
        dolar_records = scrape_dolar(batch_id, mode=mode)   # [O17]
        rate_mid = (
            dolar_records[0].get("mid") if dolar_records else None
        )
        save_dolar_batch(dolar_records, batch_id)            # [O26]
        stats["dolar"] = len(dolar_records)
        log.info(
            f"  ✅ Dolar: {len(dolar_records)} registros "
            f"(rate_mid={rate_mid})"
        )
    except Exception as e:
        log.error(f"  ❌ Dolar: {e}")
        stats["dolar"] = 0

    # ── 2. Scrapers locales PE ───────────────────────────────────
    if mode in ("normal", "local_only", "full"):
        log.info(_step("🇵🇪 Tiendas locales PE (Falabella + Hiraoka)"))
        if not _near_timeout():
            try:
                local_records = scrape_local(batch_id, mode=mode)   # [O17]
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

    # ── 3. MercadoLibre PE ───────────────────────────────────────
    # [O20] local_only incluye MeLi PE (consistente con help string)
    if _HAS_MELI and mode in ("normal", "local_only", "full"):
        log.info(_step("🛍️ MercadoLibre PE"))
        if not _near_timeout():
            try:
                meli_records = scrape_mercadolibre(
                    batch_id, mode=mode   # [O17]
                )
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

    # ── 4. Newegg USA ────────────────────────────────────────────
    if _HAS_NEWEGG and mode in ("normal", "historical", "full"):
        log.info(_step("🖥️ Newegg USA (precios USD)"))
        if not _near_timeout():
            try:
                newegg_records = scrape_newegg(
                    batch_id, mode=mode   # [O17]
                )
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

    # ── 5. eBay ──────────────────────────────────────────────────
    if mode in ("normal", "historical", "full"):
        log.info(_step("🛒 eBay USA"))
        if not _near_timeout():
            try:
                ebay_records = scrape_ebay(batch_id, mode=mode)   # [O17]
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

    # ── 6. CamelCamelCamel ───────────────────────────────────────
    # [O18] Guard _HAS_CAMEL — si el módulo no carga, omite con warning
    if _HAS_CAMEL and mode in ("historical", "full"):
        log.info(_step("🐪 CamelCamelCamel"))
        if not _near_timeout():
            try:
                camel_records = scrape_camel(batch_id, mode=mode)   # [O17]
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

    # ── 7. PCPartPicker ──────────────────────────────────────────
    # [O16] Guard _HAS_PCP — carga dinámica igual que MeLi/Newegg
    if _HAS_PCP and mode in ("historical", "full"):
        log.info(_step("🖥️ PCPartPicker"))
        if not _near_timeout():
            try:
                pcp_records = scrape_pcpartpicker(
                    batch_id, mode=mode   # [O17]
                )
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

    # ── 8. Kaggle ────────────────────────────────────────────────
    # [O18] Guard _HAS_KAGGLE — si el módulo no carga, omite con warning
    if _HAS_KAGGLE and mode in ("kaggle_only", "full"):
        log.info(_step("📦 Kaggle datasets"))
        if not _near_timeout():
            try:
                kaggle_records = scrape_kaggle(
                    batch_id, mode=mode   # [O17]
                )
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

    # ── 9. Importación ───────────────────────────────────────────
    # [O9] 'local_only' incluido
    if _HAS_IMPORTACION and mode in (
        "normal", "local_only", "historical", "full"
    ):
        log.info(_step("📦 Precios de importación"))
        if not _near_timeout():
            try:
                imp_records = scrape_importacion(
                    batch_id, mode=mode   # [O17]
                )
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

    # ── 10. Competencia ──────────────────────────────────────────
    # [O8] 'normal' incluido
    if _HAS_COMPETENCIA and mode in ("normal", "local_only", "full"):
        log.info(_step("🔍 Competencia local PE"))
        if not _near_timeout():
            try:
                comp_records = scrape_competencia(
                    batch_id, mode=mode   # [O17]
                )
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

    # ── Merge al MASTER ──────────────────────────────────────────
    # [O26] `batches` ya no incluye el batch de dólar (guardado aparte)
    log.info("\n[MERGE] Actualizando MASTER_hardware_peru.csv...")
    master_total, new_added = merge_to_master(batches)
    stats["master_total"] = master_total

    # ── Reporte ──────────────────────────────────────────────────
    elapsed = time.time() - start
    report  = save_report(batch_id, stats, elapsed, new_added)

    # ── Resumen final ────────────────────────────────────────────
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
        description="Pipeline de recolección — tesis-hardware-peru v5.10",
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
            "competencia (~30 min)\n"   # [O20] consistente con código
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
    # [O7] datetime con timezone explícita
    batch_id = (
        args.batch_id or
        datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    )
    run(mode=args.mode, batch_id=batch_id)
