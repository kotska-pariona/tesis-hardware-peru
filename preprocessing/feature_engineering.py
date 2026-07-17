#!/usr/bin/env python3
"""
feature_engineering.py v1.1
═══════════════════════════════════════════════════════════════════
Etapa II del pipeline (Sección 4.7.2 del plan de tesis).

Genera las características de entrada para los modelos de Etapa III
(TFT, TCN, XGBoost) a partir de los splits temporales ya separados
por temporal_split.py.

CAMBIOS v1.1 (sobre v1.0):
  [F1] FIX CRÍTICO build_features(): ahora acepta un parámetro
       `context` (split estrictamente ANTERIOR en el tiempo). Antes,
       lags/MA/std se calculaban por split de forma aislada, así que
       las primeras ~30 filas de cada SKU en val/test quedaban en NaN
       aunque el historial real existiera en el split previo. Ahora
       se "presta" temporalmente el historial necesario del contexto,
       se calculan las features sobre la serie combinada, y al final
       se descartan las filas prestadas — solo se usa información
       PASADA real, nunca futura (no hay leakage).
  [F2] FIX CRÍTICO orden cronológico: sort_values(["sku","price_date"])
       ordenaba por STRING, no por fecha real. Si las fuentes usan
       formatos de fecha inconsistentes (ISO vs DD/MM/YYYY, etc.),
       el orden quedaba silenciosamente incorrecto y todos los lags/
       medias móviles/z-scores calculados eran inválidos sin ningún
       error visible. Ahora se usa pd.to_datetime() como clave de
       ordenamiento auxiliar (la columna price_date original no se
       modifica).
  [F3] RollingZScoreNormalizer.update_history(): permite encadenar
       el historial rolling entre splits consecutivos (train→val→test)
       para que test no "salte" directamente al historial de train
       ignorando val — evita una discontinuidad artificial en el
       cálculo de z-score al inicio de test.
  [F4] Asignación de z-scores por índice explícito (Series.loc) en
       vez de por posición (extend + asignación posicional), evitando
       una dependencia implícita y frágil del orden de iteración de
       groupby().

ANTI-LEAKAGE (Kapoor & Narayanan, 2023):
  - El normalizador (rolling z-score) se AJUSTA (fit) exclusivamente
    sobre train.csv.
  - Los parámetros aprendidos (media, std por ventana) se APLICAN
    (transform) sobre val.csv y test.csv sin volver a ajustarlos.
  - Los lags/MA/std son deterministas y solo miran hacia el pasado;
    usar `context` para no perder datos NO introduce leakage, porque
    context es siempre un split cronológicamente anterior al target.
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
# UTILIDAD DE ORDEN CRONOLÓGICO REAL — [F2]
# ══════════════════════════════════════════════════════════════════
def _sort_by_date(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ordena por (sku, fecha_real) usando pd.to_datetime() como clave
    auxiliar. La columna price_date original NO se modifica ni se
    sobrescribe — solo se usa para determinar el orden correcto.
    """
    df = df.copy()
    df["_sort_key"] = pd.to_datetime(df["price_date"], errors="coerce")
    df = df.sort_values(["sku", "_sort_key"], kind="stable")
    return df.drop(columns=["_sort_key"]).reset_index(drop=True)


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


