#!/usr/bin/env python3
"""
mice_imputer.py v1.2
═══════════════════════════════════════════════════════════════════
Etapa II del pipeline (Sección 4.7.2 del plan de tesis).

ANTI-LEAKAGE (Kapoor & Narayanan, 2023):
  - fit() EXCLUSIVAMENTE sobre train.csv
  - transform() sobre val/test sin re-ajuste

CAMBIOS v1.2 (FIX-24):
  [B6] classify_columns() excluye columnas con missingness >= MAX_MISSING_PCT
       (default 95%) de MICE. Imputar columnas casi completamente vacías
       produce ruido, no información. Se registran en 'high_missing'.
  [B7] impute_categorical() convierte la columna a dtype object ANTES de
       asignar el placeholder "unknown", evitando FutureWarning de pandas
       cuando la columna fue leída como float64 (todo-NaN en CSV).
  [B8] run_mice_pipeline() incluye 'high_missing_excluded' en el reporte
       JSON y lo imprime en consola para trazabilidad completa.
  [B9] Columnas en BINARY_COLUMNS que lleguen como string "True"/"False"
       o "0"/"1" se convierten a int ANTES de classify_columns(), para
       que is_numeric_dtype() las detecte correctamente como binarias.
"""

import argparse
import json
import pickle
import sys
import warnings
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from sklearn.experimental import enable_iterative_imputer  # noqa: F401
from sklearn.impute import IterativeImputer
from sklearn.linear_model import BayesianRidge


# ══════════════════════════════════════════════════════════════════
# CONSTANTES
# ══════════════════════════════════════════════════════════════════

ID_COLUMNS = {
    "batch_id", "timestamp", "source", "sku", "url",
    "price_date", "seller_nickname", "part_id", "retailer",
    "title", "condition", "price_currency",
}

BINARY_COLUMNS = {
    "free_shipping", "is_official_store", "is_best_seller",
    "is_good_seller",
}

CATEGORICAL_COLUMNS = {"brand", "category", "category_label"}

# Umbral: columnas con >= este % de NaN se excluyen de MICE [B6]
MAX_MISSING_PCT = 0.95


# ══════════════════════════════════════════════════════════════════
# NORMALIZACIÓN PREVIA — [B9]
# ══════════════════════════════════════════════════════════════════

