#!/usr/bin/env python3
"""
rebuild_master.py — Reconstrucción retroactiva del MASTER (v2 - corregido)
════════════════════════════════════════════════════════════════════
Lee TODOS los batch_*.csv de data/raw/ (incluye los mal nombrados
batch_batch_*) y reconstruye MASTER_hardware_peru.csv aplicando la
lógica de identidad CORREGIDA:

  - normalize_schema()  [O23][O24]  (igual que main.py v5.9)
  - convert_currency()  [O25]       (usa MASTER_exchange_rate.csv
                                      para buscar el rate_mid por fecha)
  - _make_dedup_key()   [O27]       (source, sku|url|title, price_date)
                                      -> price NUNCA es parte de la identidad

CHANGELOG v2:
  [FIX-1] convert_currency ahora reporta fechas sin rate_mid (silencioso -> visible)
          y también rellena el par price_orig_pen / price_orig_usd.
  [FIX-2] Lectura de CSV con utf-8-sig + errors="replace" (evita descartar
          archivos completos por 1 caracter mal codificado) + log por archivo.
  [FIX-3] Dedup ahora conserva la ÚLTIMA observación cronológica del día
          (antes se quedaba con la primera según orden alfabético de archivo).
  [FIX-4] Reporte de completitud de price_usd / price_orig_usd ANTES vs
          DESPUÉS del rebuild (la métrica que bloqueaba el Hito H1).

No sobreescribe el MASTER original. Genera:
  data/raw/MASTER_hardware_peru_REBUILT.csv

Uso:
  python rebuild_master.py --data-dir /ruta/a/data/raw
"""

import argparse
import csv
import glob
import hashlib
from pathlib import Path
from collections import defaultdict


# ── Copiado de main.py v5.9 (sin cambios) ──────────────────────────────
FIELD_ORDER = [
    "batch_id", "timestamp", "source", "category",
    "sku", "brand", "title",
    "price_pen", "price_orig_pen", "price_usd", "price_orig_usd",
    "price_date", "discount_pct", "price_currency",
    "rating", "reviews",
    "condition", "available_qty", "free_shipping",
    "is_official_store", "is_best_seller", "is_good_seller",
    "seller_nickname",
    "seller_feedback_score", "seller_feedback_pct",
    "retailer", "part_id", "url",
]

_ALIAS_GROUPS = {
    "sku":            ["sku", "asin_sku", "item_id", "part_id"],
    "available_qty":  ["available_qty", "available"],
    "price_orig_pen": ["price_orig_pen", "original_price"],
    "free_shipping":  ["free_shipping", "shipping_free"],
    "price_currency": ["price_currency", "currency"],
}

# [FIX-1] Pares moneda a reparar: (campo_pen, campo_usd)
_CURRENCY_PAIRS = [
    ("price_pen", "price_usd"),
    ("price_orig_pen", "price_orig_usd"),
]


def normalize_schema(records: list) -> list:
    for row in records:
        for canon, aliases in _ALIAS_GROUPS.items():
            current = row.get(canon)
            if current is None or current == "":
                for alt in aliases:
                    val = row.get(alt)
                    if val is not None and val != "":
                        row[canon] = val
                        break
        pd_val = row.get("price_date")
        ts_val = row.get("timestamp")
        if (pd_val is None or pd_val == "") and ts_val:
            row["price_date"] = str(ts_val)[:10]
    return records


def _completeness_report(records: list, label: str):
    """[FIX-4] Reporta % de completitud de los campos de precio en USD."""
    total = len(records)
    if total == 0:
        print(f"   ({label}) sin registros")
        return
    for _, usd_field in _CURRENCY_PAIRS:
        ok = sum(1 for r in records if r.get(usd_field) not in (None, ""))
        print(f"   ({label}) {usd_field}: {ok:,}/{total:,} ({ok/total:.2%})")


