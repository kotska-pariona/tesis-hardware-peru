#!/usr/bin/env python3
"""
rebuild_master.py — Reconstrucción retroactiva del MASTER
════════════════════════════════════════════════════════════════════
Lee TODOS los batch_*.csv de data/raw/ (incluye los mal nombrados
batch_batch_*) y reconstruye MASTER_hardware_peru.csv aplicando la
lógica de identidad CORREGIDA:

  - normalize_schema()  [O23][O24]  (igual que main.py v5.9)
  - convert_currency()  [O25]       (usa MASTER_exchange_rate.csv
                                      para buscar el rate_mid por fecha)
  - _make_dedup_key()   [O27]       (source, sku|url|title, price_date)
                                      -> price NUNCA es parte de la identidad

No sobreescribe el MASTER original. Genera:
  data/raw/MASTER_hardware_peru_REBUILT.csv

Uso:
  python rebuild_master.py --data-dir /ruta/a/data/raw
"""

import argparse
import csv
import glob
import hashlib
import re
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


def convert_currency(records: list, rate_lookup: dict) -> list:
    """rate_lookup: dict fecha(YYYY-MM-DD) -> rate_mid (float)."""
    for row in records:
        date_key = (row.get("price_date") or "")[:10]
        rate_mid = rate_lookup.get(date_key)
        if not rate_mid:
            continue
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
        if not (name.startswith("batch_") ):
            continue
        selected.append(Path(f))
    return sorted(selected)


def _load_exchange_rate_lookup(data_dir: Path) -> dict:
    """Construye dict fecha -> rate_mid desde MASTER_exchange_rate.csv."""
    path = data_dir / "MASTER_exchange_rate.csv"
    lookup = {}
    if not path.exists():
        return lookup
    with open(path, encoding="utf-8") as fh:
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
    print(f"\n💱 Tipos de cambio cargados: {len(rate_lookup)} fechas")

    raw_rows = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
                raw_rows.extend(rows)
        except Exception as e:
            print(f"⚠️  Error leyendo {f.name}: {e}")

    print(f"\n📊 Total filas RAW leídas: {len(raw_rows):,}")

    raw_rows = normalize_schema(raw_rows)
    raw_rows = convert_currency(raw_rows, rate_lookup)

    # Dedup global con la clave corregida
    seen = set()
    final_rows = []
    skipped = 0
    for row in raw_rows:
        key = _make_dedup_key(row)
        if key not in seen:
            seen.add(key)
            final_rows.append(row)
        else:
            skipped += 1

    print(f"✅ Filas únicas tras dedup corregido: {len(final_rows):,}")
    print(f"🗑️  Duplicados reales eliminados: {skipped:,}")

    # ── Prueba de continuidad temporal ──────────────────────────────────
    # Agrupa por identidad (sin fecha) y cuenta cuántos días distintos
    # tiene cada producto -> demuestra si la serie temporal ya funciona.
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
