#!/usr/bin/env python3
"""
data_quality.py v1.3
═══════════════════════════════════════════════════════════════════
Certifica el MASTER_hardware_peru.csv contra preprocessing/data_contract.yaml
ANTES de que llegue a feature_engineering.py (Etapa II).

CAMBIOS v1.2 (sobre v1.1):
  [FIX1] price_date faltante ya NO colapsa filas en drop_duplicates().
         Se separan explícitamente en 'sin_fecha_removidas' (reportado
         aparte) para no confundirlas con duplicados reales.
  [FIX2] price_usd == NaN ya NO se marca como outlier fuera de rango.
         Se preserva para que mice_imputer.py lo impute correctamente.
  [FIX3] groupby("category") ahora usa dropna=False y selecciona la
         columna antes de .apply(), eliminando el DeprecationWarning
         y el desalineamiento de índices que descartaba filas.
  [FIX4] Estacionariedad ahora ordena por price_date real (datetime),
         no por string.
  [FIX5] Conversión explícita a bool/float nativos de Python antes
         de json.dump() — numpy.bool_/float64 no son serializables.

CAMBIOS v1.3 (sobre v1.2):
  [FIX6] sku == NaN ya NO colapsa filas en drop_duplicates(). Mismo
         problema que [FIX1] pero para sku: pandas trata NaN == NaN
         como igual, lo que colapsaba miles de productos DISTINTOS
         de falabella/hiraoka (benchmark, sin sku real) en 1 sola
         fila. Se genera un fingerprint sintético (title + price_pen)
         SOLO para la comparación de deduplicación; el sku real
         (incluyendo NaN) se preserva sin modificar en el dataset
         final.

[Q1-Q3 de v1.1 se mantienen sin cambios]

Uso:
    python preprocessing/data_quality.py \
        --input data/raw/MASTER_hardware_peru.csv \
        --contract preprocessing/data_contract.yaml \
        --output data/processed/MASTER_hardware_peru_clean.csv
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import numpy as np
import yaml

try:
    from statsmodels.tsa.stattools import adfuller, kpss
    _HAS_STATSMODELS = True
except ImportError:
    _HAS_STATSMODELS = False


# ══════════════════════════════════════════════════════════════════
# CARGA DEL CONTRATO
# ══════════════════════════════════════════════════════════════════
def load_contract(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        contract = yaml.safe_load(f)
    return contract


def get_required_columns(contract: dict) -> list:
    cols = []
    for group, items in contract.get("columnas_obligatorias", {}).items():
        for item in items:
            if item and item != "null":
                cols.append(item)
    return cols


# ══════════════════════════════════════════════════════════════════
# [Q2] VALIDACIÓN FAIL-FAST DE ESQUEMA
# ══════════════════════════════════════════════════════════════════
def validate_schema(df: pd.DataFrame, contract: dict) -> list:
    required = get_required_columns(contract)
    missing = [c for c in required if c not in df.columns]
    return missing


# ══════════════════════════════════════════════════════════════════
# AUDITORÍA DE COMPLETITUD
# ══════════════════════════════════════════════════════════════════
def audit_completeness(df: pd.DataFrame, contract: dict) -> dict:
    required = get_required_columns(contract)
    result = {}
    for col in required:
        if col in df.columns:
            non_null = df[col].notna().sum()
            pct = round(float(non_null) / len(df) * 100, 2) if len(df) else 0.0
            result[col] = float(pct)
    overall = round(float(np.mean(list(result.values()))), 2) if result else 0.0
    result["_overall_pct"] = overall
    return result


# ══════════════════════════════════════════════════════════════════
# [FIX1] SEPARAR FILAS SIN price_date ANTES DE DEDUPLICAR
# ══════════════════════════════════════════════════════════════════
def split_missing_date(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Separa filas sin price_date válido. Estas NO deben entrar al
    drop_duplicates() normal, porque NaN == NaN colapsaría filas
    que en realidad son observaciones distintas sin fecha registrada.
    """
    if "price_date" not in df.columns:
        return df, 0

    before = len(df)
    mask_has_date = df["price_date"].notna()
    removed = before - int(mask_has_date.sum())

    if removed > 0:
        print(f"  🔍 Filas sin price_date removidas: {removed:,} "
              f"({removed/before*100:.2f}%) — no se pueden ubicar en la serie temporal")

    return df[mask_has_date].copy(), removed