def convert_currency(records: list, rate_lookup: dict) -> list:
    """
    [FIX-1] rate_lookup: dict fecha(YYYY-MM-DD) -> rate_mid (float).
    Ahora repara AMBOS pares de moneda (precio actual y precio original)
    y reporta explícitamente qué fechas no se pudieron reparar por falta
    de tipo de cambio (antes era un `continue` totalmente silencioso).
    """
    filled_counts = defaultdict(int)
    missing_dates_by_field = defaultdict(set)

    for row in records:
        date_key = (row.get("price_date") or "")[:10]
        rate_mid = rate_lookup.get(date_key)

        for pen_field, usd_field in _CURRENCY_PAIRS:
            usd = row.get(usd_field)
            pen = row.get(pen_field)

            needs_fill = (usd is None or usd == "") and pen not in (None, "")
            needs_fill_rev = (pen is None or pen == "") and usd not in (None, "")

            if not rate_mid:
                # Había algo que reparar pero no hay tipo de cambio para esa fecha
                if date_key and (needs_fill or needs_fill_rev):
                    missing_dates_by_field[usd_field].add(date_key)
                continue

            try:
                if needs_fill:
                    row[usd_field] = round(float(pen) / rate_mid, 2)
                    filled_counts[usd_field] += 1
                elif needs_fill_rev:
                    row[pen_field] = round(float(usd) * rate_mid, 2)
                    filled_counts[pen_field] += 1
            except (ValueError, TypeError):
                continue

    print("\n💱 Resultado de conversión de moneda:")
    for field, count in filled_counts.items():
        print(f"   ✅ {field}: {count:,} valores rellenados")
    for field, dates in missing_dates_by_field.items():
        print(f"   ⚠️  {field}: {len(dates)} fecha(s) SIN tipo de cambio "
              f"-> {sorted(dates)}")
    if not missing_dates_by_field:
        print("   ✅ Todas las fechas con datos faltantes tenían tipo de cambio disponible.")

    return records


def _make_dedup_key(row: dict) -> tuple:
    """[O27] price NUNCA forma parte de la identidad."""
    source     = (row.get("source") or "").strip()
    sku        = (row.get("sku") or "").strip()
    price_date = (row.get("price_date") or "").strip()

    if sku:
        return (source, sku, price_date)

    url   = (row.get("url") or "").strip()
    title = (row.get("title") or row.get("name") or "")[:120].strip().lower()
    identity_source = url if url else title
    fp = hashlib.md5(identity_source.encode()).hexdigest()[:12]
    return (source, f"fp_{fp}", price_date)


def _sort_ts_key(row: dict) -> str:
    """[FIX-3] Clave de orden cronológico. Usa timestamp completo si existe,
    si no cae a price_date. Filas sin ninguno quedan al inicio (orden estable)."""
    return row.get("timestamp") or row.get("price_date") or ""


# ── Selección de archivos a procesar ───────────────────────────────────
def _discover_batch_files(data_dir: Path) -> list:
    """
    Incluye batch_*.csv y batch_batch_*.csv.
    Excluye: MASTER_*.csv, archivos *_dolar.csv (van en su propio
    MASTER_exchange_rate.csv, sin sku -> no aplican a este dedup),
    y batch_24h_*.csv (agregados diarios, no raw -> evitar doble conteo).
    """
    all_csv = glob.glob(str(data_dir / "*.csv"))
    selected = []
    for f in all_csv:
        name = Path(f).name
        if name.startswith("MASTER_"):
            continue
        if name.startswith("batch_24h_"):
            continue
        if name.endswith("_dolar.csv"):
            continue
        if not (name.startswith("batch_")):
            continue
        selected.append(Path(f))
    return sorted(selected)


def _load_exchange_rate_lookup(data_dir: Path) -> dict:
    """Construye dict fecha -> rate_mid desde MASTER_exchange_rate.csv."""
    path = data_dir / "MASTER_exchange_rate.csv"
    lookup = {}
    if not path.exists():
        print(f"⚠️  ATENCIÓN: no existe {path.name}, no se podrá convertir moneda.")
        return lookup
    # [FIX-2] encoding robusto también aquí
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for row in csv.DictReader(fh):
            date = (row.get("date") or "")[:10]
            mid  = row.get("mid")
            if date and mid:
                try:
                    lookup[date] = float(mid)
                except ValueError:
                    continue
    return lookup


