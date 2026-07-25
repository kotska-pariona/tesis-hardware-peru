#!/usr/bin/env python3
"""
feature_engineering.py v1.5
═══════════════════════════════════════════════════════════════════
Etapa II del pipeline (Sección 4.7.2 del plan de tesis).

CAMBIOS v1.5 (FIX-28):
  [B11] Lags y ventanas adaptados a la densidad real de las series.
        El dataset tiene máx ~10 observaciones por SKU con frecuencia
        diaria/semanal. Los lags (1,7,30) y ventanas (7,14,30) de v1.x
        producían 100% NaN porque ningún SKU tiene 30+ observaciones.
        Ahora se usan lags=(1,2,3) y ventanas=(2,3,5) por defecto,
        con parámetros configurables por CLI para ajuste futuro.
  [B12] _add_lags(): añade columna de cobertura de lag — reporta qué
        porcentaje de filas tiene valor real (no NaN) en cada lag,
        para detectar lags inútiles antes de pasarlos al modelo.
  [B13] run_feature_pipeline(): imprime tabla de cobertura de lags
        y emite advertencia si algún lag tiene < 10% cobertura en
        train, sugiriendo reducir el lag máximo.
"""

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ══════════════════════════════════════════════════════════════════
# CONSTANTES
# ══════════════════════════════════════════════════════════════════
_SORT_KEY  = "__fe_sort_key"
_IS_TARGET = "__fe_is_target"

PRICE_COL_CANDIDATES = [
    "price_usd",
    "price_pen",
    "price_orig_pen",
    "total_usd",
    "original_price",
]

# Lags y ventanas por defecto — adaptados a series cortas (máx ~10 obs)
# Ajustar con --lags y --windows si el dataset cambia
DEFAULT_LAGS    = (1, 2, 3)
DEFAULT_WINDOWS = (2, 3, 5)


# ══════════════════════════════════════════════════════════════════
# DETECCIÓN AUTOMÁTICA DE COLUMNA DE PRECIO
# ══════════════════════════════════════════════════════════════════
def detect_price_col(df: pd.DataFrame,
                     candidates: list = PRICE_COL_CANDIDATES) -> str:
    for col in candidates:
        if col not in df.columns:
            continue
        pct_valid = df[col].notna().mean()
        if pct_valid >= 0.05:
            if col != candidates[0]:
                print(f"   ⚠️  '{candidates[0]}' es ≥95% NaN — "
                      f"usando '{col}' ({pct_valid*100:.1f}% válido)")
            else:
                print(f"   ✅ Columna de precio: '{col}' "
                      f"({pct_valid*100:.1f}% válido)")
            return col

    diag = "\n".join(
        f"   {c}: {'no existe' if c not in df.columns else f'{df[c].notna().mean()*100:.1f}% válido'}"
        for c in candidates
    )
    raise ValueError(
        f"Ninguna columna de precio candidata tiene datos suficientes:\n"
        f"{diag}"
    )


# ══════════════════════════════════════════════════════════════════
# DIAGNÓSTICO DE SERIES TEMPORALES — [B11]
# ══════════════════════════════════════════════════════════════════
def diagnose_series(df: pd.DataFrame, label: str = "train") -> dict:
    """
    Imprime estadísticas de longitud de series por SKU.
    Devuelve dict con percentiles para uso programático.
    """
    counts = df.groupby("sku").size()
    stats  = counts.describe(percentiles=[.25, .5, .75, .90, .95])
    print(f"\n   📊 Longitud de series [{label}]:")
    print(f"      SKUs únicos : {len(counts):,}")
    print(f"      min / p25   : {int(stats['min'])} / {int(stats['25%'])}")
    print(f"      mediana     : {int(stats['50%'])}")
    print(f"      p75 / p95   : {int(stats['75%'])} / {int(stats['95%'])}")
    print(f"      máx         : {int(stats['max'])}")
    return stats.to_dict()