def build_features(
    df: pd.DataFrame,
    context: pd.DataFrame = None,
    lags: list = (1, 7, 30),
    windows: list = (7, 14, 30),
    col: str = "price_usd",
) -> pd.DataFrame:
    """
    [F1] Version optimizada: sort unico, contexto reducido por SKU,
    sin copias innecesarias. El contexto es siempre cronologicamente
    anterior (no hay leakage).
    """
    lags, windows = list(lags), list(windows)
    context_needed = max(lags + windows) if (lags or windows) else 0

    # Sort unico sobre target
    target = df.copy()
    target["_sort_key"] = pd.to_datetime(target["price_date"], errors="coerce")
    target = target.sort_values(["sku", "_sort_key"], kind="stable").drop(columns=["_sort_key"])
    target["_is_target"] = True

    if context is not None and not context.empty and context_needed > 0:
        # [OPT] Solo las columnas necesarias del contexto + sort unico
        ctx = context.copy()
        ctx["_sort_key"] = pd.to_datetime(ctx["price_date"], errors="coerce")
        ctx = ctx.sort_values(["sku", "_sort_key"], kind="stable").drop(columns=["_sort_key"])

        # [OPT] tail por SKU con include_groups=False para evitar DeprecationWarning
        tail_context = (
            ctx.groupby("sku", group_keys=False)[ctx.columns]
            .apply(lambda g: g.tail(context_needed), include_groups=False)
        )
        # include_groups=False excluye 'sku' del resultado, lo restauramos
        tail_context = ctx.loc[tail_context.index].copy()
        tail_context["_is_target"] = False

        combined = pd.concat([tail_context, target], ignore_index=True)
        # Sort final unico sobre combined
        combined["_sort_key"] = pd.to_datetime(combined["price_date"], errors="coerce")
        combined = combined.sort_values(["sku", "_sort_key"], kind="stable").drop(columns=["_sort_key"]).reset_index(drop=True)
    else:
        combined = target.reset_index(drop=True)

    combined = _add_lags(combined, col, lags)
    combined = _add_rolling_features(combined, col, windows)

    result = combined[combined["_is_target"]].drop(columns=["_is_target"]).reset_index(drop=True)
    return result


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

    [F3] update_history() permite encadenar el historial entre splits
    consecutivos (train → val → test), evitando que test "salte"
    directamente al historial de train ignorando val por completo.
    """

    def __init__(self, window: int = 90, col: str = "price_usd"):
        self.window = window
        self.col = col
        self.fitted_ = False
        self._history_ = {}   # sku -> últimos `window` valores conocidos

    def fit(self, df_train: pd.DataFrame):
        df_train = _sort_by_date(df_train)
        for sku, group in df_train.groupby("sku"):
            self._history_[sku] = group[self.col].tail(self.window).tolist()
        self.fitted_ = True
        return self

    def transform(self, df: pd.DataFrame, is_train: bool = False) -> pd.DataFrame:
        if not self.fitted_:
            raise RuntimeError("Debe llamar fit() sobre train antes de transform()")

        df = _sort_by_date(df)
        col_name = f"{self.col}_zscore_{self.window}"
        # [F4] Asignación explícita por índice — evita depender del
        # orden implícito de iteración de groupby().
        z_series = pd.Series(index=df.index, dtype="float64")

        for sku, group in df.groupby("sku"):
            idx = group.index
            values = group[self.col].tolist()
            history = self._history_.get(sku, []) if not is_train else []
            rolling_z = []

            buffer = list(history)  # contexto previo para val/test
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

            z_series.loc[idx] = rolling_z

        df[col_name] = z_series
        return df

    def update_history(self, df: pd.DataFrame):
        """
        [F3] Extiende el historial con un split ya transformado
        (p.ej. val), para que el SIGUIENTE split (test) continúe la
        ventana rolling sin salto temporal. Llamar DESPUÉS de
        transform(val) y ANTES de transform(test).
        """
        df = _sort_by_date(df)
        for sku, group in df.groupby("sku"):
            prev = self._history_.get(sku, [])
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
def run_feature_pipeline(input_dir: Path, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    print("═" * 60)
    print("  FEATURE ENGINEERING v1.1 — Etapa II")
    print("═" * 60)

    train = pd.read_csv(input_dir / "train.csv", low_memory=False)
    val   = pd.read_csv(input_dir / "val.csv",   low_memory=False)
    test  = pd.read_csv(input_dir / "test.csv",  low_memory=False)

    print(f"\n📊 Splits cargados: train={len(train):,} | val={len(val):,} | test={len(test):,}")

    # 1. Features deterministas (lags, MA, std) — no requieren fit.
    #    [F1] val/test usan `context` = split(s) anterior(es), para
    #    no perder las primeras ~30 filas de cada SKU por falta de
    #    historial (sin introducir leakage: el contexto es siempre
    #    cronológicamente anterior).
    print("\n🔧 Generando lags, medias móviles y volatilidad...")
    train_feat = build_features(train)
    val_feat   = build_features(val,  context=train)
    test_feat  = build_features(test, context=pd.concat([train, val], ignore_index=True))

    # 2. Rolling z-score — fit SOLO en train (anti-leakage)
    print("\n📐 Ajustando normalizador (rolling z-score, fit=train)...")
    normalizer = RollingZScoreNormalizer(window=90, col="price_usd")
    normalizer.fit(train_feat)

    train_feat = normalizer.transform(train_feat, is_train=True)
    val_feat   = normalizer.transform(val_feat,   is_train=False)
    normalizer.update_history(val_feat)  # [F3] encadena val antes de test
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
    print(f"   NaN en lag_30 (train)  : {train_feat['price_usd_lag_30'].isna().sum():,}")
    print(f"   NaN en lag_30 (val)    : {val_feat['price_usd_lag_30'].isna().sum():,} "
          f"(antes del fix [F1] esto era ~100% de las primeras filas por SKU)")
    print(f"   NaN en lag_30 (test)   : {test_feat['price_usd_lag_30'].isna().sum():,}")

    print("\n" + "═" * 60)
    print("  ✅ Etapa II completada — listo para modelos (Etapa III)")
    print("═" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Feature Engineering — Etapa II")
    parser.add_argument("--input-dir", required=True, help="Carpeta con train/val/test.csv")
    parser.add_argument("--output-dir", required=True, help="Carpeta de salida de features")
    args = parser.parse_args()

    run_feature_pipeline(Path(args.input_dir), Path(args.output_dir))