def normalize_binary_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    [B9-FIX] Convierte columnas de BINARY_COLUMNS que lleguen como
    string ("True"/"False", "1"/"0", "yes"/"no") a int {0, 1}.
    Solo actúa sobre columnas presentes en el DataFrame.
    Columnas ya numéricas se dejan intactas.
    """
    df = df.copy()
    for col in BINARY_COLUMNS:
        if col not in df.columns:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            # Ya es numérica — solo asegurar que no haya floats intermedios
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            # Es string — mapear a int
            mapping = {
                "true": 1, "false": 0,
                "yes": 1,  "no": 0,
                "1": 1,    "0": 0,
                "1.0": 1,  "0.0": 0,
            }
            df[col] = (
                df[col].astype(str).str.strip().str.lower()
                .map(mapping)
            )
            # Valores no reconocidos → NaN (MICE los imputará)
    return df


# ══════════════════════════════════════════════════════════════════
# CLASIFICACIÓN DE COLUMNAS — [M1] [M2] [M3] [B6]
# ══════════════════════════════════════════════════════════════════

def classify_columns(df: pd.DataFrame,
                     max_missing_pct: float = MAX_MISSING_PCT) -> dict:
    """
    Clasifica columnas usando dtype REAL del DataFrame post-normalización.

    [B1] Usa pd.api.types.is_numeric_dtype() por columna — strings nunca
         entran a mice_cols.
    [B6] Excluye de MICE columnas con missingness >= max_missing_pct.
         Imputar columnas casi completamente vacías produce ruido puro.
    """
    all_cols = set(df.columns)

    truly_numeric = {
        c for c in df.columns
        if pd.api.types.is_numeric_dtype(df[c])
    }

    identifiers        = ID_COLUMNS & all_cols
    categorical        = CATEGORICAL_COLUMNS & all_cols
    numeric_binary     = BINARY_COLUMNS & truly_numeric
    numeric_continuous = truly_numeric - numeric_binary - identifiers - categorical

    # Columnas no clasificadas
    classified   = identifiers | categorical | numeric_continuous | numeric_binary
    unclassified = all_cols - classified

    non_numeric_unclassified = unclassified - truly_numeric
    numeric_unclassified     = unclassified & truly_numeric

    if non_numeric_unclassified:
        print(f"   ⚠️  No numéricas sin clasificar → identifiers: "
              f"{sorted(non_numeric_unclassified)}")
    if numeric_unclassified:
        print(f"   ℹ️  Numéricas sin clasificar → numeric_continuous: "
              f"{sorted(numeric_unclassified)}")
        numeric_continuous = numeric_continuous | numeric_unclassified

    identifiers = identifiers | non_numeric_unclassified

    # [B6-FIX] Excluir columnas con alta missingness de MICE
    candidates = numeric_continuous | numeric_binary
    high_missing = {
        c for c in candidates
        if df[c].isna().mean() >= max_missing_pct
    }
    if high_missing:
        print(f"   ⚠️  Columnas ≥{max_missing_pct*100:.0f}% NaN → "
              f"excluidas de MICE (se dejan como NaN): {sorted(high_missing)}")
        numeric_continuous = numeric_continuous - high_missing
        numeric_binary     = numeric_binary - high_missing

    return {
        "numeric_continuous": sorted(numeric_continuous),
        "numeric_binary":     sorted(numeric_binary),
        "categorical":        sorted(categorical),
        "identifiers":        sorted(identifiers),
        "high_missing":       sorted(high_missing),   # [B8] trazabilidad
    }


# ══════════════════════════════════════════════════════════════════
# WRAPPER DE MICE
# ══════════════════════════════════════════════════════════════════

class MiceImputer:

    def __init__(self, max_iter: int = 10, random_state: int = 42):
        self.max_iter       = max_iter
        self.random_state   = random_state
        self.imputer_       = None
        self.numeric_continuous_cols_ = None
        self.numeric_binary_cols_     = None
        self.mice_cols_     = None
        self.fitted_        = False

    # ── fit: SOLO sobre train ──────────────────────────────────
    def fit(self, df_train: pd.DataFrame, columns: dict):
        self.numeric_continuous_cols_ = columns["numeric_continuous"]
        self.numeric_binary_cols_     = columns["numeric_binary"]
        mice_cols = self.numeric_continuous_cols_ + self.numeric_binary_cols_

        if not mice_cols:
            warnings.warn("No hay columnas numéricas para imputar con MICE.")
            self.mice_cols_ = []
            self.fitted_    = True
            return self

        # [B5] Validar dtypes en train
        non_numeric = [
            c for c in mice_cols
            if not pd.api.types.is_numeric_dtype(df_train[c])
        ]
        if non_numeric:
            raise ValueError(
                f"[fit] Columnas no numéricas en mice_cols "
                f"(revisar classify_columns): {non_numeric}"
            )

        self.mice_cols_ = mice_cols

        self.imputer_ = IterativeImputer(
            estimator=BayesianRidge(),
            max_iter=self.max_iter,
            random_state=self.random_state,
            sample_posterior=False,
        )

        # [B2] Forzar float64
        X_train = (df_train[mice_cols]
                   .apply(pd.to_numeric, errors="coerce")
                   .astype(float))
        self.imputer_.fit(X_train)
        self.fitted_ = True
        return self

    # ── transform: train / val / test ─────────────────────────
    def transform(self, df: pd.DataFrame, split_name: str = "") -> tuple:
        if not self.fitted_:
            raise RuntimeError("Llamar fit() antes de transform()")

        df        = df.copy()
        mice_cols = self.mice_cols_
        stats     = {}

        if not mice_cols:
            return df, stats

        # [M5] Fail-fast
        missing_cols = [c for c in mice_cols if c not in df.columns]
        if missing_cols:
            raise ValueError(
                f"[{split_name}] Columnas ausentes respecto a train: "
                f"{missing_cols}"
            )

        # [B2] Forzar float64
        X_in = (df[mice_cols]
                .apply(pd.to_numeric, errors="coerce")
                .astype(float))

        # [M4] Flags _was_missing_ ANTES de imputar
        for col in mice_cols:
            mask = X_in[col].isna()
            if mask.any():
                df[f"_was_missing_{col}"] = mask.astype(int)
                stats[col] = round(mask.mean() * 100, 2)

        X_out = self.imputer_.transform(X_in)

        # [B3] Reconstrucción robusta para columnas all-NaN saltadas por sklearn
        if X_out.shape[1] == len(mice_cols):
            df[mice_cols] = X_out
        else:
            try:
                stats_arr  = self.imputer_.initial_imputer_.statistics_
                valid_cols = [
                    col for col, stat in zip(mice_cols, stats_arr)
                    if not (isinstance(stat, float) and np.isnan(stat))
                ]
                if len(valid_cols) == X_out.shape[1]:
                    df[valid_cols] = X_out
                else:
                    df[mice_cols[:X_out.shape[1]]] = X_out
                    warnings.warn(
                        f"[{split_name}] Fallback posicional en "
                        f"reconstrucción all-NaN."
                    )
            except AttributeError:
                df[mice_cols[:X_out.shape[1]]] = X_out
                warnings.warn(
                    f"[{split_name}] initial_imputer_ no disponible — "
                    f"fallback posicional."
                )

        # [M2] Binarias: clip a {0,1}
        for col in self.numeric_binary_cols_:
            if col in df.columns:
                df[col] = df[col].fillna(0).round().clip(0, 1).astype(int)

        return df, stats

    def save(self, path: Path):
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: Path) -> "MiceImputer":
        with open(path, "rb") as f:
            return pickle.load(f)


# ══════════════════════════════════════════════════════════════════
# IMPUTACIÓN DE CATEGÓRICAS — [M3] [B7]
# ══════════════════════════════════════════════════════════════════

def impute_categorical(df: pd.DataFrame, categorical_cols: list) -> tuple:
    """
    [B7-FIX] Convierte la columna a dtype object ANTES de asignar
    "unknown". Evita FutureWarning cuando pandas leyó la columna
    como float64 (porque estaba completamente vacía en el CSV).
    """
    df    = df.copy()
    stats = {}
    for col in categorical_cols:
        if col not in df.columns:
            continue
        # [B7-FIX] Forzar object dtype
        if df[col].dtype != object:
            df[col] = df[col].astype(object)
        missing_mask = df[col].isna() | (df[col].astype(str).str.strip() == "")
        if missing_mask.any():
            df[f"_was_missing_{col}"] = missing_mask.astype(int)
            df.loc[missing_mask, col] = "unknown"
            stats[col] = round(missing_mask.mean() * 100, 2)
    return df, stats


# ══════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ══════════════════════════════════════════════════════════════════

def run_mice_pipeline(input_dir: Path, output_dir: Path, max_iter: int = 10):
    output_dir.mkdir(parents=True, exist_ok=True)

    print("═" * 60)
    print("  MICE IMPUTER v1.2 — Etapa II")
    print("═" * 60)

    train = pd.read_csv(input_dir / "train.csv", low_memory=False)
    val   = pd.read_csv(input_dir / "val.csv",   low_memory=False)
    test  = pd.read_csv(input_dir / "test.csv",  low_memory=False)

    print(f"\n📊 Splits cargados: "
          f"train={len(train):,} | val={len(val):,} | test={len(test):,}")

    # [B9] Normalizar binarias antes de clasificar
    train = normalize_binary_columns(train)
    val   = normalize_binary_columns(val)
    test  = normalize_binary_columns(test)

    # Clasificación basada en train
    columns = classify_columns(train)
    print(f"\n🔎 Clasificación de columnas:")
    print(f"   Numéricas continuas (MICE) : "
          f"{len(columns['numeric_continuous'])} → "
          f"{columns['numeric_continuous']}")
    print(f"   Numéricas binarias  (MICE) : "
          f"{len(columns['numeric_binary'])} → "
          f"{columns['numeric_binary']}")
    print(f"   Categóricas (placeholder)  : "
          f"{len(columns['categorical'])} → "
          f"{columns['categorical']}")
    print(f"   Identificadores (sin tocar): "
          f"{len(columns['identifiers'])}")
    # [B8] Reportar excluidas por alta missingness
    if columns["high_missing"]:
        print(f"   🚫 Excluidas por alta missingness (≥{MAX_MISSING_PCT*100:.0f}%): "
              f"{len(columns['high_missing'])} → "
              f"{columns['high_missing']}")

    # [M5] Fail-fast
    mice_cols = columns["numeric_continuous"] + columns["numeric_binary"]
    for name, split_df in [("val", val), ("test", test)]:
        missing = [c for c in mice_cols if c not in split_df.columns]
        if missing:
            print(f"\n❌ FATAL: split '{name}' sin columnas: {missing}")
            sys.exit(1)
    print("\n✅ Consistencia de columnas verificada entre train/val/test")

    # MICE fit en train
    print(f"\n🧮 Ajustando MICE (max_iter={max_iter}) sobre train...")
    imputer = MiceImputer(max_iter=max_iter)
    imputer.fit(train, columns)

    report_stats = {"train": {}, "val": {}, "test": {}}

    print("\n🔧 Aplicando imputación (transform)...")
    train_imp, report_stats["train"] = imputer.transform(train, "train")
    val_imp,   report_stats["val"]   = imputer.transform(val,   "val")
    test_imp,  report_stats["test"]  = imputer.transform(test,  "test")

    # Categóricas
    if columns["categorical"]:
        print("\n🏷️  Imputando categóricas con placeholder 'unknown'...")
        train_imp, cs_tr = impute_categorical(train_imp, columns["categorical"])
        val_imp,   cs_va = impute_categorical(val_imp,   columns["categorical"])
        test_imp,  cs_te = impute_categorical(test_imp,  columns["categorical"])
        report_stats["train"].update(cs_tr)
        report_stats["val"].update(cs_va)
        report_stats["test"].update(cs_te)

    # Guardar imputador
    imputer.save(output_dir / "mice_imputer.pkl")
    print(f"\n💾 Imputador guardado: mice_imputer.pkl")

    # Guardar splits
    train_imp.to_csv(output_dir / "train.csv", index=False)
    val_imp.to_csv(output_dir   / "val.csv",   index=False)
    test_imp.to_csv(output_dir  / "test.csv",  index=False)
    print(f"💾 Splits imputados guardados en {output_dir}/")

    # Reporte JSON — [B8] incluye high_missing
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report = {
        "batch_id":   batch_id,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "max_iter":   max_iter,
        "columnas_clasificacion":   columns,
        "high_missing_excluded":    columns["high_missing"],
        "pct_imputado_por_split":   report_stats,
    }
    report_path = output_dir / f"mice_report_{batch_id}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"📋 Reporte: {report_path.name}")

    # Resumen consola
    print("\n" + "═" * 60)
    print("  RESUMEN DE IMPUTACIÓN")
    print("═" * 60)
    for split_name, s in report_stats.items():
        if s:
            print(f"\n  [{split_name}]")
            for col, pct in s.items():
                marker = "⚠️ " if pct > 80 else "  "
                print(f"    {marker}{col:<30} {pct:>6.2f}% imputado")
        else:
            print(f"\n  [{split_name}] Sin valores faltantes")

    if columns["high_missing"]:
        print(f"\n  🚫 Columnas excluidas de MICE por ≥{MAX_MISSING_PCT*100:.0f}% NaN:")
        for col in columns["high_missing"]:
            pct = train[col].isna().mean() * 100
            print(f"     {col:<30} {pct:>6.2f}% NaN en train")

    print("\n" + "═" * 60)
    print("  ✅ MICE v1.2 completado — listo para feature_engineering.py")
    print("═" * 60)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Imputación MICE — Etapa II")
    parser.add_argument("--input-dir",  required=True,
                        help="Carpeta con train/val/test.csv")
    parser.add_argument("--output-dir", required=True,
                        help="Carpeta de salida")
    parser.add_argument("--max-iter", type=int, default=10,
                        help="Iteraciones IterativeImputer (default: 10)")
    args = parser.parse_args()

    run_mice_pipeline(
        Path(args.input_dir),
        Path(args.output_dir),
        max_iter=args.max_iter,
    )