# ══════════════════════════════════════════════════════════════════
# [FIX6] CLAVE DE DEDUP PARA sku — evita colapso por NaN
# ══════════════════════════════════════════════════════════════════
def _dedup_sku_series(df: pd.DataFrame) -> pd.Series:
    """
    Construye una versión de 'sku' segura para deduplicación.

    Problema: pandas.drop_duplicates() trata NaN == NaN como igual.
    Fuentes como falabella_benchmark/hiraoka_benchmark no capturan
    sku real, por lo que TODOS sus productos comparten sku == NaN.
    Sin este fix, drop_duplicates() colapsa cientos/miles de
    productos DISTINTOS (títulos y precios diferentes) en 1 sola
    fila por (source, price_date), destruyendo datos reales.

    Solución: cuando sku está vacío, se genera un fingerprint
    sintético 'fp_<md5>' a partir de title + price_pen, ÚNICAMENTE
    para esta comparación. El sku real del DataFrame NO se modifica.
    """
    if "sku" not in df.columns:
        return pd.Series([""] * len(df), index=df.index)

    sku = df["sku"].astype(str)
    mask_missing = df["sku"].isna() | (sku.str.strip() == "") | (sku == "nan")

    if mask_missing.any():
        title = df.get("title", pd.Series("", index=df.index)).astype(str)
        price = df.get("price_pen", pd.Series("", index=df.index)).astype(str)
        raw = title + "_" + price
        fp = raw.apply(lambda x: "fp_" + hashlib.md5(x.encode("utf-8")).hexdigest()[:12])
        sku = sku.where(~mask_missing, fp)

    return sku


# ══════════════════════════════════════════════════════════════════
# DEDUPLICACIÓN según clave del contrato
# ══════════════════════════════════════════════════════════════════
def deduplicate(df: pd.DataFrame, contract: dict) -> pd.DataFrame:
    rules = contract.get("reglas_de_validacion", {})
    if rules.get("duplicados_permitidos", False):
        return df

    key_cols = [c for c in ["source", "sku", "price_date"] if c in df.columns]
    if not key_cols:
        return df

    before = len(df)

    # [FIX6] Clave temporal con fingerprint — evita colapso por sku NaN.
    # El sku real (incluyendo sus NaN) se preserva intacto en df.
    df = df.copy()
    df["_dedup_sku"] = _dedup_sku_series(df)
    key_cols_fixed = ["_dedup_sku" if c == "sku" else c for c in key_cols]

    df_dedup = df.drop_duplicates(subset=key_cols_fixed, keep="last")
    df_dedup = df_dedup.drop(columns=["_dedup_sku"])

    removed = before - len(df_dedup)
    print(f"  🔍 Duplicados reales removidos: {removed:,} (clave: {key_cols})")
    return df_dedup


# ══════════════════════════════════════════════════════════════════
# [FIX2 + FIX3] DETECCIÓN DE OUTLIERS — preserva NaN para MICE
# ══════════════════════════════════════════════════════════════════
def detect_price_outliers(df: pd.DataFrame, contract: dict) -> pd.DataFrame:
    rules = contract.get("reglas_de_validacion", {})
    rango = rules.get("precio_usd_rango_valido", [1.0, 5000.0])

    if "price_usd" not in df.columns:
        return df

    before = len(df)

    # [FIX2] NaN se preserva (no se marca fuera de rango).
    mask_rango = df["price_usd"].between(rango[0], rango[1]) | df["price_usd"].isna()

    # [FIX3] IQR k=3.0 por categoría, respetando NaN en price_usd y category
    def _iqr_mask(s: pd.Series) -> pd.Series:
        valid = s.dropna()
        if len(valid) < 4:
            return pd.Series(True, index=s.index)
        q1, q3 = valid.quantile([0.25, 0.75])
        iqr = q3 - q1
        if iqr == 0:
            return pd.Series(True, index=s.index)
        lo, hi = q1 - 3.0 * iqr, q3 + 3.0 * iqr
        return s.between(lo, hi) | s.isna()

    if "category" in df.columns:
        mask_iqr = (
            df.groupby("category", dropna=False)["price_usd"]
            .apply(_iqr_mask)
            .reset_index(level=0, drop=True)
            .reindex(df.index)
        )
    else:
        mask_iqr = pd.Series(True, index=df.index)

    final_mask = mask_rango & mask_iqr
    df_clean = df[final_mask].copy()

    removed = before - len(df_clean)
    preserved_nan = int(df["price_usd"].isna().sum())
    print(f"  🔍 Outliers reales removidos: {removed:,} ({removed/before*100:.2f}%)")
    print(f"  ℹ️  price_usd faltantes preservados para MICE: {preserved_nan:,}")
    return df_clean


