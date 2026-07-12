#!/usr/bin/env python3
"""
temporal_split.py v1.0
═══════════════════════════════════════════════════════════════════
Etapa II del pipeline (Sección 4.7.2 del plan de tesis).

Partición TEMPORAL del MASTER (post data_quality.py) en
train/val/test, respetando estrictamente el orden cronológico
para evitar leakage entre splits.

Se ejecuta ANTES de mice_imputer.py y feature_engineering.py:
  data_quality.py → **temporal_split.py** → mice_imputer.py →
  feature_engineering.py

ANTI-LEAKAGE (Kapoor & Narayanan, 2023):
  - El corte se hace por FECHA GLOBAL, no por fila aleatoria ni por
    SKU. Un split 75/12.5/12.5% aleatorio por fila mezclaría fechas
    pasadas y futuras del mismo SKU entre train/val/test, lo cual es
    leakage cronológico encubierto.
  - Ninguna fecha (price_date) queda partida entre dos splits: todas
    las filas de un mismo día van al mismo split.
  - Se valida explícitamente que
      max(fecha en train) < min(fecha en val)
      max(fecha en val)   < min(fecha en test)
    antes de escribir los archivos de salida (fail-fast si no se
    cumple).

DISEÑO:
  [T1] Corte por fecha única, no por fila: se ordenan las fechas
       distintas de price_date y se buscan 2 puntos de corte que
       acerquen la proporción ACUMULADA de filas a 75/12.5/12.5%,
       sin partir ningún día entre dos splits.
  [T2] Parsing de fecha robusto: usa pd.to_datetime(errors="coerce")
       y aborta (fail-fast) si hay filas con price_date no parseable,
       ya que esas filas no pueden ubicarse temporalmente con certeza.
  [T3] Detección de "cold-start SKUs": reporta SKUs presentes en
       val/test que NUNCA aparecieron en train. Es información crítica
       para feature_engineering.py (esos SKUs no tendrán contexto
       histórico prestable, y sus lags/MA serán NaN legítimamente).
  [T4] Validación post-corte de no-solapamiento temporal (assert
       explícito), no solo confianza en la lógica de corte.
  [T5] Reporte JSON (split_report_<batch>.json) con fechas de corte,
       tamaños reales de cada split, proporciones logradas vs.
       objetivo, y estadísticas de cold-start SKUs.

Uso:
    python preprocessing/temporal_split.py \
        --input data/processed/MASTER_hardware_peru_clean.csv \
        --output-dir data/processed \
        --train-ratio 0.75 --val-ratio 0.125
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd


# ══════════════════════════════════════════════════════════════════
# [T2] PARSEO ROBUSTO DE FECHA — fail-fast si hay valores inválidos
# ══════════════════════════════════════════════════════════════════
def _parse_dates_or_fail(df: pd.DataFrame, date_col: str = "price_date") -> pd.DataFrame:
    df = df.copy()
    df["_parsed_date"] = pd.to_datetime(df[date_col], errors="coerce")
    n_invalid = df["_parsed_date"].isna().sum()

    if n_invalid > 0:
        pct = round(n_invalid / len(df) * 100, 3)
        print(f"\n❌ FATAL: {n_invalid:,} filas ({pct}%) tienen '{date_col}' "
              f"no parseable como fecha.")
        print("   No se puede garantizar el orden cronológico del split.")
        print("   Revisar data_quality.py / data_contract.yaml antes de continuar.")
        sys.exit(1)

    return df


# ══════════════════════════════════════════════════════════════════
# [T1] BÚSQUEDA DE PUNTOS DE CORTE POR FECHA (no por fila)
# ══════════════════════════════════════════════════════════════════
def _find_date_cutoffs(
    df: pd.DataFrame,
    train_ratio: float,
    val_ratio: float,
) -> tuple:
    """
    Retorna (cutoff_train_end, cutoff_val_end) — dos fechas tales que:
      - Todas las filas con _parsed_date <= cutoff_train_end van a train.
      - Todas las filas con cutoff_train_end < _parsed_date <= cutoff_val_end van a val.
      - El resto va a test.
    Los cortes se eligen sobre las FECHAS ÚNICAS ordenadas, buscando la
    fecha cuya proporción acumulada de FILAS se acerque más al target,
    sin partir ningún día entre splits.
    """
    daily_counts = (
        df.groupby("_parsed_date").size().sort_index()
    )
    cum_frac = daily_counts.cumsum() / daily_counts.sum()

    # Fecha única cuya fracción acumulada está más cerca del target,
    # pero SIN excederlo (evita que train se "coma" parte de val).
    train_candidates = cum_frac[cum_frac <= train_ratio]
    if train_candidates.empty:
        # dataset muy pequeño / pocas fechas únicas: toma la primera fecha
        cutoff_train_end = daily_counts.index[0]
    else:
        cutoff_train_end = train_candidates.index[-1]

    target_val_end = train_ratio + val_ratio
    val_candidates = cum_frac[(cum_frac <= target_val_end) & (cum_frac.index > cutoff_train_end)]
    if val_candidates.empty:
        # fallback: siguiente fecha única disponible tras cutoff_train_end
        remaining = cum_frac[cum_frac.index > cutoff_train_end]
        cutoff_val_end = remaining.index[0] if not remaining.empty else cutoff_train_end
    else:
        cutoff_val_end = val_candidates.index[-1]

    return cutoff_train_end, cutoff_val_end


# ══════════════════════════════════════════════════════════════════
# [T3] DETECCIÓN DE COLD-START SKUS
# ══════════════════════════════════════════════════════════════════
def _detect_cold_start_skus(train: pd.DataFrame, val: pd.DataFrame, test: pd.DataFrame) -> dict:
    train_skus = set(train["sku"].dropna().unique())
    val_skus   = set(val["sku"].dropna().unique())
    test_skus  = set(test["sku"].dropna().unique())

    val_cold  = val_skus - train_skus
    test_cold = test_skus - (train_skus | val_skus)

    return {
        "train_skus_unicos": len(train_skus),
        "val_skus_unicos": len(val_skus),
        "test_skus_unicos": len(test_skus),
        "val_cold_start_skus": len(val_cold),
        "val_cold_start_pct": round(len(val_cold) / max(len(val_skus), 1) * 100, 2),
        "test_cold_start_skus": len(test_cold),
        "test_cold_start_pct": round(len(test_cold) / max(len(test_skus), 1) * 100, 2),
    }


# ══════════════════════════════════════════════════════════════════
# [T4] VALIDACIÓN DE NO-SOLAPAMIENTO TEMPORAL — fail-fast
# ══════════════════════════════════════════════════════════════════
def _validate_no_temporal_overlap(train: pd.DataFrame, val: pd.DataFrame, test: pd.DataFrame):
    max_train = train["_parsed_date"].max()
    min_val   = val["_parsed_date"].min()
    max_val   = val["_parsed_date"].max()
    min_test  = test["_parsed_date"].min()

    if max_train >= min_val:
        print(f"\n❌ FATAL: solapamiento temporal train/val "
              f"(max_train={max_train} >= min_val={min_val})")
        sys.exit(1)

    if max_val >= min_test:
        print(f"\n❌ FATAL: solapamiento temporal val/test "
              f"(max_val={max_val} >= min_test={min_test})")
        sys.exit(1)

    print(f"\n✅ Validación temporal OK:")
    print(f"   train : ... → {max_train.date()}")
    print(f"   val   : {min_val.date()} → {max_val.date()}")
    print(f"   test  : {min_test.date()} → ...")


# ══════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ══════════════════════════════════════════════════════════════════
def run_temporal_split(
    input_path: Path,
    output_dir: Path,
    train_ratio: float = 0.75,
    val_ratio: float = 0.125,
    date_col: str = "price_date",
):
    output_dir.mkdir(parents=True, exist_ok=True)
    test_ratio = 1.0 - train_ratio - val_ratio

    print("═" * 60)
    print("  TEMPORAL SPLIT v1.0 — Etapa II")
    print("═" * 60)
    print(f"\n🎯 Proporciones objetivo: train={train_ratio:.1%} | "
          f"val={val_ratio:.1%} | test={test_ratio:.1%}")

    df = pd.read_csv(input_path, low_memory=False)
    print(f"\n📊 MASTER cargado: {len(df):,} filas | {df.shape[1]} columnas")

    # [T2] Parseo robusto — fail-fast
    df = _parse_dates_or_fail(df, date_col=date_col)
    print(f"   Rango de fechas: {df['_parsed_date'].min().date()} → "
          f"{df['_parsed_date'].max().date()}")
    print(f"   Fechas únicas  : {df['_parsed_date'].nunique():,}")

    # [T1] Búsqueda de cortes por fecha
    cutoff_train_end, cutoff_val_end = _find_date_cutoffs(df, train_ratio, val_ratio)

    train = df[df["_parsed_date"] <= cutoff_train_end].copy()
    val   = df[(df["_parsed_date"] > cutoff_train_end) & (df["_parsed_date"] <= cutoff_val_end)].copy()
    test  = df[df["_parsed_date"] > cutoff_val_end].copy()

    print(f"\n📐 Cortes encontrados:")
    print(f"   train : hasta {cutoff_train_end.date()}")
    print(f"   val   : {cutoff_train_end.date()} (excl.) → {cutoff_val_end.date()}")
    print(f"   test  : desde {cutoff_val_end.date()} (excl.)")

    # [T4] Validación fail-fast de no-solapamiento
    _validate_no_temporal_overlap(train, val, test)

    # Limpieza de columna auxiliar
    train = train.drop(columns=["_parsed_date"])
    val   = val.drop(columns=["_parsed_date"])
    test  = test.drop(columns=["_parsed_date"])

    # [T3] Cold-start SKUs
    cold_start_stats = _detect_cold_start_skus(train, val, test)

    # Proporciones reales logradas
    total = len(df)
    real_ratios = {
        "train": round(len(train) / total, 4),
        "val":   round(len(val) / total, 4),
        "test":  round(len(test) / total, 4),
    }

    print(f"\n📊 Tamaños reales de los splits:")
    print(f"   train : {len(train):,} filas ({real_ratios['train']:.1%})")
    print(f"   val   : {len(val):,} filas ({real_ratios['val']:.1%})")
    print(f"   test  : {len(test):,} filas ({real_ratios['test']:.1%})")

    print(f"\n🧊 Cold-start SKUs (presentes en val/test pero no antes):")
    print(f"   val  : {cold_start_stats['val_cold_start_skus']:,} SKUs "
          f"({cold_start_stats['val_cold_start_pct']}% de los SKUs de val)")
    print(f"   test : {cold_start_stats['test_cold_start_skus']:,} SKUs "
          f"({cold_start_stats['test_cold_start_pct']}% de los SKUs de test)")

    # ── Guardar splits ──────────────────────────────────────────
    train.to_csv(output_dir / "train.csv", index=False)
    val.to_csv(output_dir / "val.csv", index=False)
    test.to_csv(output_dir / "test.csv", index=False)
    print(f"\n💾 Splits guardados en {output_dir}/ (train.csv, val.csv, test.csv)")

    # ── Reporte JSON [T5] ────────────────────────────────────────
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report = {
        "batch_id": batch_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input_file": str(input_path),
        "proporciones_objetivo": {
            "train": train_ratio, "val": val_ratio, "test": test_ratio,
        },
        "proporciones_reales": real_ratios,
        "cortes": {
            "train_end": str(cutoff_train_end.date()),
            "val_end": str(cutoff_val_end.date()),
        },
        "tamanos": {
            "train": len(train), "val": len(val), "test": len(test),
            "total": total,
        },
        "cold_start_skus": cold_start_stats,
    }
    report_path = output_dir / f"split_report_{batch_id}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"📋 Reporte de split: {report_path.name}")

    print("\n" + "═" * 60)
    print("  ✅ Split temporal completado — listo para mice_imputer.py")
    print("═" * 60)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Partición temporal — Etapa II")
    parser.add_argument("--input", required=True, help="Ruta al MASTER limpio (post data_quality.py)")
    parser.add_argument("--output-dir", required=True, help="Carpeta de salida (train.csv, val.csv, test.csv)")
    parser.add_argument("--train-ratio", type=float, default=0.75, help="Proporción de train (default: 0.75)")
    parser.add_argument("--val-ratio", type=float, default=0.125, help="Proporción de val (default: 0.125)")
    parser.add_argument("--date-col", default="price_date", help="Nombre de la columna de fecha (default: price_date)")
    args = parser.parse_args()

    if args.train_ratio + args.val_ratio >= 1.0:
        print("❌ FATAL: train_ratio + val_ratio debe ser < 1.0 (para dejar espacio a test)")
        sys.exit(1)

    run_temporal_split(
        Path(args.input),
        Path(args.output_dir),
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        date_col=args.date_col,
    )
