"""
preprocessing/cleaner.py — Módulo de limpieza y preprocesamiento
HDS-ROI v6.0 — Path canónico esperado por el diagnóstico

Método : MICE (Multiple Imputation by Chained Equations)
Base   : BayesianRidge (sklearn)
Params : max_iter=10, random_state=42, sample_posterior=True
Outliers: Rolling z-score por ventana deslizante
Rango  : $5.40 — $8,175.54 USD
"""
import pandas as pd
import numpy as np
from sklearn.experimental import enable_iterative_imputer  # noqa
from sklearn.impute import IterativeImputer
from sklearn.linear_model import BayesianRidge

PRICE_MIN  = 5.40
PRICE_MAX  = 8_175.54
MICE_PARAMS = dict(
    estimator       = BayesianRidge(),
    max_iter        = 10,
    random_state    = 42,
    sample_posterior= True,
)


def apply_mice(df: pd.DataFrame, numeric_cols: list) -> pd.DataFrame:
    """Aplica MICE sobre columnas numéricas especificadas."""
    imputer = IterativeImputer(**MICE_PARAMS)
    df = df.copy()
    df[numeric_cols] = imputer.fit_transform(df[numeric_cols])
    return df


def filter_price_range(df: pd.DataFrame,
                        col: str = "price_usd") -> pd.DataFrame:
    """Filtra outliers de precio fuera del rango válido."""
    mask    = df[col].between(PRICE_MIN, PRICE_MAX)
    removed = (~mask).sum()
    if removed:
        print(f"  [cleaner] Removidos {removed:,} registros fuera de rango "
              f"(${PRICE_MIN}–${PRICE_MAX:,.2f})")
    return df[mask].copy()


def rolling_zscore_filter(df: pd.DataFrame,
                           col: str = "price_usd",
                           window: int = 7,
                           threshold: float = 3.0) -> pd.DataFrame:
    """Detección de anomalías por rolling z-score."""
    roll_mean = df[col].rolling(window, min_periods=1).mean()
    roll_std  = df[col].rolling(window, min_periods=1).std().fillna(1.0)
    z_scores  = (df[col] - roll_mean) / roll_std
    removed   = (z_scores.abs() > threshold).sum()
    if removed:
        print(f"  [cleaner] Rolling z-score: {removed:,} anomalías removidas")
    return df[z_scores.abs() <= threshold].copy()


def clean_pipeline(df: pd.DataFrame,
                    numeric_cols: list = None) -> pd.DataFrame:
    """
    Pipeline completo de limpieza ETL:
      1. Filtro rango de precios
      2. Rolling z-score
      3. MICE imputation
    """
    if numeric_cols is None:
        numeric_cols = ["price_usd"]
    n0 = len(df)
    df = filter_price_range(df)
    df = rolling_zscore_filter(df)
    df = apply_mice(df, numeric_cols)
    print(f"  [cleaner] Pipeline: {n0:,} → {len(df):,} registros "
          f"({n0 - len(df):,} removidos)")
    return df


if __name__ == "__main__":
    print("preprocessing/cleaner.py — módulo de limpieza HDS-ROI v6.0")
    print("Importar con: from preprocessing.cleaner import clean_pipeline")
