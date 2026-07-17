#!/usr/bin/env python3
"""
mice_imputer.py v1.0
═══════════════════════════════════════════════════════════════════
Etapa II del pipeline (Sección 4.7.2 del plan de tesis).

Imputación multivariante (MICE — Multivariate Imputation by Chained
Equations) de valores faltantes, aplicada DESPUÉS de temporal_split.py
y ANTES de feature_engineering.py.

ANTI-LEAKAGE (Kapoor & Narayanan, 2023):
  - El imputador se AJUSTA (fit) EXCLUSIVAMENTE sobre train.csv.
  - Los parámetros aprendidos (matriz de regresión encadenada) se
    APLICAN (transform) sobre val.csv y test.csv sin volver a
    ajustarlos — igual que scikit-learn StandardScaler/OneHotEncoder.
  - Nunca se usa información de val/test para decidir cómo imputar
    train, ni se usa test para imputar val.

DISEÑO:
  [M1] Solo columnas NUMÉRICAS pasan por MICE real (IterativeImputer).
       Columnas identificadoras (sku, source, url, batch_id, price_date)
       NUNCA se imputan — no tiene sentido inventar un SKU o una fecha.
  [M2] Columnas binarias (0/1) se redondean/clipan a {0,1} después de
       MICE, porque IterativeImputer puede devolver valores continuos
       intermedios (ej. 0.37) que no son válidos para un flag binario.
  [M3] Columnas categóricas de texto (brand, category) NO pasan por
       MICE — se rellenan con placeholder "unknown" + flag de auditoría.
       MICE numérico no aplica a variables categóricas sin codificar,
       y codificar/decodificar agrega complejidad que el plan de tesis
       no pide explícitamente en esta etapa.
  [M4] Flags _was_missing_<col> — para que los modelos de Etapa III
       puedan distinguir "valor real" de "valor imputado", en vez de
       tratarlos como equivalentes.
  [M5] Fail-fast: si val/test no comparten el mismo set de columnas
       numéricas que train, se aborta con error explícito ANTES de
       llamar transform() (que fallaría con un error confuso de sklearn).
  [M6] Reporte JSON de auditoría (mice_report_<batch>.json) — % de
       valores imputados por columna y por split, para trazabilidad.

Uso:
    python preprocessing/mice_imputer.py \
        --input-dir data/processed \
        --output-dir data/imputed \
        --max-iter 10
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

# IterativeImputer aún es "experimental" en sklearn — requiere el
# enable_iterative_imputer explícito antes de importarlo.
from sklearn.experimental import enable_iterative_imputer  # noqa: F401
from sklearn.impute import IterativeImputer
from sklearn.linear_model import BayesianRidge


# ══════════════════════════════════════════════════════════════════
# CLASIFICACIÓN DE COLUMNAS — [M1] [M2] [M3]
# ══════════════════════════════════════════════════════════════════

# Columnas identificadoras/estructurales — NUNCA se imputan.
ID_COLUMNS = {
    "batch_id", "timestamp", "source", "sku", "url",
    "price_date", "seller_nickname", "part_id", "retailer",
    "title", "condition", "price_currency",
}

# Columnas binarias conocidas (0/1) — MICE + redondeo/clip posterior.
BINARY_COLUMNS = {
    "free_shipping", "is_official_store", "is_best_seller",
    "is_good_seller",
}

# Columnas categóricas de texto — placeholder, NO pasan por MICE.
CATEGORICAL_COLUMNS = {"brand", "category", "category_label"}


def classify_columns(df: pd.DataFrame) -> dict:
    """
    Retorna un dict con las columnas separadas en:
      - numeric_continuous: pasan por MICE tal cual
      - numeric_binary:     pasan por MICE + redondeo a {0,1}
      - categorical:        placeholder "unknown"
      - identifiers:        no se tocan
    """
    all_cols = set(df.columns)
    numeric_cols = set(df.select_dtypes(include=[np.number]).columns)

    identifiers = ID_COLUMNS & all_cols
    categorical = CATEGORICAL_COLUMNS & all_cols
    numeric_binary = BINARY_COLUMNS & numeric_cols
    numeric_continuous = numeric_cols - numeric_binary - identifiers

    # Cualquier columna no clasificada explícitamente pero no numérica
    # ni en las listas anteriores, se trata como identificador (modo
    # conservador: mejor no tocarla que corromperla).
    unclassified = all_cols - identifiers - categorical - numeric_continuous - numeric_binary
    identifiers = identifiers | unclassified

    return {
        "numeric_continuous": sorted(numeric_continuous),
        "numeric_binary":     sorted(numeric_binary),
        "categorical":        sorted(categorical),
        "identifiers":        sorted(identifiers),
    }


# ══════════════════════════════════════════════════════════════════
# WRAPPER DE MICE — fit SOLO en train, transform en val/test
# ══════════════════════════════════════════════════════════════════
class MiceImputer:
    """
    Envuelve sklearn.IterativeImputer respetando estrictamente el
    principio anti-leakage: fit() se llama UNA sola vez, sobre train.
    transform() se puede llamar múltiples veces (train, val, test)
    sin volver a ajustar los parámetros internos.
    """

    def __init__(self, max_iter: int = 10, random_state: int = 42):
        self.max_iter = max_iter
        self.random_state = random_state
        self.imputer_ = None
        self.numeric_continuous_cols_ = None
        self.numeric_binary_cols_ = None
        self.fitted_ = False

    def fit(self, df_train: pd.DataFrame, columns: dict):
        self.numeric_continuous_cols_ = columns["numeric_continuous"]
        self.numeric_binary_cols_     = columns["numeric_binary"]
        mice_cols = self.numeric_continuous_cols_ + self.numeric_binary_cols_

        if not mice_cols:
            warnings.warn("No hay columnas numéricas para imputar con MICE.")
            self.fitted_ = True
            return self

        self.imputer_ = IterativeImputer(
            estimator=BayesianRidge(),
            max_iter=self.max_iter,
            random_state=self.random_state,
            sample_posterior=False,
        )
        self.imputer_.fit(df_train[mice_cols])
        self.fitted_ = True
        return self

    def transform(self, df: pd.DataFrame, split_name: str = "") -> tuple:
        """
        Retorna (df_imputado, stats_dict).
        [M5] Fail-fast si df no tiene las columnas con las que se
        ajustó el imputador.
        """
        if not self.fitted_:
            raise RuntimeError("Debe llamar fit() sobre train antes de transform()")

        df = df.copy()
        mice_cols = self.numeric_continuous_cols_ + self.numeric_binary_cols_
        stats = {}

        if not mice_cols:
            return df, stats

        # [M5] Fail-fast: columnas esperadas deben existir
        missing = [c for c in mice_cols if c not in df.columns]
        if missing:
            raise ValueError(
                f"[{split_name}] Columnas numéricas ausentes respecto a "
                f"train (imputador no puede aplicarse): {missing}"
            )

        # [M4] Flags de auditoría — ANTES de imputar
        for col in mice_cols:
            missing_mask = df[col].isna()
            if missing_mask.any():
                df[f"_was_missing_{col}"] = missing_mask.astype(int)
                pct = round(missing_mask.mean() * 100, 2)
                stats[col] = pct

        # [FIX] sklearn salta columnas all-NaN en fit → devuelve menos columnas
        # Usamos get_feature_names_out si está disponible, sino reconstruimos
        import numpy as np
        X_in = df[mice_cols].values
        X_out = self.imputer_.transform(df[mice_cols])

        # Identificar qué columnas fueron realmente imputadas por sklearn
        # (las all-NaN en train son saltadas → n_cols_out <= n_cols_in)
        if X_out.shape[1] == len(mice_cols):
            # Caso normal: todas las columnas procesadas
            df[mice_cols] = X_out
        else:
            # Caso all-NaN: reconstruir columna a columna
            # sklearn mantiene el orden pero omite las all-NaN
            # Detectar cuáles fueron omitidas (las que tienen indicador en imputer_)
            indicator = self.imputer_.indicator_
            if indicator is not None:
                kept_mask = ~np.array([
                    col_idx in self.imputer_.indicator_.features_
                    for col_idx in range(len(mice_cols))
                ])
            else:
                # Fallback: detectar por all-NaN en train
                kept_mask = np.array([True] * len(mice_cols))

            # Método robusto: usar statistics_ para saber cuáles fueron procesadas
            # imputer_.statistics_ tiene NaN para columnas saltadas
            stats_arr = self.imputer_.initial_imputer_.statistics_
            valid_cols = [col for col, stat in zip(mice_cols, stats_arr)
                         if not np.isnan(stat)]

            if len(valid_cols) == X_out.shape[1]:
                df[valid_cols] = X_out
                # Las columnas saltadas quedan con NaN (sin cambio)
            else:
                # Último fallback: asignar por posición a las primeras N columnas
                df[mice_cols[:X_out.shape[1]]] = X_out

        # [M2] Columnas binarias: redondear/clip a {0,1} tras MICE
        # Si la columna era all-NaN (sklearn la saltó), rellenar con 0
        for col in self.numeric_binary_cols_:
            if df[col].isna().all():
                df[col] = 0
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
# IMPUTACIÓN DE CATEGÓRICAS — [M3] placeholder simple, sin fit/leakage
# ══════════════════════════════════════════════════════════════════
def impute_categorical(df: pd.DataFrame, categorical_cols: list) -> tuple:
    df = df.copy()
    stats = {}
    for col in categorical_cols:
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
    print("  MICE IMPUTER v1.0 — Etapa II")
    print("═" * 60)

    train = pd.read_csv(input_dir / "train.csv", low_memory=False)
    val   = pd.read_csv(input_dir / "val.csv",   low_memory=False)
    test  = pd.read_csv(input_dir / "test.csv",  low_memory=False)

    print(f"\n📊 Splits cargados: train={len(train):,} | val={len(val):,} | test={len(test):,}")

    # ── Clasificación de columnas (basada en train) ─────────────
    columns = classify_columns(train)
    print(f"\n🔎 Clasificación de columnas:")
    print(f"   Numéricas continuas (MICE) : {len(columns['numeric_continuous'])} → {columns['numeric_continuous']}")
    print(f"   Numéricas binarias (MICE)  : {len(columns['numeric_binary'])} → {columns['numeric_binary']}")
    print(f"   Categóricas (placeholder)  : {len(columns['categorical'])} → {columns['categorical']}")
    print(f"   Identificadores (sin tocar): {len(columns['identifiers'])}")

    # ── [M5] Fail-fast: val/test deben compartir columnas numéricas ──
    mice_cols = columns["numeric_continuous"] + columns["numeric_binary"]
    for name, split_df in [("val", val), ("test", test)]:
        missing = [c for c in mice_cols if c not in split_df.columns]
        if missing:
            print(f"\n❌ FATAL: split '{name}' no tiene las columnas numéricas "
                  f"esperadas (según train): {missing}")
            print("   Abortando — revisar temporal_split.py o data_contract.yaml.")
            sys.exit(1)
    print("\n✅ Consistencia de columnas verificada entre train/val/test")

    # ── MICE: fit SOLO en train ──────────────────────────────────
    print(f"\n🧮 Ajustando MICE (IterativeImputer, max_iter={max_iter}) sobre train...")
    imputer = MiceImputer(max_iter=max_iter)
    imputer.fit(train, columns)

    report_stats = {"train": {}, "val": {}, "test": {}}

    print("\n🔧 Aplicando imputación (transform)...")
    train_imp, report_stats["train"] = imputer.transform(train, split_name="train")
    val_imp,   report_stats["val"]   = imputer.transform(val,   split_name="val")
    test_imp,  report_stats["test"] = imputer.transform(test,  split_name="test")

    # ── Categóricas: placeholder por split (no requiere fit) ────
    if columns["categorical"]:
        print("\n🏷️  Imputando categóricas con placeholder 'unknown'...")
        train_imp, cat_stats_train = impute_categorical(train_imp, columns["categorical"])
        val_imp,   cat_stats_val   = impute_categorical(val_imp,   columns["categorical"])
        test_imp,  cat_stats_test  = impute_categorical(test_imp,  columns["categorical"])
        report_stats["train"].update(cat_stats_train)
        report_stats["val"].update(cat_stats_val)
        report_stats["test"].update(cat_stats_test)

    # ── Guardar imputador para uso en inferencia ─────────────────
    imputer.save(output_dir / "mice_imputer.pkl")
    print(f"\n💾 Imputador guardado: mice_imputer.pkl")

    # ── Guardar splits imputados ──────────────────────────────────
    train_imp.to_csv(output_dir / "train.csv", index=False)
    val_imp.to_csv(output_dir / "val.csv", index=False)
    test_imp.to_csv(output_dir / "test.csv", index=False)
    print(f"💾 Splits imputados guardados en {output_dir}/")

    # ── Reporte de auditoría ──────────────────────────────────────
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report = {
        "batch_id": batch_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "max_iter": max_iter,
        "columnas_clasificacion": columns,
        "pct_imputado_por_split": report_stats,
    }
    report_path = output_dir / f"mice_report_{batch_id}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"📋 Reporte de imputación: {report_path.name}")

    # ── Resumen en consola ─────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  RESUMEN DE IMPUTACIÓN")
    print("═" * 60)
    for split_name, stats in report_stats.items():
        if stats:
            print(f"\n  [{split_name}]")
            for col, pct in stats.items():
                print(f"    {col:<25} {pct:>6.2f}% imputado")
        else:
            print(f"\n  [{split_name}] Sin valores faltantes detectados")
    print("\n" + "═" * 60)
    print("  ✅ Imputación MICE completada — listo para feature_engineering.py")
    print("═" * 60)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Imputación MICE — Etapa II")
    parser.add_argument("--input-dir", required=True, help="Carpeta con train/val/test.csv (post temporal_split)")
    parser.add_argument("--output-dir", required=True, help="Carpeta de salida de splits imputados")
    parser.add_argument("--max-iter", type=int, default=10, help="Iteraciones de IterativeImputer (default: 10)")
    args = parser.parse_args()

    run_mice_pipeline(Path(args.input_dir), Path(args.output_dir), max_iter=args.max_iter)