# ── Pipeline principal ──────────────────────────────────────────────────
def rebuild(data_dir: Path):
    files = _discover_batch_files(data_dir)
    print(f"📂 Archivos batch detectados: {len(files)}")
    for f in files:
        print(f"   - {f.name}")

    rate_lookup = _load_exchange_rate_lookup(data_dir)
    print(f"\n💱 Tipos de cambio cargados: {len(rate_lookup)} fechas -> "
          f"{sorted(rate_lookup.keys())}")

    # [FIX-2] Lectura robusta: nunca se descarta un archivo completo por un
    # error de encoding puntual, y se loguea cuántas filas aportó cada uno.
    raw_rows = []
    for f in files:
        try:
            with open(f, encoding="utf-8-sig", errors="replace", newline="") as fh:
                rows = list(csv.DictReader(fh))
                raw_rows.extend(rows)
                print(f"   ✔ {f.name}: {len(rows):,} filas")
        except Exception as e:
            print(f"   ❌ ERROR leyendo {f.name}: {e} (archivo OMITIDO por completo)")

    print(f"\n📊 Total filas RAW leídas: {len(raw_rows):,}")

    raw_rows = normalize_schema(raw_rows)

    # [FIX-4] Completitud ANTES de la conversión de moneda
    print("\n📈 Completitud ANTES del rebuild (post-normalize, pre-convert):")
    _completeness_report(raw_rows, "ANTES")

    raw_rows = convert_currency(raw_rows, rate_lookup)

    # [FIX-3] Orden cronológico ascendente para que, al deduplicar,
    # la ÚLTIMA observación del día sea la que sobreviva (no la primera
    # según orden alfabético de archivo, que era arbitrario).
    raw_rows.sort(key=_sort_ts_key)

    # Dedup global con la clave corregida — conserva la ÚLTIMA ocurrencia
    dedup_map = {}
    skipped = 0
    for row in raw_rows:
        key = _make_dedup_key(row)
        if key in dedup_map:
            skipped += 1
        dedup_map[key] = row  # overwrite -> se queda con la más reciente

    final_rows = list(dedup_map.values())

    print(f"\n✅ Filas únicas tras dedup corregido: {len(final_rows):,}")
    print(f"🗑️  Duplicados reales eliminados: {skipped:,} "
          f"(se conservó la observación más reciente de cada día)")

    # [FIX-4] Completitud DESPUÉS del rebuild
    print("\n📈 Completitud DESPUÉS del rebuild:")
    _completeness_report(final_rows, "DESPUÉS")

    # ── Prueba de continuidad temporal ──────────────────────────────────
    identity_dates = defaultdict(set)
    for row in final_rows:
        source = (row.get("source") or "").strip()
        sku    = (row.get("sku") or "").strip()
        if not sku:
            continue
        identity_dates[(source, sku)].add((row.get("price_date") or "")[:10])

    multi_day = {k: v for k, v in identity_dates.items() if len(v) > 1}
    print(f"\n🕒 Productos con SKU presentes en >1 día distinto: {len(multi_day):,}")
    print("   (esto es la PRUEBA de que la serie temporal ya no se fragmenta)")

    example_count = 0
    for (source, sku), dates in multi_day.items():
        if example_count >= 5:
            break
        print(f"   ejemplo: source={source} sku={sku} -> fechas={sorted(dates)}")
        example_count += 1

    # ── Escribir el MASTER reconstruido ─────────────────────────────────
    all_fields = set(FIELD_ORDER)
    for r in final_rows:
        all_fields.update(r.keys())
    ordered    = [f for f in FIELD_ORDER if f in all_fields]
    remainder  = sorted(all_fields - set(ordered))
    fieldnames = ordered + remainder

    out_path = data_dir / "MASTER_hardware_peru_REBUILT.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(final_rows)

    print(f"\n💾 Guardado: {out_path}")
    print(f"   Total registros en MASTER reconstruido: {len(final_rows):,}")

    return final_rows


def _parse_args():
    p = argparse.ArgumentParser(description="Reconstrucción retroactiva del MASTER")
    p.add_argument("--data-dir", required=True, help="Ruta a la carpeta data/raw")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    rebuild(Path(args.data_dir))