# ══════════════════════════════════════════════════════════════════
# [FIX4] PRUEBAS DE ESTACIONARIEDAD — ordenadas por fecha real
# ══════════════════════════════════════════════════════════════════
def stationarity_tests(df: pd.DataFrame) -> dict:
    if not _HAS_STATSMODELS or "price_usd" not in df.columns or "price_date" not in df.columns:
        return {"adf_pvalue": None, "kpss_pvalue": None, "status": "omitido"}

    try:
        df_tmp = df.copy()
        df_tmp["price_date"] = pd.to_datetime(df_tmp["price_date"], errors="coerce")
        df_tmp = df_tmp.dropna(subset=["price_date"])

        serie = (
            df_tmp.sort_values("price_date")
            .groupby("price_date")["price_usd"]
            .mean()
            .dropna()
        )

        if len(serie) < 20:
            return {"adf_pvalue": None, "kpss_pvalue": None, "status": "insuficiente"}

        adf_result  = adfuller(serie, autolag="AIC")
        kpss_result = kpss(serie, regression="c", nlags="auto")

        # [FIX5] cast explícito a tipos nativos de Python
        return {
            "adf_pvalue":  round(float(adf_result[1]), 4),
            "kpss_pvalue": round(float(kpss_result[1]), 4),
            "adf_estacionaria":  bool(adf_result[1] < 0.05),
            "kpss_estacionaria": bool(kpss_result[1] > 0.05),
            "status": "ok",
        }
    except Exception as e:
        return {"adf_pvalue": None, "kpss_pvalue": None, "status": f"error: {e}"}


# ══════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ══════════════════════════════════════════════════════════════════
def run_quality_pipeline(input_path: Path, contract_path: Path, output_path: Path):
    print("═" * 60)
    print("  DATA QUALITY v1.3 — Certificación Hito H1")
    print("═" * 60)

    contract = load_contract(contract_path)
    print(f"\n📄 Contrato cargado: {contract_path.name} (v{contract.get('version')})")

    df = pd.read_csv(input_path, low_memory=False)
    n_original = len(df)
    print(f"📊 MASTER cargado: {n_original:,} registros, {len(df.columns)} columnas")

    missing = validate_schema(df, contract)
    if missing:
        print(f"\n❌ FATAL: Columnas obligatorias faltantes: {missing}")
        print("   El dataset NO cumple el contrato. Abortando (Etapa II bloqueada).")
        sys.exit(1)
    print("✅ Esquema validado — todas las columnas obligatorias presentes")

    completeness = audit_completeness(df, contract)
    min_required = float(contract["reglas_de_validacion"]["completitud_minima_pct"])
    print(f"\n📈 Completitud general: {completeness['_overall_pct']}% "
          f"(mínimo requerido: {min_required}%)")
    for col, pct in completeness.items():
        if col != "_overall_pct" and pct < min_required:
            print(f"   ⚠️  {col}: {pct}% (por debajo del mínimo)")

    print("\n🧹 Limpieza de datos...")
    df, n_sin_fecha = split_missing_date(df)
    df = deduplicate(df, contract)
    df = detect_price_outliers(df, contract)

    print("\n📉 Pruebas de estacionariedad...")
    stationarity = stationarity_tests(df)
    if stationarity["status"] == "ok":
        print(f"   ADF p-valor:  {stationarity['adf_pvalue']} "
              f"({'✅ estacionaria' if stationarity['adf_estacionaria'] else '⚠️ no estacionaria'})")
        print(f"   KPSS p-valor: {stationarity['kpss_pvalue']} "
              f"({'✅ estacionaria' if stationarity['kpss_estacionaria'] else '⚠️ no estacionaria'})")
    else:
        print(f"   ⚠️ Pruebas omitidas: {stationarity['status']}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"\n💾 Dataset limpio guardado: {output_path} ({len(df):,} registros)")

    # [FIX5] hito_H1_cumplido como bool nativo
    hito_cumplido = bool(completeness["_overall_pct"] >= min_required)

    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report = {
        "batch_id": batch_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "registros_originales": int(n_original),
        "registros_sin_fecha_removidos": int(n_sin_fecha),
        "registros_finales": int(len(df)),
        "pct_retenido": round(float(len(df)) / n_original * 100, 2) if n_original else 0.0,
        "completitud": completeness,
        "estacionariedad": stationarity,
        "hito_H1_cumplido": hito_cumplido,
    }
    report_path = output_path.parent / f"quality_report_{batch_id}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"📋 Reporte de calidad: {report_path.name}")

    print("\n" + "═" * 60)
    print(f"  📦 Retención final: {report['pct_retenido']}% del MASTER original")
    if report["hito_H1_cumplido"]:
        print("  ✅ HITO H1 CUMPLIDO — Dataset certificado para Etapa II")
    else:
        print("  ⚠️  HITO H1 NO CUMPLIDO — completitud insuficiente")
    print("═" * 60)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Certificación de calidad del MASTER (Hito H1)")
    parser.add_argument("--input", required=True, help="Ruta al MASTER_hardware_peru.csv")
    parser.add_argument("--contract", default="preprocessing/data_contract.yaml")
    parser.add_argument("--output", required=True, help="Ruta de salida del dataset limpio")
    args = parser.parse_args()

    run_quality_pipeline(Path(args.input), Path(args.contract), Path(args.output))
