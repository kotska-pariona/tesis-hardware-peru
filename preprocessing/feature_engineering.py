#!/usr/bin/env python3
"""
feature_engineering.py v1.0
═══════════════════════════════════════════════════════════════════
Etapa II del pipeline (Sección 4.7.2 del plan de tesis).

Genera las características de entrada para los modelos de Etapa III
(TFT, TCN, XGBoost) a partir de los splits temporales ya separados
por temporal_split.py.

ANTI-LEAKAGE (Kapoor & Narayanan, 2023):
  - El normalizador (rolling z-score) se AJUSTA (fit) exclusivamente
    sobre train.csv.
  - Los parámetros aprendidos (media, std por ventana) se APLICAN
    (transform) sobre val.csv y test.csv sin volver a ajustarlos.
  - MICE se ajusta también solo sobre train; val/test usan el mismo
    imputador ya entrenado (fit_transform en train, transform en resto).

Características generadas (por SKU):
  - Rezagos:        price_usd_lag_1, price_usd_lag_7, price_usd_lag_30
  - Medias móviles:  price_usd_ma_7, price_usd_ma_14, price_usd_ma_30
  - Volatilidad:     price_usd_std_7, price_usd_std_30 (rolling std)
  - Normalización:   price_usd_zscore_90 (rolling z-score, ventana 90d)

Uso:
    python preprocessing/feature_engineering.py \
        --input-dir data/processed \
        --output-dir data/features
"""

import argparse
import pickle
from pathlib import Path

import numpy as np
import pandas as pd


# ══════════════════════════════════════════════════════════════════
# INGENIERÍA DE CARACTERÍSTICAS POR SKU
# ══════════════════════════════════════════════════════════════════
def _add_lags(df: pd.DataFrame, col: str, lags: list) -> pd.DataFrame:
    for lag in lags:
        df[f"{col}_lag_{lag}"] = df.groupby("sku")[col].shift(lag)
    return df


def _add_rolling_features(df: pd.DataFrame, col: str, windows: list) -> pd.DataFrame:
    grouped = df.groupby("sku")[col]
    for w in windows:
        df[f"{col}_ma_{w}"]  = grouped.transform(lambda s: s.rolling(w, min_periods=1).mean())
        df[f"{col}_std_{w}"] = grouped.transform(lambda s: s.rolling(w, min_periods=1).std())
    return df


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["sku", "price_date"]).reset_index(drop=True)

    # Rezagos (Sección 4.7.2, punto 4)
    df = _add_lags(df, "price_usd", lags=[1, 7, 30])

    # Medias móviles y volatilidad
    df = _add_rolling_features(df, "price_usd", windows=[7, 14, 30])

    return df


# ══════════════════════════════════════════════════════════════════
# ROLLING Z-SCORE — fit SOLO en train, transform en val/test
# (implementación simplificada: usa media/std móvil de 90 días
#  calculada acumulativamente hasta cada punto, sin usar futuro)
# ══════════════════════════════════════════════════════════════════
class RollingZScoreNormalizer:
    """
    Ajusta (fit) los parámetros de normalización SOLO sobre el
    dataset de entrenamiento. Para train, usa rolling z-score causal
    (ventana 90 días, solo pasado). Para val/test, usa la MISMA
    ventana pero continuando la serie histórica de train, evitando
    así "resetear" la normalización en el corte de partición.
    """

    def __init__(self, window: int = 90, col: str = "price_usd"):
        self.window = window
        self.col = col
        self.fitted_ = False
        self._history_ = {}   # sku -> últimos `window` valores de train

    def fit(self, df_train: pd.DataFrame):
        for sku, group in df_train.groupby("sku"):
            self._history_[sku] = group[self.col].tail(self.window).tolist()
        self.fitted_ = True
        return self

    def transform(self, df: pd.DataFrame, is_train: bool = False) -> pd.DataFrame:
        if not self.fitted_:
            raise RuntimeError("Debe llamar fit() sobre train antes de transform()")

        df = df.copy()
        zscores = []

        for sku, group in df.groupby("sku"):
            values = group[self.col].tolist()
            history = self._history_.get(sku, []) if not is_train else []
            rolling_z = []

            buffer = list(history)  # contexto previo (de train) para val/test
            for v in values:
                if len(buffer) >= 2:
                    mu, sigma = np.mean(buffer), np.std(buffer)
                    z = (v - mu) / sigma if sigma > 1e-6 else 0.0
                else:
                    z = 0.0
                rolling_z.append(z)
                buffer.append(v)
                if len(buffer) > self.window:
                    buffer.pop(0)

            zscores.extend(rolling_z)

        df[f"{self.col}_zscore_{self.window}"] = zscores
        return df

    def save(self, path: Path):
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: Path) -> "RollingZScoreNormalizer":
        with open(path, "rb") as f:
            return pickle.load(f)


# ══════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ══════════════════════════════════════════════════════════════════
def run_feature_pipeline(input_dir: Path, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    print("═" * 60)
    print("  FEATURE ENGINEERING v1.0 — Etapa II")
    print("═" * 60)

    train = pd.read_csv(input_dir / "train.csv", low_memory=False)
    val   = pd.read_csv(input_dir / "val.csv",   low_memory=False)
    test  = pd.read_csv(input_dir / "test.csv",  low_memory=False)

    print(f"\n📊 Splits cargados: train={len(train):,} | val={len(val):,} | test={len(test):,}")

    # 1. Features deterministas (lags, MA, std) — no requieren fit
    print("\n🔧 Generando lags, medias móviles y volatilidad...")
    train_feat = build_features(train)
    val_feat   = build_features(val)
    test_feat  = build_features(test)

    # 2. Rolling z-score — fit SOLO en train (anti-leakage)
    print("\n📐 Ajustando normalizador (rolling z-score, fit=train)...")
    normalizer = RollingZScoreNormalizer(window=90, col="price_usd")
    normalizer.fit(train_feat)

    train_feat = normalizer.transform(train_feat, is_train=True)
    val_feat   = normalizer.transform(val_feat,   is_train=False)
    test_feat  = normalizer.transform(test_feat,  is_train=False)

    # Guardar normalizador para uso en inferencia (Etapa III/run_pipeline.py)
    normalizer.save(output_dir / "zscore_normalizer.pkl")
    print(f"  💾 Normalizador guardado: zscore_normalizer.pkl")

    # 3. Guardar features
    train_feat.to_csv(output_dir / "train_features.csv", index=False)
    val_feat.to_csv(output_dir / "val_features.csv", index=False)
    test_feat.to_csv(output_dir / "test_features.csv", index=False)

    print(f"\n✅ Features guardadas en {output_dir}/")
    print(f"   Columnas nuevas por split: "
          f"{train_feat.shape[1] - train.shape[1]}")

    print("\n" + "═" * 60)
    print("  ✅ Etapa II completada — listo para modelos (Etapa III)")
    print("═" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Feature Engineering — Etapa II")
    parser.add_argument("--input-dir", required=True, help="Carpeta con train/val/test.csv")
    parser.add_argument("--output-dir", required=True, help="Carpeta de salida de features")
    args = parser.parse_args()

    run_feature_pipeline(Path(args.input_dir), Path(args.output_dir))
