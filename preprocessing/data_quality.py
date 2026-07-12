#!/usr/bin/env python3
"""
data_quality.py v1.2
═══════════════════════════════════════════════════════════════════
Certifica el MASTER_hardware_peru.csv contra preprocessing/data_contract.yaml
ANTES de que llegue a feature_engineering.py (Etapa II).

CAMBIOS v1.2 (sobre v1.1):
  [Q4] FIX CRÍTICO deduplicate(): la clave (source, sku, price_date)
       colapsaba TODOS los registros sin SKU del mismo source/día en
       una sola fila, porque sku="" es idéntico para todos ellos.
       Ahora se replica el fingerprint MD5 (título+precio) que ya usa
       main.py para productos sin SKU, evitando pérdida masiva de
       datos de fuentes que no parsean SKU de forma consistente
       (eBay, algunos listados de Newegg/PCPartPicker/locales).
  [Q5] FIX CRÍTICO detect_price_outliers(): dropna=False en el
       groupby("category") — evita ValueError/comportamiento indefinido
       cuando existen filas con category=NaN. Además se separa el
       conteo de "sin price_usd" del conteo de "outlier por rango/IQR"
       para trazabilidad correcta en el reporte de auditoría (antes
       se reportaban juntos bajo un solo número de "outliers").
  [Q6] stationarity_tests(): price_date se parsea explícitamente con
       pd.to_datetime() y la serie se ordena por fecha antes de correr
       ADF/KPSS — evita resultados inválidos si las fuentes no usan
       un formato de fecha 100% consistente.
  [Q7] Guardas contra división por cero cuando el dataset queda vacío
       tras la deduplicación (before == 0).

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
            pct = round(non_null / len(df) * 100, 2) if len(df) else 0.0
            result[col] = pct
    overall = round(np.mean(list(result.values())), 2) if result else 0.0
    result["_overall_pct"] = overall
    return result


# ══════════════════════════════════════════════════════════════════
# DETECCIÓN DE OUTLIERS — IQR k=3.0 (rangos válidos del contrato)
# ══════════════════════════════════════════════════════════════════
def detect_price_outliers(df: pd.DataFrame, contract: dict) -> pd.DataFrame:
    """
    [Q5] dropna=False en el groupby de categoría + separación de
    conteos: "sin price_usd" vs "fuera de rango" vs "outlier IQR".
    """
    rules = contract.get("reglas_de_validacion", {})
    rango = rules.get("precio_usd_rango_valido", [1.0, 5000.0])

    if "price_usd" not in df.columns:
        return df

    before = len(df)
    if before == 0:
        return df

    has_price  = df["price_usd"].notna()
    en_rango   = df["price_usd"].between(rango[0], rango[1])
    mask_rango = has_price & en_rango

    def _iqr_mask(group):
        q1, q3 = group["price_usd"].quantile([0.25, 0.75])
        iqr = q3 - q1
        lo, hi = q1 - 3.0 * iqr, q3 + 3.0 * iqr
        return group["price_usd"].between(lo, hi)

    if "category" in df.columns:
        # [Q5] dropna=False — evita descartar filas con category=NaN
        mask_iqr = df.groupby(
            "category", group_keys=False, dropna=False
        ).apply(_iqr_mask)
        mask_iqr = mask_iqr.reindex(df.index, fill_value=False)
    else:
        mask_iqr = pd.Series(True, index=df.index)

    df_clean = df[mask_rango & mask_iqr.fillna(False)].copy()

    # [Q5] Desglose de causas para trazabilidad del Hito H1
    sin_precio     = int((~has_price).sum())
    fuera_de_rango = int((has_price & ~en_rango).sum())
    removed_total  = before - len(df_clean)
    removed_iqr    = max(removed_total - sin_precio - fuera_de_rango, 0)

    print(f"  🔍 Removidos por falta de price_usd : {sin_precio:,}")
    print(f"  🔍 Removidos por rango inválido      : {fuera_de_rango:,}")
    print(f"  🔍 Removidos por outlier IQR (k=3)   : {removed_iqr:,}")
    print(f"  🔍 Total outliers/inválidos removidos: {removed_total:,} "
          f"({removed_total/before*100:.2f}%)")
    return df_clean


# ══════════════════════════════════════════════════════════════════
# DEDUPLICACIÓN según clave del contrato
# ══════════════════════════════════════════════════════════════════
def deduplicate(df: pd.DataFrame, contract: dict) -> pd.DataFrame:
    """
    [Q4] FIX CRÍTICO: cuando sku está vacío, se genera un fingerprint
    MD5 (título+precio) IGUAL que main.py, para no colapsar productos
    distintos sin SKU del mismo source/día en una sola fila.
    """
    rules = contract.get("reglas_de_validacion", {})
    if rules.get("duplicados_permitidos", False):
        return df

    if not all(c in df.columns for c in ["source", "price_date"]):
        return df

    before = len(df)
    if before == 0:
        return df

    def _effective_sku(row) -> str:
        sku = str(row.get("sku", "") or "").strip()
        if sku:
            return sku
        title = str(row.get("title", row.get("name", "")) or "")[:80]
        price = str(row.get("price_usd") or row.get("price_pen") or "")
        return "fp_" + hashlib.md5(f"{title}|{price}".encode()).hexdigest()[:12]

    df = df.copy()
    df["_dedup_sku"] = df.apply(_effective_sku, axis=1)
    key_cols = [c for c in ["source", "_dedup_sku", "price_date"] if c in df.columns]

    df_dedup = df.drop_duplicates(subset=key_cols, keep="last")
    df_dedup = df_dedup.drop(columns=["_dedup_sku"])

    removed = before - len(df_dedup)
    print(f"  🔍 Duplicados removidos: {removed:,} "
          f"(clave: source + sku/fingerprint + price_date)")
    return df_dedup


# ══════════════════════════════════════════════════════════════════
# PRUEBAS DE ESTACIONARIEDAD (ADF / KPSS) — sobre serie agregada
# ══════════════════════════════════════════════════════════════════
def stationarity_tests(df: pd.DataFrame) -> dict:
    """
    [Q6] price_date se parsea con pd.to_datetime() y la serie se
    ordena por fecha antes de ADF/KPSS — evita resultados inválidos
    si las fuentes no comparten el mismo formato de fecha.
    """
    if not _HAS_STATSMODELS or "price_usd" not in df.columns:
        return {"adf_pvalue": None, "kpss_pvalue": None, "status": "omitido"}

    try:
        fechas = pd.to_datetime(df["price_date"], errors="coerce")
        tmp = pd.DataFrame(
            {"_dt": fechas, "price_usd": df["price_usd"]}
        ).dropna()
        serie = tmp.groupby("_dt")["price_usd"].mean().sort_index()

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
    print("  DATA QUALITY v1.2 — Certificación Hito H1")
    print("═" * 60)

    contract = load_contract(contract_path)
    print(f"\n📄 Contrato cargado: {contract_path.name} (v{contract.get('version')})")

    df = pd.read_csv(input_path, low_memory=False)
    registros_originales = len(df)
    print(f"📊 MASTER cargado: {registros_originales:,} registros, {len(df.columns)} columnas")

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
        print(f"   ADF p-valor:  {