def suggest_lags(df: pd.DataFrame) -> tuple:
    """
    [B11] Sugiere lags y ventanas basados en el p50 de longitud
    de serie. Regla conservadora: lag_max <= p50 - 1.
    """
    counts = df.groupby("sku").size()
    p50    = int(counts.median())
    p75    = int(counts.quantile(0.75))

    lag_max    = max(1, p50 - 1)
    window_max = max(2, p75 - 1)

    lags    = tuple(sorted({1, 2, lag_max}))
    windows = tuple(sorted({2, 3, min(window_max, lag_max + 2)}))

    print(f"\n   💡 Lags sugeridos (p50={p50}): {lags}")
    print(f"   💡 Ventanas sugeridas (p75={p75}): {windows}")
    return lags, windows


# ══════════════════════════════════════════════════════════════════
# UTILIDAD DE ORDEN CRONOLÓGICO REAL
# ══════════════════════════════════════════════════════════════════
def _sort_by_date(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df[_SORT_KEY] = pd.to_datetime(df["price_date"], errors="coerce")
    df = df.sort_values(["sku", _SORT_KEY], kind="stable")
    return df.drop(columns=[_SORT_KEY]).reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════
# INGENIERÍA DE CARACTERÍSTICAS POR SKU
# ══════════════════════════════════════════════════════════════════
def _add_lags(df: pd.DataFrame, col: str, lags: list) -> pd.DataFrame:
    for lag in lags:
        df[f"{col}_lag_{lag}"] = df.groupby("sku")[col].shift(lag)
    return df


def _add_rolling_features(df: pd.DataFrame, col: str,
                           windows: list) -> pd.DataFrame:
    """ddof=0 → std de 1 elemento = 0.0 en vez de NaN."""
    grouped = df.groupby("sku")[col]
    for w in windows:
        df[f"{col}_ma_{w}"] = grouped.transform(
            lambda s, _w=w: s.rolling(_w, min_periods=1).mean()
        )
        df[f"{col}_std_{w}"] = grouped.transform(
            lambda s, _w=w: s.rolling(_w, min_periods=1).std(ddof=0)
        )
    return df


def build_features(
    df: pd.DataFrame,
    context: pd.DataFrame = None,
    lags: list = DEFAULT_LAGS,
    windows: list = DEFAULT_WINDOWS,
    col: str = "price_usd",
) -> pd.DataFrame:
    """
    Genera lags, medias móviles y volatilidad por SKU.
    [F1]  context = split anterior → evita NaN en primeras filas.
    [B10] groupby().tail(N) nativo — sin apply(), sin warnings.
    """
    lags    = list(lags)
    windows = list(windows)
    context_needed = max(lags + windows) if (lags or windows) else 0

    for c in [_SORT_KEY, _IS_TARGET]:
        if c in df.columns:
            df = df.drop(columns=[c])

    target = df.copy()
    target[_SORT_KEY] = pd.to_datetime(target["price_date"], errors="coerce")
    target = (target
              .sort_values(["sku", _SORT_KEY], kind="stable")
              .drop(columns=[_SORT_KEY])
              .reset_index(drop=True))
    target[_IS_TARGET] = True

    if context is not None and not context.empty and context_needed > 0:
        ctx = context.copy()
        for c in [_SORT_KEY, _IS_TARGET]:
            if c in ctx.columns:
                ctx = ctx.drop(columns=[c])

        ctx[_SORT_KEY] = pd.to_datetime(ctx["price_date"], errors="coerce")
        ctx = (ctx
               .sort_values(["sku", _SORT_KEY], kind="stable")
               .drop(columns=[_SORT_KEY])
               .reset_index(drop=True))

        # [B10] groupby().tail(N) — nativo pandas, sin apply()
        tail_ctx = (
            ctx.groupby("sku", sort=False)
            .tail(context_needed)
            .reset_index(drop=True)
        )
        tail_ctx[_IS_TARGET] = False

        combined = (
            pd.concat([tail_ctx, target], ignore_index=True)
            .assign(**{
                _SORT_KEY: lambda d: pd.to_datetime(
                    d["price_date"], errors="coerce"
                )
            })
            .sort_values(["sku", _SORT_KEY], kind="stable")
            .drop(columns=[_SORT_KEY])
            .reset_index(drop=True)
        )
    else:
        combined = target.copy()

    combined = _add_lags(combined, col, lags)
    combined = _add_rolling_features(combined, col, windows)

    result = (combined[combined[_IS_TARGET]]
              .drop(columns=[_IS_TARGET])
              .reset_index(drop=True))
    return result


# ══════════════════════════════════════════════════════════════════
# COBERTURA DE LAGS — [B12]
# ══════════════════════════════════════════════════════════════════
def report_lag_coverage(df: pd.DataFrame, col: str,
                        lags: list, label: str = ""):
    """
    [B12] Imprime % de filas con valor real (no NaN) por lag.
    Advierte si algún lag tiene < 10% cobertura.
    """
    print(f"\n   📋 Cobertura de lags [{label}]:")
    for lag in lags:
        lag_col = f"{col}_lag_{lag}"
        if lag_col not in df.columns:
            continue
        cov = df[lag_col].notna().mean() * 100
        bar = "█" * int(cov / 5)
        warn = " ⚠️  < 10%" if cov < 10 else ""
        print(f"      lag_{lag:<3} {cov:5.1f}%  {bar}{warn}")


# ══════════════════════════════════════════════════════════════════
# ROLLING Z-SCORE — fit SOLO en train
# ══════════════════════════════════════════════════════════════════
class RollingZScoreNormalizer:

    def __init__(self, window: int = 90, col: str = "price_usd"):
        self.window   = window
        self.col      = col
        self.fitted_  = False
        self._history_: dict = {}

    def fit(self, df_train: pd.DataFrame):
        df_train = _sort_by_date(df_train)
        for sku, group in df_train.groupby("sku"):
            self._history_[sku] = group[self.col].tail(self.window).tolist()
        self.fitted_ = True
        return self

    def transform(self, df: pd.DataFrame,
                  is_train: bool = False) -> pd.DataFrame:
        if not self.fitted_:
            raise RuntimeError(
                "Debe llamar fit() sobre train antes de transform()"
            )
        df       = _sort_by_date(df)
        col_name = f"{self.col}_zscore_{self.window}"
        z_series = pd.Series(index=df.index, dtype="float64")
        updated_history: dict = {}

        for sku, group in df.groupby("sku"):
            idx     = group.index
            values  = group[self.col].tolist()
            history = [] if is_train else self._history_.get(sku, [])
            rolling_z = []
            buffer    = list(history)

            for v in values:
                if len(buffer) >= 2:
                    mu    = np.mean(buffer)
                    sigma = np.std(buffer)
                    z     = (v - mu) / sigma if sigma > 1e-6 else 0.0
                else:
                    z = 0.0
                rolling_z.append(z)
                buffer.append(v)
                if len(buffer) > self.window:
                    buffer.pop(0)

            z_series.loc[idx] = rolling_z
            if is_train:
                updated_history[sku] = buffer[-self.window:]

        if is_train:
            self._history_.update(updated_history)

        df[col_name] = z_series
        return df

    def update_history(self, df: pd.DataFrame):
        df = _sort_by_date(df)
        for sku, group in df.groupby("sku"):
            prev     = self._history_.get(sku, [])
            combined = prev + group[self.col].tolist()
            self._history_[sku] = combined[-self.window:]

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
def run_feature_pipeline(input_dir: Path, output_dir: Path,
                         lags: tuple = None, windows: tuple = None):

    if input_dir.resolve() == output_dir.resolve():
        print("❌ FATAL: --input-dir y --output-dir son el mismo directorio.")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    print("═" * 60)
    print("  FEATURE ENGINEERING v1.5 — Etapa II")
    print("═" * 60)

    train = pd.read_csv(input_dir / "train.csv", low_memory=False)
    val   = pd.read_csv(input_dir / "val.csv",   low_memory=False)
    test  = pd.read_csv(input_dir / "test.csv",  low_memory=False)

    print(f"\n📊 Splits cargados: "
          f"train={len(train):,} | val={len(val):,} | test={len(test):,}")

    # Detectar columna de precio
    print("\n🔍 Detectando columna de precio...")
    price_col = detect_price_col(train)

    # [B11] Diagnóstico de series y lags sugeridos
    print("\n🔬 Analizando densidad de series temporales...")
    diagnose_series(train, label="train")

    if lags is None or windows is None:
        print("\n   ℹ️  Lags/ventanas no especificados — calculando automáticamente:")
        auto_lags, auto_windows = suggest_lags(train)
        lags    = lags    or auto_lags
        windows = windows or auto_windows
    else:
        print(f"\n   ℹ️  Lags manuales: {lags} | Ventanas: {windows}")

    cols_before = set(train.columns)

    # ── 1. Features deterministas ────────────────────────────────
    print("\n🔧 Generando lags, medias móviles y volatilidad...")
    train_feat = build_features(train, col=price_col,
                                lags=lags, windows=windows)
    val_feat   = build_features(val,   context=train, col=price_col,
                                lags=lags, windows=windows)
    test_feat  = build_features(
        test,
        context=pd.concat([train, val], ignore_index=True),
        col=price_col, lags=lags, windows=windows,
    )

    # ── 2. Rolling z-score (fit SOLO en train) ───────────────────
    print("\n📐 Ajustando normalizador (rolling z-score, fit=train)...")
    normalizer = RollingZScoreNormalizer(window=90, col=price_col)
    normalizer.fit(train_feat)

    train_feat = normalizer.transform(train_feat, is_train=True)
    val_feat   = normalizer.transform(val_feat,   is_train=False)
    normalizer.update_history(val_feat)
    test_feat  = normalizer.transform(test_feat,  is_train=False)

    normalizer.save(output_dir / "zscore_normalizer.pkl")
    print(f"   💾 Normalizador guardado: zscore_normalizer.pkl")

    # ── 3. Guardar features ──────────────────────────────────────
    train_feat.to_csv(output_dir / "train_features.csv", index=False)
    val_feat.to_csv(output_dir   / "val_features.csv",   index=False)
    test_feat.to_csv(output_dir  / "test_features.csv",  index=False)

    # ── 4. Reporte ───────────────────────────────────────────────
    cols_after = set(train_feat.columns)
    new_cols   = sorted(cols_after - cols_before)

    print(f"\n✅ Features guardadas en {output_dir}/")
    print(f"   Columnas nuevas ({len(new_cols)}): {new_cols}")

    # [B12] Cobertura de lags
    report_lag_coverage(train_feat, price_col, list(lags), "train")
    report_lag_coverage(val_feat,   price_col, list(lags), "val")
    report_lag_coverage(test_feat,  price_col, list(lags), "test")

    print("\n" + "═" * 60)
    print("  ✅ Feature Engineering v1.5 completado")
    print("  ✅ Etapa II completada — listo para modelos (Etapa III)")
    print("═" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Feature Engineering — Etapa II"
    )
    parser.add_argument("--input-dir",  required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--lags", type=int, nargs="+", default=None,
        help="Lags explícitos (ej: --lags 1 2 3). "
             "Por defecto se calculan automáticamente."
    )
    parser.add_argument(
        "--windows", type=int, nargs="+", default=None,
        help="Ventanas rolling (ej: --windows 2 3 5). "
             "Por defecto se calculan automáticamente."
    )
    args = parser.parse_args()

    run_feature_pipeline(
        Path(args.input_dir),
        Path(args.output_dir),
        lags    = tuple(args.lags)    if args.lags    else None,
        windows = tuple(args.windows) if args.windows else None,
    )