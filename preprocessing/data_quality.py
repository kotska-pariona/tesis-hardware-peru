#!/usr/bin/env python3
"""
data_quality.py v1.1
═══════════════════════════════════════════════════════════════════
Certifica el MASTER_hardware_peru.csv contra preprocessing/data_contract.yaml
ANTES de que llegue a feature_engineering.py (Etapa II).

CAMBIOS v1.1 (sobre v1.0):
  [Q1] Validación dirigida por data_contract.yaml — antes las reglas
       (completitud, rangos, duplicados) estaban hardcodeadas y podían
       desincronizarse silenciosamente del contrato real.
  [Q2] Fail-fast explícito: si columnas_obligatorias faltan, el script
       termina con exit(1) y NO genera el CSV limpio — evita que
       feature_engineering.py falle más adelante con errores confusos.
  [Q3] Reporte JSON de auditoría (data/raw/quality_report_<batch>.json)
       para trazabilidad del Hito H1 (completitud ≥95%, ADF/KPSS).

Uso:
    python preprocessing/data_quality.py \
        --input data/raw/MASTER_hardware_peru.csv \
        --contract preprocessing/data_contract.yaml \
        --output data/raw/MASTER_hardware_peru_clean.csv
"""

import argparse
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
            pct = round(non_null / len(df) * 100, 2) if len(df) else 0.0
            result[col] = pct
    overall = round(np.mean(list(result.values())), 2) if result else 0.0
    result["_overall_pct"] = overall
    return result


# ══════════════════════════════════════════════════════════════════
# DETECCIÓN DE OUTLIERS — IQR k=3.0 (rangos válidos del contrato)
# ══════════════════════════════════════════════════════════════════
def detect_price_outliers(df: pd.DataFrame, contract: dict) -> pd.DataFrame:
    rules = contract.get("reglas_de_validacion", {})
    rango = rules.get("precio_usd_rango_valido", [1.0, 5000.0])

    if "price_usd" not in df.columns:
        return df

    before = len(df)
    mask_rango = df["price_usd"].between(rango[0], rango[1])

    # IQR k=3.0 adicional, por categoría (evita comparar GPU con RAM)
    def _iqr_mask(group):
        q1, q3 = group["price_usd"].quantile([0.25, 0.75])
        iqr = q3 - q1
        lo, hi = q1 - 3.0 * iqr, q3 + 3.0 * iqr
        return group["price_usd"].between(lo, hi)

    if "category" in df.columns:
        mask_iqr = df.groupby("category", group_keys=False).apply(_iqr_mask)
    else:
        mask_iqr = pd.Series(True, index=df.index)

    df_clean = df[mask_rango & mask_iqr].copy()
    removed = before - len(df_clean)
    print(f"  🔍 Outliers removidos: {removed:,} ({removed/before*100:.2f}%)")
    return df_clean


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
    df_dedup = df.drop_duplicates(subset=key_cols, keep="last")
    removed = before - len(df_dedup)
    print(f"  🔍 Duplicados removidos: {removed:,} (clave: {key_cols})")
    return df_dedup


# ══════════════════════════════════════════════════════════════════
# PRUEBAS DE ESTACIONARIEDAD (ADF / KPSS) — sobre serie agregada
# ══════════════════════════════════════════════════════════════════
def stationarity_tests(df: pd.DataFrame) -> dict:
    if not _HAS_STATSMODELS or "price_usd" not in df.columns:
        return {"adf_pvalue": None, "kpss_pvalue": None, "status": "omitido"}

    try:
        serie = df.groupby("price_date")["price_usd"].mean().dropna()
        if len(serie) < 20:
            return {"adf_pvalue": None, "kpss_pvalue": None, "status": "insuficiente"}

        adf_result  = adfuller(serie, autolag="AIC")
        kpss_result = kpss(serie, regression="c", nlags="auto")

        return {
            "adf_pvalue":  round(adf_result[1], 4),
            "kpss_pvalue": round(kpss_result[1], 4),
            "adf_estacionaria":  adf_result[1] < 0.05,   # H0: no estacionaria
            "kpss_estacionaria": kpss_result[1] > 0.05,  # H0: estacionaria
            "status": "ok",
        }
    except Exception as e:
        return {"adf_pvalue": None, "kpss_pvalue": None, "status": f"error: {e}"}


# ══════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ══════════════════════════════════════════════════════════════════
def run_quality_pipeline(input_path: Path, contract_path: Path, output_path: Path):
    print("═" * 60)
    print("  DATA QUALITY v1.1 — Certificación Hito H1")
    print("═" * 60)

    contract = load_contract(contract_path)
    print(f"\n📄 Contrato cargado: {contract_path.name} (v{contract.get('version')})")

    df = pd.read_csv(input_path, low_memory=False)
    print(f"📊 MASTER cargado: {len(df):,} registros, {len(df.columns)} columnas")

    # [Q2] Fail-fast: columnas obligatorias
    missing = validate_schema(df, contract)
    if missing:
        print(f"\n❌ FATAL: Columnas obligatorias faltantes: {missing}")
        print("   El dataset NO cumple el contrato. Abortando (Etapa II bloqueada).")
        sys.exit(1)
    print("✅ Esquema validado — todas las columnas obligatorias presentes")

    # Completitud
    completeness = audit_completeness(df, contract)
    min_required = contract["reglas_de_validacion"]["completitud_minima_pct"]
    print(f"\n📈 Completitud general: {completeness['_overall_pct']}% "
          f"(mínimo requerido: {min_required}%)")
    for col, pct in completeness.items():
        if col != "_overall_pct" and pct < min_required:
            print(f"   ⚠️  {col}: {pct}% (por debajo del mínimo)")

    # Limpieza
    print("\n🧹 Limpieza de datos...")
    df = deduplicate(df, contract)
    df = detect_price_outliers(df, contract)

    # Estacionariedad
    print("\n📉 Pruebas de estacionariedad...")
    stationarity = stationarity_tests(df)
    if stationarity["status"] == "ok":
        print(f"   ADF p-valor:  {stationarity['adf_pvalue']} "
              f"({'✅ estacionaria' if stationarity['adf_estacionaria'] else '⚠️ no estacionaria'})")
        print(f"   KPSS p-valor: {stationarity['kpss_pvalue']} "
              f"({'✅ estacionaria' if stationarity['kpss_estacionaria'] else '⚠️ no estacionaria'})")
    else:
        print(f"   ⚠️ Pruebas omitidas: {stationarity['status']}")

    # Guardar dataset limpio
    df.to_csv(output_path, index=False)
    print(f"\n💾 Dataset limpio guardado: {output_path} ({len(df):,} registros)")

    # [Q3] Reporte de auditoría
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report = {
        "batch_id": batch_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "registros_originales": int(len(pd.read_csv(input_path, low_memory=False))),
        "registros_finales": int(len(df)),
        "completitud": completeness,
        "estacionariedad": stationarity,
        "hito_H1_cumplido": completeness["_overall_pct"] >= min_required,
    }
    report_path = output_path.parent / f"quality_report_{batch_id}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"📋 Reporte de calidad: {report_path.name}")

    print("\n" + "═" * 60)
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
